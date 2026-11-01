"""Exact bounded legacy recommendation metadata from one native read snapshot.

PostgreSQL remains the persistent Store. Its existing in-memory FTS5 projection
also evaluates the source-owned SQLite timestamp/JSON expression over fresh
request-local metadata; no business database fallback or evidence cache exists.
"""
import json
import math
import sqlite3

MAX_ROWS = 200000
MAX_BYTES = 128 * 1024 * 1024

_RESOURCE_SCHEMA = '''CREATE TEMP TABLE ac_selection_resources(
 id INTEGER PRIMARY KEY,category TEXT,kind TEXT,url TEXT,eval_grade TEXT,eval_score REAL,eval_at REAL,
 last_ok_at REAL,last_check_at REAL,last_status_code INTEGER,health_ok_24h INTEGER,health_n_24h INTEGER,
 probe_latency_ms INTEGER,trial_ok INTEGER,trial_info TEXT,active INTEGER,health_status TEXT,eval_security TEXT)'''
_REPORT_SCHEMA = '''CREATE TEMP TABLE ac_selection_reports(
 id INTEGER PRIMARY KEY,resource_id INTEGER,kind TEXT,agent_url TEXT,executed_at REAL,created_at REAL,
 eval_grade TEXT,eval_score REAL,is_success INTEGER,status_code INTEGER,latency_ms INTEGER,tool_name TEXT,
 connection_version_id TEXT)'''
_ELIGIBILITY_SCHEMA = '''CREATE TEMP TABLE ac_selection_eligibility(
 resource_id INTEGER PRIMARY KEY,executed_at REAL,outcome TEXT,expires REAL)'''


def _error(store, code):
    from .application_store_postgres import ApplicationStoreError
    if getattr(store, '_depth', 0): store._failed = True
    raise ApplicationStoreError(code)


def _cost(rows):
    return sum(len(value.encode('utf-8')) if type(value) is str else len(value)
               if type(value) is bytes else 8 for row in rows for value in row)


class PostgresSelectionMixin:
    def selection_candidates(self, match, kind, cutoff):
        if (type(match) is not str or not 1 <= len(match) <= 4096 or '\0' in match
                or kind not in (None, 'a2a', 'mcp', 'x402')
                or type(cutoff) not in (int, float) or not -1e12 <= cutoff <= 1e12
                or not math.isfinite(cutoff)):
            _error(self, 'invalid_parameters')
        from .concierge.selection import _candidate_sql
        from .storage_adapter import Row
        with self.tx(readonly=True):
            fts = self._fts(match) if self._native_lexical else self._fts()
            # An in-memory main database alone does not constrain TEMP storage.
            fts.execute('PRAGMA temp_store=MEMORY')
            if fts.execute('PRAGMA temp_store').fetchone()[0] != 2:
                _error(self, 'projection_storage_unavailable')
            try:
                ids = [row[0] for row in fts.execute('SELECT rowid FROM documents WHERE documents MATCH ?', (match,))]
            except sqlite3.Error:
                _error(self, 'invalid_parameters')
            if len(ids) > MAX_ROWS: _error(self, 'result_limit')
            if not ids: return []
            packed = json.dumps(ids, separators=(',', ':'))
            resources = self._execute('''SELECT r.id,r.category,r.kind,r.url,r.eval_grade,r.eval_score,r.eval_at,
                r.last_ok_at,r.last_check_at,r.last_status_code,r.health_ok_24h,r.health_n_24h,
                r.probe_latency_ms,r.trial_ok,r.trial_info,r.active,r.health_status,r.eval_security
                FROM resources r WHERE r.id IN (SELECT value::bigint FROM jsonb_array_elements_text(%s::jsonb))
                  AND r.active=1 AND r.kind IN ('a2a','mcp','x402') AND (%s::text IS NULL OR r.kind=%s)
                  AND r.health_status IN ('healthy','reachable')
                  AND COALESCE(r.eval_security,'') NOT IN ('quarantine','review')''',
                (packed, kind, kind), max_rows=MAX_ROWS, max_bytes=MAX_BYTES).fetchall()
            if not resources: return []
            remaining = MAX_BYTES - _cost(resources)
            packed = json.dumps([row['id'] for row in resources], separators=(',', ':'))
            reports = self._execute('''SELECT t.id,t.resource_id,t.kind,t.agent_url,t.executed_at,t.created_at,
                t.eval_grade,t.eval_score,t.is_success,t.status_code,t.latency_ms,t.tool_name,t.connection_version_id
                FROM agent_test_reports t WHERE EXISTS(SELECT 1 FROM resources r
                  WHERE r.id IN (SELECT value::bigint FROM jsonb_array_elements_text(%s::jsonb))
                    AND t.kind=r.kind AND (t.resource_id=r.id OR t.agent_url=r.url))''',
                (packed,), max_rows=MAX_ROWS, max_bytes=remaining).fetchall()
            remaining -= _cost(reports)
            eligibility = self._execute('''SELECT resource_id,executed_at,outcome,expires FROM capability_eligibility
                WHERE resource_id IN (SELECT value::bigint FROM jsonb_array_elements_text(%s::jsonb))''',
                (packed,), max_rows=MAX_ROWS, max_bytes=remaining).fetchall()
            # Metadata is never reused merely because the FTS epoch is unchanged.
            # A savepoint removes all request-local tables even on invalid input.
            fts.execute('SAVEPOINT ac_selection_projection')
            try:
                for statement in (_RESOURCE_SCHEMA, _REPORT_SCHEMA, _ELIGIBILITY_SCHEMA): fts.execute(statement)
                fts.execute('CREATE INDEX ac_selection_report_resource ON ac_selection_reports(resource_id,kind)')
                fts.execute('CREATE INDEX ac_selection_report_url ON ac_selection_reports(agent_url,kind)')
                fts.executemany('INSERT INTO ac_selection_resources VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    [tuple(row) for row in resources])
                fts.executemany('INSERT INTO ac_selection_reports VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    [tuple(row) for row in reports])
                fts.executemany('INSERT INTO ac_selection_eligibility VALUES(?,?,?,?)', [tuple(row) for row in eligibility])
                # Table substitutions are fixed source names, never request data.
                query = (_candidate_sql().replace('resources_fts', 'documents')
                    .replace('agent_test_reports', 'ac_selection_reports')
                    .replace('capability_eligibility', 'ac_selection_eligibility')
                    .replace('JOIN resources r', 'JOIN ac_selection_resources r'))
                cursor = fts.execute(query, (match, kind, kind, cutoff, cutoff, cutoff))
                columns = tuple(item[0] for item in cursor.description)
                result = [Row(columns, tuple(row)) for row in cursor]
                if len(result) > MAX_ROWS or _cost(result) > MAX_BYTES: _error(self, 'result_limit')
                return result
            except sqlite3.Error:
                _error(self, 'statement_failed')
            finally:
                fts.execute('ROLLBACK TO ac_selection_projection')
                fts.execute('RELEASE ac_selection_projection')

    def selection_candidates_for(self, ids, kind, cutoff):
        """Fresh evidence for a bounded hybrid shortlist, with no FTS5 projection."""
        if (type(ids) is not list or len(ids)>600 or any(type(rid) is not int or not 0<rid<2**63 for rid in ids)
                or kind not in (None,'a2a','mcp','x402') or type(cutoff) not in (int,float) or not math.isfinite(cutoff)):
            _error(self,'invalid_parameters')
        if not ids:return []
        with self.tx(readonly=True):
            found=self._execute("""SELECT r.id,r.category,r.kind,r.url,r.eval_grade,r.eval_score,r.eval_at,
                r.last_ok_at,r.last_check_at,r.last_status_code,r.health_ok_24h,r.health_n_24h,
                r.probe_latency_ms,r.trial_ok,r.trial_info,
                t.id AS report_id,t.executed_at AS report_at,t.eval_grade AS report_grade,t.eval_score AS report_score,
                t.is_success AS report_success,t.status_code AS report_status,t.latency_ms AS report_latency,
                t.tool_name AS report_tool,t.connection_version_id AS report_version,t.created_at AS report_created_at,
                t.executed_at AS report_executed_at,ce.executed_at AS execution_at,
                ce.outcome AS execution_outcome,ce.expires AS execution_expires
                FROM resources r LEFT JOIN LATERAL (
                  SELECT id,executed_at,eval_grade,eval_score,is_success,status_code,latency_ms,tool_name,connection_version_id,created_at
                  FROM agent_test_reports WHERE kind=r.kind AND (resource_id=r.id OR agent_url=r.url)
                    AND executed_at IS NOT NULL AND connection_version_id IS NOT NULL
                  ORDER BY executed_at DESC,id DESC LIMIT 1
                ) t ON true LEFT JOIN capability_eligibility ce ON ce.resource_id=r.id
                WHERE r.id IN (SELECT value::bigint FROM jsonb_array_elements_text(%s::jsonb))
                  AND r.active=1 AND r.kind IN ('a2a','mcp','x402') AND (%s::text IS NULL OR r.kind=%s)
                  AND r.health_status IN ('healthy','reachable')
                  AND COALESCE(r.eval_security,'') NOT IN ('quarantine','review')""",
                (json.dumps(ids),kind,kind),max_rows=600,max_bytes=MAX_BYTES).fetchall()
        from datetime import datetime,timezone
        result=[]
        for raw in found:
            row=dict(raw);value=row['report_created_at']
            if value is not None:
                try:value=float(value)
                except (TypeError,ValueError):
                    try:
                        stamp=datetime.fromisoformat(str(value).replace('Z','+00:00'))
                        value=(stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp).timestamp()
                    except (ValueError,OverflowError):value=None
                row['report_created_at']=value
            result.append(row)
        return result

    def recommendation_report_evidence(self, ids):
        """Request-local report/evidence batches; never cache eligibility across requests."""
        if type(ids) is not list or len(ids)>600 or any(type(rid) is not int or not 0<rid<2**63 for rid in ids):
            _error(self,'invalid_parameters')
        reports={}
        evidence={}
        if ids:
            with self.tx(readonly=True):
                rows=self._execute('''SELECT id,resource_id,kind,agent_name,agent_url,evidence_scope,
                    connection_version_id,executed_at,execution_finished_at,is_success
                    FROM agent_test_reports WHERE id IN
                    (SELECT value::bigint FROM jsonb_array_elements_text(%s::jsonb))''',
                    (json.dumps(list(dict.fromkeys(ids))),),max_rows=600,max_bytes=MAX_BYTES).fetchall()
                reports={r['id']:dict(r)for r in rows}
                versions=list(dict.fromkeys(r['connection_version_id']for r in rows if r['connection_version_id']))
                if versions:
                    rows=self._execute('''SELECT * FROM (SELECT e.*,ROW_NUMBER() OVER
                        (PARTITION BY version_id ORDER BY finished DESC,recorded DESC,id DESC) AS recommendation_rn
                        FROM capability_evidence e WHERE scope='execution' AND version_id IN
                        (SELECT value FROM jsonb_array_elements_text(%s::jsonb))) batch
                        WHERE recommendation_rn=1''',(json.dumps(versions),),max_rows=600,max_bytes=MAX_BYTES).fetchall()
                    evidence={r['version_id']:[dict(r)]for r in rows}
        class Evidence:
            def query(self,sql,parameters=()):
                if sql != "SELECT * FROM capability_evidence WHERE version_id=? AND scope='execution' ORDER BY finished DESC,recorded DESC,id DESC LIMIT 1" or len(parameters)!=1:
                    raise ValueError('UNREVIEWED_REPORT_EVIDENCE_QUERY')
                return evidence.get(parameters[0],[])
        return reports,Evidence()

    def recommendation_resources(self, ids):
        """Read bounded candidate contracts together instead of one transaction per listing."""
        from .application_store_resource_batches import resources
        if type(ids) is not list or len(ids)>MAX_ROWS:
            _error(self,'invalid_parameters')
        found=[]
        with self.tx(readonly=True):
            for start in range(0,len(ids),1000):
                found.extend(resources(self,ids[start:start+1000],"active=1",()))
                if _cost(found)>MAX_BYTES:_error(self,'result_limit')
        return {row['id']:dict(row) for row in found}

    def find_existing_candidates(self, urls, keys, raw, trimmed):
        if (type(urls) not in (list, tuple) or type(keys) not in (list, tuple)
                or len(urls) > 32 or len(keys) > 96
                or any(type(value) is not str or not 1 <= len(value) <= 4104 or '\0' in value for value in (*urls, *keys))
                or any(type(value) is not str or len(value) > 4096 or '\0' in value for value in (raw, trimmed))):
            _error(self, 'invalid_parameters')
        if not urls and not keys: return []
        with self.tx(readonly=True):
            return self._execute('''SELECT id,name,kind,source,url,category,description,
                price_usdc,pay_to,method,networks,health_status FROM resources
                WHERE url IN (SELECT value FROM jsonb_array_elements_text(%s::jsonb))
                   OR key IN (SELECT value FROM jsonb_array_elements_text(%s::jsonb))
                ORDER BY active DESC,CASE WHEN url IN (%s,%s) THEN 0 ELSE 1 END,id ASC LIMIT 1''',
                (json.dumps(list(dict.fromkeys(urls))), json.dumps(list(dict.fromkeys(keys))), raw, trimmed)).fetchall()
