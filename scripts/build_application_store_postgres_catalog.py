"""Build the explicit application PostgreSQL SQL catalog from fixed repository source.

Only --check or --write is accepted; neither accepts a path or database address.
SQLite is an owned in-memory schema parser. No existing database or provider is
used. Runtime PostgreSQL executes the checked-in dialect pairs by exact lookup;
it never rewrites SQL, scans source or initializes a caller-selected schema.
Generated pairs remain reviewable and are covered by native application tests.
"""
import argparse
import ast
import hashlib
import itertools
import json
from pathlib import Path
import re
import sqlite3


def source_constant(node, environment=None, *, _depth=0):
    """Resolve only bounded literals and already-reviewed constant names."""
    if _depth > 24:
        raise ValueError('Source constant exceeds the nesting limit.')
    environment = {} if environment is None else environment
    resolve = lambda child: source_constant(child, environment, _depth=_depth + 1)
    if isinstance(node, ast.Constant) and type(node.value) in (str, int, float, bool, type(None)):
        if isinstance(node.value, str) and len(node.value) > 131072:
            raise ValueError('Source constant exceeds the size limit.')
        return node.value
    if isinstance(node, ast.Name) and node.id in environment:
        return environment[node.id]
    if isinstance(node, (ast.Tuple, ast.List)) and len(node.elts) <= 1000:
        return tuple(map(resolve, node.elts)) if isinstance(node, ast.Tuple) else list(map(resolve, node.elts))
    if isinstance(node, ast.Dict) and len(node.keys) <= 1000 and all(key is not None for key in node.keys):
        return {resolve(key): resolve(value) for key, value in zip(node.keys, node.values)}
    if isinstance(node, ast.JoinedStr) and len(node.values) <= 1000:
        parts = []
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                parts.append(resolve(part))
            elif (isinstance(part, ast.FormattedValue) and isinstance(part.value, ast.Name)
                  and part.conversion == -1 and part.format_spec is None
                  and part.value.id in environment and isinstance(environment[part.value.id], str)):
                parts.append(environment[part.value.id])
            else:
                raise ValueError('Unreviewed source constant expression.')
        result = ''.join(parts)
        if len(result) <= 131072:
            return result
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = resolve(node.left), resolve(node.right)
        if isinstance(left, str) and isinstance(right, str) and len(left) + len(right) <= 131072:
            return left + right
    raise ValueError('Unreviewed source constant expression.')


def stable_name(prefix, sql):
    """PREFIX plus the first 12 hex digits of the statement text's sha256 (whitespace collapsed).

    11-12 (PM): names carried the source line number or the list position, so one added line renamed
    hundreds of statements and every --check reported 'changed'. Runtime looks statements up by their
    normalized SQLite text only (application_store_postgres._STATEMENTS); the name is for review."""
    return prefix + '.' + hashlib.sha256(' '.join(sql.split()).encode()).hexdigest()[:12]


def build_catalog():
    from agent_market.gateway.store import Store
    root = Path(__file__).resolve().parents[1]
    methods='observation_guard observation_transaction resource upsert_resource upsert_page _upsert _text_constraints record_probe resource_counts feedback_stats record_tool_transition get_tool_transitions get_meta set_meta create_test_report get_test_report get_test_report_by_slug create_workflow get_workflow update_workflow delete_workflow fork_workflow record_customer_inquiry get_customer_inquiry update_customer_inquiry record_cancellation_request reactivate_cancellation record_privacy_request update_privacy_request get_customer_requests_summary health_history prune_health record_crawl_run record_evaluation_unavailable record_evaluation record_health _observation_time _supersede_observation _invalidate_survey_evaluation record_observed_quote record_auth record_capability record_usage set_category set_auth_observed mark_tool_level_auth record_scavenge_failure scavenger_stats in_use_ids agent_source_stats'.split()
    auth='authenticate_user create_session get_session_user delete_session change_user_password record_audit list_admin_users create_admin_user delete_admin_user'.split()
    entries=[]
    def convert(sql):
        # Build-time only lexical placeholder projection; output is a checked-in,
        # explicit SQL dialect pair. No runtime SQL is rewritten.
        out=[];quoted=False;i=0
        while i<len(sql):
            c=sql[i]
            if c=="'":
                out.append(c)
                if quoted and i+1<len(sql) and sql[i+1]=="'":out.append("'");i+=2;continue
                quoted=not quoted
            elif c=='?' and not quoted:out.append('%s')
            elif c=='%':out.append('%%')
            else:out.append(c)
            i+=1
        return ''.join(out)
    for file,names in [('agent_market/gateway/store.py',methods),('agent_market/gateway/admin_auth.py',auth)]:
        tree=ast.parse((root/file).read_text())
        for node in ast.walk(tree):
            if not isinstance(node,ast.FunctionDef) or node.name not in names:continue
            for call in ast.walk(node):
                if not isinstance(call,ast.Call) or not isinstance(call.func,ast.Attribute) or call.func.attr not in ('execute','query') or not call.args:continue
                arg=call.args[0]
                if not isinstance(arg,ast.Constant) or not isinstance(arg.value,str) or not re.match(r'\s*(SELECT|INSERT|UPDATE|DELETE)\b',arg.value,re.I):continue
                sql=arg.value;pg=convert(sql);lastrowid=None
                if 'INSERT OR REPLACE INTO resources_fts' in sql:
                    pg='INSERT INTO resources_fts(rowid,name,description) VALUES (%s,%s,%s) ON CONFLICT(rowid) DO UPDATE SET name=EXCLUDED.name,description=EXCLUDED.description'
                elif 'INSERT OR REPLACE INTO vec_outbox' in sql:
                    reason='new' if "'new'" in sql else 'changed'
                    pg="INSERT INTO vec_outbox(resource_id,enqueued_at,reason) VALUES (%s,%s,'"+reason+"') ON CONFLICT(resource_id) DO UPDATE SET enqueued_at=EXCLUDED.enqueued_at,reason=EXCLUDED.reason"
                elif sql in ("INSERT OR REPLACE INTO meta VALUES (?,?)", "INSERT OR REPLACE INTO meta VALUES (?, ?)"):
                    pg='INSERT INTO meta(key,value) VALUES (%s,%s) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value'
                elif 'INSERT OR REPLACE' in sql or 'INSERT OR IGNORE' in sql:
                    print('UNSUPPORTED',node.name,sql);continue
                if 'SUM(outcome IN' in pg:pg=pg.replace("SUM(outcome IN ('healthy','reachable'))","SUM(CASE WHEN outcome IN ('healthy','reachable') THEN 1 ELSE 0 END)")
                pg=pg.replace('MAX(COALESCE(observed_at,0),excluded.observed_at)','GREATEST(COALESCE(observed_at,0),excluded.observed_at)')
                if re.match(r'\s*INSERT INTO (resources|agent_test_reports|agent_workflows|admin_users)\b',sql,re.I):pg+=' RETURNING id';lastrowid='id'
                entries.append({'name':stable_name(('auth.' if 'admin_auth' in file else 'store.')+node.name,sql),'sqlite':sql,'postgres':pg,'readonly':bool(re.match(r'\s*SELECT\b',sql,re.I)),'generated_id':lastrowid})
    # Native schema collected from a new in-memory fixture only, never an operating DB.
    s=Store();db=s._db;schema=[];tables=[]
    for name,ddl in db.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'resources_fts%' AND name != 'resources_vocab' AND name NOT LIKE 'vec_resources%' ORDER BY name"):
        if 'VIRTUAL TABLE' in ddl:continue
        columns=list(db.execute('PRAGMA table_info("'+name+'")'));parts=[];pk=sorted((r['pk'],r['name']) for r in columns if r['pk'])
        for c in columns:
            typ={'INTEGER':'BIGINT','REAL':'DOUBLE PRECISION','TEXT':'TEXT','BLOB':'BYTEA'}[c['type'].upper()]
            text='"'+c['name']+'" '+typ
            if len(pk)==1 and pk[0][1]=='id' and typ=='BIGINT':text+=' GENERATED BY DEFAULT AS IDENTITY'
            if c['notnull'] or c['pk']:text+=' NOT NULL'
            if c['dflt_value'] is not None:text+=' DEFAULT '+c['dflt_value']
            parts.append(text)
        if pk:parts.append('PRIMARY KEY('+','.join('"'+col+'"' for _,col in pk)+')')
        unique=[]
        for idx in list(db.execute('PRAGMA index_list("'+name+'")')):
            if idx['unique'] and idx['origin']!='pk':
                cols=[r['name'] for r in db.execute('PRAGMA index_info("'+idx['name']+'")')]
                if None not in cols:unique.append(cols)
        for cols in unique:parts.append('UNIQUE('+','.join('"'+c+'"' for c in cols)+')')
        schema.append('CREATE TABLE IF NOT EXISTS "'+name+'" ('+','.join(parts)+')');tables.append(name)
    entries.append({'name':'workflow.bind_resource','sqlite':'SELECT id FROM resources WHERE kind=? AND url=? ORDER BY active DESC,id DESC LIMIT 1','postgres':'SELECT id FROM resources WHERE kind=%s AND url=%s ORDER BY active DESC,id DESC LIMIT 1','readonly':True,'generated_id':None})
    schema.append('CREATE TABLE IF NOT EXISTS resources_fts(rowid BIGINT PRIMARY KEY,name TEXT NOT NULL,description TEXT NOT NULL)')
    schema.append('CREATE TABLE IF NOT EXISTS application_store_state(id BIGINT PRIMARY KEY CHECK(id=1),profile TEXT NOT NULL,catalog_epoch BIGINT NOT NULL DEFAULT 0)')
    schema.append("INSERT INTO application_store_state(id,profile) VALUES(1,'application-postgres-store-v1') ON CONFLICT(id) DO NOTHING")
    # Explicit native constraints, absent from PRAGMA table_info metadata.
    schema += ["ALTER TABLE workflow_reviews ADD CONSTRAINT application_review_rating CHECK(rating BETWEEN 1 AND 5)"]
    result={'profile':'application-postgres-statements-v1','methods':methods,'staff_auth_functions':auth,'tables':tables+['resources_fts','application_store_state'],'schema':schema,'statements':entries}

    db.close()
    model=result;entries=model['statements'];seen={e['sqlite'].strip() for e in entries}
    modules=['admin_completion','managed_catalog','collector/health','collector/capabilities','collector/auth_discovery','collector/a2a','collector/agent','concierge/front','concierge/task_updates','concierge/memory','concierge/notify','concierge/security','concierge/proxy','concierge/clearinghouse','concierge/inertia','concierge/selection','concierge/fast_chat','concierge/contacts','gateway/store','gateway/admin_auth','gateway/dashboard','gateway/service','gateway/sns','gateway/visitor_desk','legacy_vector_index','customer_organizations','workspace_access','workspace_execution','customer_identity','customer_workspace_runtime','workspace_lifecycle','workspace_release','provider_claims','shadow_ledger','workflow_support','advancement_readiness','workflow_quality_review','workflow_product_composer','workspace_metering','workflows','workflow_persistence','workflow_fallback','workflow_budgets','workflow_operations','workflow_maintenance','execution_authority','capability_registry','observability','artifact_signing','private_artifact_keys','workflow_templates']
    # The static whitelist is intentional. The runtime never scans source or accepts
    # caller-chosen files/modules. SQL pairs are reviewed checked-in output.
    modules=sorted(set(modules)|{'public_availability','concierge/registration_service','concierge/public_inquiries','owned_data_agents/activation','owned_data_agents/dispatch','concierge/testbench_examples','evidence_rollups','reliability_evaluation','reliability_evaluation_worker','reliability_trust','reliability_routing','reliability_controls_restore','gateway/notification_preferences','collector/registries','gateway/server','gateway/deployment_security'}|{p.stem for p in (root/'agent_market').glob('workflow_*.py') if not p.stem.endswith('_fixtures') and p.stem != 'workflow_backup'}|{p.stem for p in (root/'agent_market').glob('workspace_*.py')},key=lambda name:(name!='workflows',name))
    modules=sorted(set(modules)|{'ledger','application_control_retention','customer_task_outcomes','customer_recovery','stripe_sandbox','reliability_early_stop','reliability_publication','reliability_circuit_automation','reliability_research','reliability_research_service','reliability_admission','reliability_admission_service','reliability_circuit', 'customer_authoring', 'customer_credits', 'customer_credit_service',
        'concierge/report_evidence','concierge/verification_summary','concierge/discovery_state','concierge/recovery','concierge/conditional_http','report_creation',
        'agent_access/storage','agent_access/catalog','agent_access/tasks','agent_access/events','agent_access/service','agent_access/projection','agent_access/pages'},key=lambda name:(name!='workflows',name))
    source=[];schemas=[];nodes=[]
    # Register only the evidence guard, not Edge operation names or native SQL.
    edge_path=root/'agent_market/edge_gateway/service.py';edge_raw=edge_path.read_bytes()
    source.append({'file':str(edge_path.relative_to(root)),'sha256':hashlib.sha256(edge_raw).hexdigest()})
    edge_tree=ast.parse(edge_raw)
    evidence_guard=next(n for n in ast.walk(edge_tree) if isinstance(n,ast.FunctionDef) and n.name=='record_mcp_evidence')
    nodes.extend(('edge_gateway/service',n) for n in ast.walk(evidence_guard)
        if isinstance(n,ast.Constant) and isinstance(n.value,str) and n.value.lstrip().startswith('SELECT '))
    for name in modules:
     p=root/'agent_market'/f'{name}.py'
     if not p.exists():continue
     raw=p.read_bytes();source.append({'file':str(p.relative_to(root)),'sha256':hashlib.sha256(raw).hexdigest()});tree=ast.parse(raw)
     if name=='workflow_postgres_archive':continue
     nodes.extend((name,n) for n in ast.walk(tree) if isinstance(n,ast.Constant) and isinstance(n.value,str))
     for node in tree.body:
      if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and (t.id=='SCHEMA' or name=='legacy_vector_index' and t.id=='_DDL') for t in node.targets):
       try:v=ast.literal_eval(node.value)
       except ValueError:continue
       vals=(v,) if isinstance(v,str) else tuple(v)
       schemas.extend((name,v) for v in vals if isinstance(v,str))
    # Native repositories have fixed PostgreSQL SQL already. Record their exact
    # source provenance without interpreting native placeholders as SQLite SQL.
    for name in ('application_store_collector', 'application_store_finance', 'credential_vault',
            'application_store_migration', 'application_runtime', 'application_writer_fence', 'application_store_selection', 'application_store_consumers', 'application_store_sns', 'postgres_restore_guard', 'postgres_archive_provider', 'postgres_operational_archive'):
     path=root/'agent_market'/f'{name}.py'
     if path.exists(): source.append({'file':str(path.relative_to(root)),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    s=Store();db=s._db
    for name,sql in schemas:
     try:db.executescript(sql)
     except sqlite3.Error as e:raise RuntimeError((name,str(e)))
    # Some current application domains declare tables in bounded constructors
    # rather than a module SCHEMA. Parse only single constant CREATE TABLE DDL
    # into the owned in-memory fixture, never a data/control statement.
    for name,node in nodes:
        sql=node.value
        if re.match(r'^\s*CREATE TABLE IF NOT EXISTS [a-z_][a-z0-9_]*\s*\(',sql,re.I):
            parts=[];pending=''
            for char in sql:
                pending+=char
                if char==';' and sqlite3.complete_statement(pending):parts.append(pending);pending=''
            if pending.strip():parts.append(pending)
            for part in parts:
                if re.match(r'^\s*CREATE TABLE IF NOT EXISTS [a-z_][a-z0-9_]*\s*\(',part,re.I):db.execute(part)
    # Workflow runtime-owned additive columns are explicit current source contracts.
    for col,decl in [('lease_until','REAL NOT NULL DEFAULT 0'),('owner','TEXT'),('fence','INTEGER NOT NULL DEFAULT 0'),('deadline','REAL'),('execution_outcome','TEXT')]:
     if col not in {r[1] for r in db.execute('PRAGMA table_info(workflow_runs)')}:db.execute('ALTER TABLE workflow_runs ADD COLUMN '+col+' '+decl)
    metadata={};native={};ddl=[];constraints={};sqlite_tables={}
    rowid_tables={'workspace_app_run_links','workspace_quality_assignments','workspace_support_proposals','workspace_readiness_declarations'}
    for row in db.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'resources_fts%' AND name!='resources_vocab' AND name NOT LIKE 'vec_resources%' ORDER BY name").fetchall():
     name,sql=row
     if 'VIRTUAL TABLE' in sql:continue
     sqlite_tables[name]=sql
     cols=list(db.execute('PRAGMA table_info("'+name+'")'));metadata[name]=[list(c) for c in cols];parts=[];pk=sorted((r['pk'],r['name']) for r in cols if r['pk'])
     for c in cols:
      mixed=(name in ('workspace_private_tickets','workspace_private_runs') and c['name']=='actor_user_id') or (name in ('workspace_drafts','workspace_versions') and c['name']=='created_by')
      typ='TEXT' if mixed else {'INTEGER':'BIGINT','REAL':'DOUBLE PRECISION','TEXT':'TEXT','BLOB':'BYTEA'}[c['type'].upper()]
      text='"'+c['name']+'" '+typ
      if len(pk)==1 and pk[0][1]==c['name'] and typ=='BIGINT' and (c['name'] in ('id','sequence') or 'AUTOINCREMENT' in sql):text+=' GENERATED BY DEFAULT AS IDENTITY'
      if c['notnull'] or c['pk']:text+=' NOT NULL'
      if c['dflt_value'] is not None:text+=' DEFAULT '+c['dflt_value']
      parts.append(text)
     if name in rowid_tables:parts.append('"_ac_rowid" BIGINT GENERATED ALWAYS AS IDENTITY')
     if pk:parts.append('PRIMARY KEY('+','.join('"'+col+'"' for _,col in pk)+')')
     for idx in list(db.execute('PRAGMA index_list("'+name+'")')):
      if idx['unique'] and idx['origin']!='pk':
       ic=[r['name'] for r in db.execute('PRAGMA index_info("'+idx['name']+'")')]
       if None not in ic:parts.append('UNIQUE('+','.join('"'+c+'"' for c in ic)+')')
     
     checks=re.findall(r'CHECK\s*\(([^()]*)\)',sql,re.I)
     for check in checks:parts.append('CHECK('+check+')')
     if name=='test_report_subject_claims':
      parts.append('FOREIGN KEY(report_id) REFERENCES agent_test_reports(id)')
     uniques=[]
     for idx in list(db.execute('PRAGMA index_list("'+name+'")')):
      if idx['unique'] and idx['origin']!='pk':
       values=[r['name'] for r in db.execute('PRAGMA index_info("'+idx['name']+'")')]
       if None not in values:uniques.append(values)
     constraints[name]={'primary':[c for _,c in pk],'unique':uniques,'checks':checks}
     native[name]='CREATE TABLE IF NOT EXISTS "'+name+'" ('+','.join(parts)+')';ddl.append(native[name])
    ddl.append('CREATE TABLE IF NOT EXISTS vec_resources(rowid BIGINT PRIMARY KEY,embedding BYTEA NOT NULL CHECK(octet_length(embedding)=3072))')
    # Keep base explicit corpus/state/constraint additions from first generation.
    ddl.extend(sql for sql in model['schema'] if re.match(r'(CREATE TABLE IF NOT EXISTS resources_fts|CREATE TABLE IF NOT EXISTS application_store_state|INSERT INTO application_store_state|ALTER TABLE workflow_reviews)',sql))

    def convert(sql):
     out=[];quoted=False;i=0
     while i<len(sql):
      c=sql[i]
      if c=="'":
       out.append(c)
       if quoted and i+1<len(sql) and sql[i+1]=="'":out.append("'");i+=2;continue
       quoted=not quoted
      elif c=='?' and not quoted:out.append('%s')
      elif c=='%':out.append('%%')
      else:out.append(c)
      i+=1
     return ''.join(out).replace("CAST(strftime('%%s','now') AS REAL)",
        'EXTRACT(EPOCH FROM clock_timestamp())')
    def boolean_sums(sql):
        positions=list(re.finditer(r'\bSUM\s*\(',sql,re.I))
        for match in reversed(positions):
            start=match.end();depth=1;quote=False;end=start
            while end<len(sql) and depth:
                char=sql[end]
                if char=="'":quote=not quote
                elif not quote and char=='(':depth+=1
                elif not quote and char==')':depth-=1
                end+=1
            if depth:continue
            expression=sql[start:end-1]
            if not expression.lstrip().upper().startswith('CASE') and re.search(r'[=<>]|\b(?:IS|IN|LIKE|BETWEEN)\b',expression,re.I):
                sql=sql[:start]+'('+expression+')::integer'+sql[end-1:]
        return sql

    def statement(name,sql):
     if sql.strip() in seen:return
     pg=boolean_sums(convert(sql));gen=None
     # Source-owned SQLite CASE predicates bind native boolean objects as 0/1.
     # This is a build-time projection of registered statements, never runtime SQL.
     pg=pg.replace('CASE WHEN %s THEN', 'CASE WHEN %s<>0 THEN')
     word=re.match(r'\s*(SELECT|INSERT|UPDATE|DELETE|CREATE)\b',sql,re.I)
     if not word:return
     if sql.lstrip().startswith('CREATE TABLE'):
      sql_for_name=sql.lstrip()
      m=re.match(r'CREATE TABLE IF NOT EXISTS (\w+)\s*\(',sql_for_name)
      if not m or m[1] not in native:return
      pg=native[m[1]]
     elif sql.startswith('CREATE INDEX'):
      if 'json_extract' in sql:return
     elif sql.startswith('INSERT OR IGNORE'):
      pg=convert(sql.replace('INSERT OR IGNORE','INSERT',1))+' ON CONFLICT DO NOTHING'
     elif sql.startswith('INSERT OR REPLACE'):
      m=re.match(r'INSERT OR REPLACE INTO (\w+)\s+(?:VALUES|\()',sql)
      if not m or m[1] not in metadata:return
      table=m[1];cols=[c[1] for c in metadata[table]];pk=[c[1] for c in metadata[table] if c[5]]
      if not pk:return
      pg=convert(sql.replace('INSERT OR REPLACE','INSERT',1))+' ON CONFLICT('+','.join('"'+c+'"' for c in pk)+') DO UPDATE SET '+','.join('"'+c+'"=EXCLUDED."'+c+'"' for c in cols if c not in pk)
     if 'sqlite_master' in sql or 'sqlite_schema' in sql:
      m=re.fullmatch("SELECT 1 FROM sqlite_(?:master|schema) WHERE type='table' AND name='(\w+)'",sql)
      if not m:return
      pg="SELECT 1 FROM information_schema.tables WHERE table_schema=current_schema() AND table_name='"+m[1]+"'"
     # These are the only private JSON projection paths and types in this profile.
     for field,kind in [('created','double precision'),('expires','double precision'),('customer_id','text'),('owner','text')]:
      pg=pg.replace("json_extract(payload,'$."+field+"')", "((payload::jsonb)->>'"+field+"')::"+kind)
     pg=pg.replace("json_extract(g.payload,'$.max_runs')", "((g.payload::jsonb)->>'max_runs')::bigint")
     pg=pg.replace("json_extract(receipt, '$.latency_ms')", "((receipt::jsonb)->>'latency_ms')::double precision")
     pg=pg.replace("json_extract(m.value, '$.\"' || o.resource_id || '\".reset_at')",
        "(m.value::jsonb -> o.resource_id::text ->> 'reset_at')::double precision")
     if re.search(r'\browid\b',sql):
      if 'vec_resources' not in sql:
       if not any(table in sql for table in rowid_tables):return
       pg=re.sub(r'\browid\b','_ac_rowid',pg)
     pg=re.sub(r'%s(?=\s+IS\s+(?:NOT\s+)?NULL\b)', '%s::text', pg, flags=re.I)
     # SQLite's scalar MIN and integer truncation define exact rolling-hour
     # bucket boundaries; PostgreSQL's float-to-integer cast would round.
     pg=pg.replace('MIN(23,CAST((finished-%s)/3600 AS INTEGER))',
        'LEAST(23,TRUNC((finished-%s)/3600)::integer)')
     # PostgreSQL requires the aggregate expression type for ROUND's precision form.
     pg=pg.replace('ROUND(AVG(d.elapsed_ms),2)','ROUND(AVG(d.elapsed_ms)::numeric,2)').replace('ROUND(MAX(d.elapsed_ms),2)','ROUND(MAX(d.elapsed_ms)::numeric,2)')
     if re.match(r'\s*INSERT INTO (workspace_access_audit|customer_workspace_audit|workflow_fallback_audit)\b',sql):
      # Existing callers do not consume these generated IDs; defaults suffice.
      pass
     entries.append({'name':name,'sqlite':sql,'postgres':pg,'readonly':word[1].upper()=='SELECT','generated_id':gen});seen.add(sql.strip())
    # Match complete constant SQL, including compile-time adjacent literals, not
    # f-string fragments or concatenation pieces. Runtime values never become SQL.
    for name,node in nodes:
     sql=node.value
     if not re.match(r'^\s*(SELECT|INSERT|UPDATE|DELETE|CREATE)\b',sql,re.I):continue
     # Native report enforcement is installed and attested by _invariant_ddl;
     # the SQLite startup trigger is never an executable native SQL pair.
     if name=='report_creation' and sql.lstrip().startswith('CREATE TRIGGER IF NOT EXISTS report_creation_insert'):
      continue
     
     if len(sql)>65536:continue
     segments=[];pending=''
     for char in sql:
      pending+=char
      if char==';' and sqlite3.complete_statement(pending):segments.append(pending);pending=''
     if pending.strip():segments.append(pending)
     if len(segments)>1:continue
     statement(stable_name(name+'.source',sql),sql)
    script_entries={}
    for name,script in schemas:
     # Native SQLite only parses trusted source scripts in the owned fixture. This
     # character iterator honors strings/triggers through complete_statement().
     pending='';parts=[]
     for char in script:
      pending+=char
      if char==';' and sqlite3.complete_statement(pending):parts.append(pending.strip().rstrip(';'));pending=''
     if pending.strip():parts.append(pending.strip())
     for sql in parts:statement(stable_name(name+'.schema',sql),sql)
     script_entries[script]=parts
    # Exact dynamic forms emitted only by current fixed source allowlists.
    for name,cols in [('workspace_private_tickets',['id','workspace_id','draft_id','snapshot_id','actor_user_id','created','expires','payload','signature','run_id','revoked']),('workspace_private_runs',[])]:pass

    # Bounded variants of the fixed legacy vector query families. MAX_BATCH=50
    # also bounds explicit resource/expected-resource filters; zero means no
    # filter. Only placeholder counts vary, never predicates or identifiers.
    eligible="active=1 AND COALESCE(health_status,'unknown')!='retired' AND COALESCE(eval_security,'')!='quarantine'"
    selection=""" AND NOT EXISTS(
                    SELECT 1 FROM legacy_vector_heads h JOIN legacy_vector_jobs j USING(job_id)
                    WHERE h.resource_id=resources.id AND j.status IN ('pending','claimed','failed'))
                    AND NOT EXISTS(SELECT 1 FROM legacy_vector_provenance p
                        JOIN legacy_vector_heads h USING(resource_id) JOIN legacy_vector_generations g USING(resource_id)
                        WHERE p.resource_id=resources.id AND p.job_id=h.job_id AND p.generation=g.generation
                        AND p.descriptor_hash=?)"""
    for count in range(51):
     where='' if count==0 else ' AND id IN ('+','.join('?' for _ in range(count))+')'
     statement('vector.ensure.'+str(count),'SELECT id FROM resources WHERE '+eligible+where+(selection if count==0 else '')+' ORDER BY id LIMIT ?')
     clause='' if count==0 else ' AND j.resource_id IN ('+','.join('?' for _ in range(count))+')'
     statement('vector.supersede_stale_heads.'+str(count),"""UPDATE legacy_vector_jobs SET status='superseded',finished=?,lease_until=NULL
                WHERE job_id IN (SELECT j.job_id FROM (SELECT j.* FROM legacy_vector_jobs j
                JOIN legacy_vector_heads h USING(job_id)
                WHERE (j.status='pending' OR (j.status='claimed' AND j.lease_until<=?))"""
                +clause+' ORDER BY j.created,j.job_id LIMIT ?) j '+"""
                LEFT JOIN resources r ON r.id=j.resource_id
                LEFT JOIN legacy_vector_generations g ON g.resource_id=j.resource_id
                WHERE r.id IS NULL OR COALESCE(r.active,0)!=1 OR r.health_status='retired'
                    OR r.eval_security='quarantine' OR g.generation IS NULL OR g.generation!=j.generation)""")
     statement('vector.claim.'+str(count),"""SELECT j.* FROM legacy_vector_jobs j JOIN legacy_vector_heads h USING(job_id)
                JOIN resources r ON r.id=j.resource_id
                JOIN legacy_vector_generations g ON g.resource_id=j.resource_id AND g.generation=j.generation
                WHERE r.active=1 AND COALESCE(r.health_status,'unknown')!='retired'
                AND COALESCE(r.eval_security,'')!='quarantine'
                AND j.attempts<3 AND j.not_before<=? AND (j.status='pending' OR (j.status='claimed' AND j.lease_until<=?))"""+clause+' ORDER BY j.created,j.job_id LIMIT ?')
    # The admin preference view emits precisely these eight source-owned
    # combinations. Search text, state, channel and pagination stay bound.
    preferences=ast.parse((root/'agent_market/gateway/notification_preferences.py').read_text())
    preference_list=next(node for node in ast.walk(preferences) if isinstance(node,ast.FunctionDef) and node.name=='list')
    fragments=[node.value for node in ast.walk(preference_list) if isinstance(node,ast.Constant) and isinstance(node.value,str)]
    count_sql=next(value for value in fragments if value.lstrip().startswith('SELECT COUNT(*) AS total'))
    page_sql=next(value for value in fragments if value.lstrip().startswith('SELECT w.*'))
    orders=next(value for value in fragments if value.startswith(' ORDER BY MAX('))
    search=next(value for value in fragments if value.startswith('(w.id LIKE'))
    for selected in itertools.product((False,True),repeat=3):
     predicates=[value for value,include in zip((search,'w.state=?','w.channel=?'),selected) if include]
     where=' WHERE '+' AND '.join(predicates) if predicates else ''
     statement('notification.preferences.count',count_sql+where)
     query=page_sql+where+orders
     statement('notification.preferences.list',query)
     entries[-1]['postgres']=entries[-1]['postgres'].replace('MAX(w.created,COALESCE(latest_action,0))',
       'GREATEST(w.created,COALESCE((SELECT MAX(p.at) FROM agent_task_permissions p WHERE p.watch_id=w.id),0))')
    # The public query builders have finite source-owned predicate/order choices.
    # Resolve only literal declarations and named constants at build time. Values
    # and FTS expressions remain runtime parameters, never SQL identifiers.
    front=ast.parse((root/'agent_market/concierge/front.py').read_text())
    constants={}
    for node in front.body:
     if isinstance(node,ast.Assign):
      for target in node.targets:
       if isinstance(target,ast.Name) and target.id in ('REPORT_SUBJECT_COND','REPORT_CONDS','REPORT_HISTORY_COND','VERIFIED_EXECUTION_COND','VERIFIED_COND','CARD_COLS','LIVE_COND'):
        constants[target.id]=source_constant(node.value,constants)
    explore=next(node for node in front.body if isinstance(node,ast.FunctionDef) and node.name=='get_front_explore')
    predicates={}
    for node in explore.body:
     if isinstance(node,ast.If) and isinstance(node.test,ast.Name) and node.test.id in ('category','verified','no_auth','has_report'):
      calls=[part.value for part in node.body if isinstance(part,ast.Expr)
        and isinstance(part.value,ast.Call) and isinstance(part.value.func,ast.Attribute)
        and isinstance(part.value.func.value,ast.Name) and part.value.func.value.id=='conds'
        and part.value.func.attr in ('append','extend')]
      if not calls:continue
      # extend() takes one reviewed tuple constant of predicate strings.
      parts=[]
      for call in calls:
       value=source_constant(call.args[0],constants)
       if call.func.attr=='extend' and not (type(value) is tuple and all(type(item) is str for item in value)):
        raise ValueError('Unreviewed Explore predicate builder.')
       parts.extend(value if call.func.attr=='extend' else (value,))
      expected=2 if node.test.id=='has_report' else 1
      if len(parts)!=expected or node.test.id in predicates:raise ValueError('Unreviewed Explore predicate builder.')
      predicates[node.test.id]=' AND '.join(parts)
    if set(predicates)!=set(('category','verified','no_auth','has_report')):
     raise ValueError('Missing reviewed Explore predicates.')
    for selected in itertools.product((False,True),repeat=4):
     base=constants['REPORT_HISTORY_COND'] if selected[3] and not selected[1] else constants['LIVE_COND']
     clauses=[base]+[predicates[name] for name,include in zip(('category','verified','no_auth','has_report'),selected) if include]
     for with_kind in (False,True):
      where=' AND '.join(clauses+(['r.kind=?'] if with_kind else []))
      statement('front.explore.count','SELECT COUNT(*) AS c FROM resources r WHERE '+where)
      statement('front.explore.list','SELECT '+constants['CARD_COLS']+' FROM resources r WHERE '+where+' ORDER BY COALESCE(r.first_seen, 0) DESC, r.id DESC LIMIT ?')
      report_from=' FROM resources_fts f JOIN resources r ON r.id=f.rowid WHERE resources_fts MATCH ? AND '+where
      native_matches='WITH matches AS (SELECT (value->>0)::bigint AS id,(value->>1)::double precision AS rank FROM json_array_elements(%s::json)) '
      native_from=' FROM resources r JOIN matches m ON r.id=m.id WHERE '+convert(where)
      count_from=report_from if selected[3] else ' FROM resources_fts f CROSS JOIN resources r WHERE r.id=f.rowid AND resources_fts MATCH ? AND '+where
      count_sql='SELECT COUNT(*) AS c'+count_from
      entries.append({'name':'front.explore.report.fts.count' if selected[3] else 'front.explore.fts.count',
          'sqlite':count_sql,'postgres':native_matches+'SELECT COUNT(*) AS c'+native_from,
          'readonly':True,'generated_id':None,'adapter':'explore-fts5-count-v1','parameter_count':count_sql.count('?')})
      seen.add(count_sql.strip())
      if selected[3]:
       statement('front.explore.report.list','SELECT '+constants['CARD_COLS']+' FROM resources r WHERE '+where+' ORDER BY COALESCE(r.first_seen, 0) DESC, r.id DESC LIMIT ? OFFSET ?')
       sql='SELECT '+constants['CARD_COLS']+report_from+' ORDER BY bm25(resources_fts) - COALESCE(r.eval_score, 50) / 100.0 - (r.trial_ok IS 1) * 0.5, r.id DESC LIMIT ? OFFSET ?'
       pg=native_matches+'SELECT '+constants['CARD_COLS']+native_from+' ORDER BY m.rank-COALESCE(r.eval_score,50)/100.0-CASE WHEN r.trial_ok=1 THEN 0.5 ELSE 0 END, r.id DESC LIMIT %s OFFSET %s'
       entries.append({'name':'front.explore.report.fts.page','sqlite':sql,'postgres':pg,'readonly':True,
           'generated_id':None,'adapter':'explore-fts5-page-v1','parameter_count':sql.count('?')})
       seen.add(sql.strip())
      if with_kind:
       sql='SELECT '+constants['CARD_COLS']+' FROM resources_fts f JOIN resources r ON r.id=f.rowid WHERE resources_fts MATCH ? AND '+where+' ORDER BY bm25(resources_fts) - COALESCE(r.eval_score, 50) / 100.0 - (r.trial_ok IS 1) * 0.5 LIMIT ?'
       native_query='''WITH matches AS (SELECT (value->>0)::bigint AS id,(value->>1)::double precision AS rank
           FROM json_array_elements(%s::json)) SELECT '''+constants['CARD_COLS']+''' FROM resources r JOIN matches m ON r.id=m.id WHERE '''+convert(where)+''' ORDER BY m.rank-COALESCE(r.eval_score,50)/100.0-CASE WHEN r.trial_ok=1 THEN 0.5 ELSE 0 END LIMIT %s'''
       entries.append({'name':'front.explore.fts','sqlite':sql,'postgres':native_query,'readonly':True,'generated_id':None,
           'adapter':'explore-fts5-v1','parameter_count':sql.count('?')})
       seen.add(sql.strip())
    insights=next(node for node in front.body if isinstance(node,ast.FunctionDef) and node.name=='get_front_insights')
    values={node.targets[0].id:source_constant(node.value,constants) for node in insights.body
        if isinstance(node,ast.Assign) and isinstance(node.targets[0],ast.Name) and node.targets[0].id in ('base','featured_sql')}
    choices=[(item[2],item[3]) for group in values['featured_sql'].values() for item in group]
    def fixed_fstring(node,environment):
     if not isinstance(node,ast.JoinedStr):return None
     parts=[]
     for value in node.values:
      if isinstance(value,ast.Constant):parts.append(value.value)
      elif isinstance(value,ast.FormattedValue) and isinstance(value.value,ast.Name) and value.value.id in environment and value.format_spec is None:
       parts.append(environment[value.value.id])
      else:raise ValueError('Unreviewed public query expression.')
     return ''.join(parts)
    for node in ast.walk(insights):
     if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='q' and node.args and isinstance(node.args[0],ast.JoinedStr):
      for condition,order in choices:
       sql=fixed_fstring(node.args[0],{**constants,'base':values['base'],'cond':condition,'order':order})
       statement('front.insights',sql)
    report_store=ast.parse((root/'agent_market/gateway/store.py').read_text())
    report_list=next(node for node in ast.walk(report_store)
        if isinstance(node,ast.FunctionDef) and node.name=='list_test_reports')
    report_templates=[call.args[0] for call in ast.walk(report_list)
        if isinstance(call,ast.Call) and isinstance(call.func,ast.Attribute)
        and call.func.attr=='query' and call.args and isinstance(call.args[0],ast.JoinedStr)]
    if len(report_templates)!=2:raise ValueError('Unreviewed report list builder.')
    report_predicates=('kind = ?','category = ?','eval_grade = ?','is_success = ?',
                       'tags LIKE ?','(title LIKE ? OR agent_name LIKE ? OR summary LIKE ? OR tags LIKE ?)')
    for selected in itertools.product((False,True),repeat=6):
     clauses=[value for value,include in zip(report_predicates,selected) if include]
     where='WHERE '+' AND '.join(clauses) if clauses else ''
     for template in report_templates:
      sql=fixed_fstring(template,{'where':where})
      statement('admin.test_reports',sql)
      entry=next(item for item in reversed(entries) if item['sqlite'].strip()==sql.strip())
      for field in ('title','agent_name','summary','tags'):
       entry['postgres']=entry['postgres'].replace(field+' LIKE %s',
           "translate("+field+",'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz') LIKE translate(%s,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz') ESCAPE ''")
    # Reviewed desktop admin builders. Only finite, source-owned predicate and
    # order choices become SQL; every request value remains a placeholder.
    dashboard=ast.parse((root/'agent_market/gateway/dashboard.py').read_text())
    functions={node.name:node for node in ast.walk(dashboard) if isinstance(node,ast.FunctionDef)}
    def function_strings(tree):
     return [node.value for node in ast.walk(tree) if isinstance(node,ast.Constant) and isinstance(node.value,str)]
    def admin_statement(name,sql):
     statement(name,sql)
     entry=next(item for item in reversed(entries) if item['sqlite'].strip()==sql.strip())
     pg=entry['postgres']
     # SQLite NOCASE and LIKE fold ASCII only. PostgreSQL locale-dependent
     # ILIKE would change that contract. Bytewise C order follows UTF-8.
     pg=pg.replace('r.name COLLATE NOCASE',"translate(r.name,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz') COLLATE \"C\"")
     for field in ('r.name','r.url','r.description','r.category','n.task','n.client','ip'):
      expression=field+' LIKE %s'
      folded="translate("+field+",'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz') LIKE translate(%s,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz') ESCAPE ''"
      pg=pg.replace(expression,folded)
     pg=pg.replace('(r.trial_ok IS 1)','CASE WHEN r.trial_ok=1 THEN 1 ELSE 0 END')
     pg=re.sub(r'r.eval_score DESC(?! NULLS LAST)', 'r.eval_score DESC NULLS LAST', pg)
     pg=pg.replace("(r.health_status='healthy') DESC,","(r.health_status='healthy') DESC NULLS LAST,")
     entry['postgres']=pg
    agent=functions['agents']
    sort_node=next(node for node in ast.walk(dashboard) if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='SORTS' for t in node.targets))
    sorts=ast.literal_eval(sort_node.value)
    agent_templates=[call.args[0] for call in ast.walk(agent) if isinstance(call,ast.Call) and isinstance(call.func,ast.Attribute) and call.func.attr=='execute' and call.args and isinstance(call.args[0],ast.JoinedStr)]
    for choices in itertools.product((False,True),repeat=7):
     predicates=[value for value,include in zip(('r.active=?','r.kind=?','r.health_status=?','r.category=?','r.source=?','r.eval_grade=?','(r.name LIKE ? OR r.url LIKE ? OR r.description LIKE ?)'),choices) if include]
     where=' AND '.join(predicates) or '1=1'
     for order in sorts.values():
      for template in agent_templates:admin_statement('admin.agents',fixed_fstring(template,{'where':where,'order':order}))
    need=functions['needs']
    templates=[node.value for node in ast.walk(need) if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id in ('count_query','data_query') for t in node.targets)]
    for choices in itertools.product((False,True),repeat=3):
     predicates=[value for value,include in zip(('n.status = ?','n.category = ?','(n.task LIKE ? OR n.client LIKE ? OR r.name LIKE ?)'),choices) if include]
     where='WHERE '+' AND '.join(predicates) if predicates else ''
     for template in templates:admin_statement('admin.needs',fixed_fstring(template,{'where_clause':where}))
    for bucket in (300,900,3600):
     for call in ast.walk(functions['timeseries']):
      if isinstance(call,ast.Call) and isinstance(call.func,ast.Attribute) and call.func.attr=='execute' and call.args:
       sql=fixed_fstring(call.args[0],{'bucket':str(bucket)})
       admin_statement('admin.timeseries',sql)
       entry=next(item for item in reversed(entries) if item['sqlite'].strip()==sql.strip())
       entry['postgres']=entry['postgres'].replace('CAST(at / '+str(bucket)+' AS INT)', 'TRUNC(at / '+str(bucket)+')::bigint')
    dashboard_constants={}
    for node in ast.walk(dashboard):
     if isinstance(node,ast.Assign):
      for target in node.targets:
       if isinstance(target,ast.Name) and target.id in ('CARD_COLS','LIVE') and isinstance(node.value,ast.Constant):
        dashboard_constants[target.id]=ast.literal_eval(node.value)
    insight=functions['insights']
    insight_values={node.targets[0].id:ast.literal_eval(node.value) for node in ast.walk(insight)
        if isinstance(node,ast.Assign) and isinstance(node.targets[0],ast.Name) and node.targets[0].id in ('base','featured_sql')}
    featured=[(item[2],item[3]) for group in insight_values['featured_sql'].values() for item in group]
    for call in ast.walk(insight):
     if isinstance(call,ast.Call) and isinstance(call.func,ast.Name) and call.func.id=='q' and call.args and isinstance(call.args[0],ast.JoinedStr):
      for condition,order in featured:
       sql=fixed_fstring(call.args[0],{**dashboard_constants,'base':insight_values['base'],'cond':condition,'order':order})
       admin_statement('admin.insights',sql)
    explorer=functions['explore']
    templates=[call.args[0] for call in ast.walk(explorer) if isinstance(call,ast.Call) and isinstance(call.func,ast.Attribute) and call.func.attr=='execute' and call.args and isinstance(call.args[0],ast.JoinedStr)]
    for choices in itertools.product((False,True),repeat=3):
     predicates=[dashboard_constants['LIVE']]+[value for value,include in zip(('r.category=?','r.trial_ok=1',"(COALESCE(r.auth_observed, r.auth_declared, 0)=0 OR r.kind='x402')"),choices) if include]+['r.kind=?']
     where=' AND '.join(predicates)
     for template in templates:
      sql=fixed_fstring(template,{**dashboard_constants,'where':where})
      if 'resources_fts MATCH ?' in sql:
       pg="""WITH matches AS (SELECT (value->>0)::bigint AS id,(value->>1)::double precision AS rank FROM json_array_elements(%s::json)) SELECT """+dashboard_constants['CARD_COLS']+' FROM resources r JOIN matches m ON m.id=r.id WHERE '+convert(where)+" ORDER BY m.rank-COALESCE(r.eval_score,50)/100.0-CASE WHEN r.trial_ok=1 THEN 0.5 ELSE 0 END LIMIT %s"
       if sql.strip() not in seen:
        entries.append({'name':'admin.explore.fts','sqlite':sql,'postgres':pg,'readonly':True,'generated_id':None,'adapter':'explore-fts5-v1','parameter_count':sql.count('?')});seen.add(sql.strip())
      else:
       admin_statement('admin.explore.list',sql)
       entry=next(item for item in reversed(entries) if item['sqlite'].strip()==sql.strip())
       entry['postgres']=entry['postgres'].replace('r.first_seen DESC,','r.first_seen DESC NULLS LAST,').replace('(r.trial_ok=1) DESC,','(r.trial_ok=1) DESC NULLS LAST,')
    def finite_template(node,values):
     return ''.join(part.value if isinstance(part,ast.Constant) else values for part in node.values)
    test_agents=functions['test_agents']
    test_template=next(node.value for node in ast.walk(test_agents) if isinstance(node,ast.Assign) and isinstance(node.value,ast.JoinedStr) and any(isinstance(t,ast.Name) and t.id=='sql' for t in node.targets))
    from agent_market.broker.categories import CATEGORIES
    for with_kind in (False,True):
     initial=['r.active = 1']+(['r.kind = ?'] if with_kind else [])
     variants=[[],['(r.id = ? OR r.name LIKE ? OR r.url LIKE ?)'],['(r.name LIKE ? OR r.url LIKE ? OR r.description LIKE ? OR r.category LIKE ?)']]
     variants += [['(r.name LIKE ? OR r.url LIKE ? OR r.description LIKE ? OR r.category IN ('+','.join('?' for _ in range(count))+'))'] for count in range(1,len(CATEGORIES)+2)]
     for extra in variants:admin_statement('admin.test_agents',finite_template(test_template,' AND '.join(initial+extra)))
    alternatives=functions['get_workflow_agent_alternatives']
    templates=[node for node in ast.walk(alternatives) if isinstance(node,ast.JoinedStr) and isinstance(node.values[0],ast.Constant) and node.values[0].value.lstrip().startswith('SELECT r.id')]
    for with_kind,with_category,with_query in itertools.product((False,True),repeat=3):
     clauses=["r.active = 1", "r.health_status IN ('healthy','reachable')"]
     if with_kind:clauses.append('r.kind = ?')
     if with_category:clauses.append('(r.category = ? OR r.category LIKE ?)')
     if with_query:clauses.append('(r.name LIKE ? OR r.description LIKE ? OR r.url LIKE ?)')
     for template in templates:admin_statement('admin.workflow_alternatives',finite_template(template,' AND '.join(clauses)))
    # Constant-cardinality metadata keys used by the overview.
    meta_keys=next(ast.literal_eval(node.value) for node in dashboard.body if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='META_KEYS' for t in node.targets))
    statement('admin.overview.meta',"SELECT key, value FROM meta WHERE key IN ("+','.join('?'*len(meta_keys))+") OR key LIKE 'crawl_pass:%' OR key LIKE 'erc8004_next:%' OR key LIKE 'erc8004_rescan:%'")
    admin_auth=ast.parse((root/'agent_market/gateway/admin_auth.py').read_text())
    for choices in itertools.product((False,True),repeat=3):
     predicates=[value for value,include in zip(('action = ?','username = ?','status = ?'),choices) if include]
     where='WHERE '+' AND '.join(predicates) if predicates else ''
     statement('admin.audit.count','SELECT COUNT(*) FROM admin_audit_logs '+where)
     statement('admin.audit.list','SELECT * FROM admin_audit_logs '+where+' ORDER BY at DESC LIMIT ? OFFSET ?')
    for choices in itertools.product((False,True),repeat=4):
     fields=[value for values,include in zip((['name = ?'],['role = ?'],['active = ?'],['password_hash = ?','salt = ?']),choices) if include for value in values]
     if fields:statement('admin.users.update','UPDATE admin_users SET '+', '.join(fields+['updated_at = ?'])+' WHERE id = ?')
    for active in ('AND active=1',''):
     statement('visitor.interests','SELECT * FROM agent_interests WHERE visitor_id=? AND updated>=? '+active+' ORDER BY updated DESC')
    for table in ('agent_messages','agent_interests','agent_contexts','agent_outcomes','agent_visitor_cases','agent_visitor_case_notes'):
     statement('visitor.prune','DELETE FROM '+table+' WHERE visitor_id=?')
    for with_visitor in (False,True):
     statement('task_updates.due',"SELECT e.* FROM agent_task_events e JOIN agent_task_watches w ON w.id=e.watch_id WHERE e.status='pending' AND e.next_attempt<=?"+(' AND w.visitor_id=?' if with_visitor else '')+' ORDER BY e.created LIMIT 20')
    for where in ('','WHERE action=?'):
     statement('security.rules','SELECT ip, action, reason, created_at, expires_at, blocked_hits, last_hit_at FROM security_ip_rules '+where+' ORDER BY created_at DESC LIMIT ?')
    for choices in itertools.product((False,True),repeat=2):
     predicates=[value for value,include in zip(('event_type=?','ip LIKE ?'),choices) if include]
     where='WHERE '+' AND '.join(predicates) if predicates else ''
     admin_statement('security.events','SELECT id, at, ip, event_type, path, method, user_agent, detail FROM security_events '+where+' ORDER BY id DESC LIMIT ?')
    # ERC-8004 legacy maintenance uses only constant host-set cardinalities.
    registries=ast.parse((root/'agent_market/collector/registries.py').read_text())
    host_sets={target.id:ast.literal_eval(node.value) for node in registries.body if isinstance(node,ast.Assign)
        for target in node.targets if isinstance(target,ast.Name) and target.id in ('IPFS_HOSTS','SHARED_HOSTS')}
    for function in (node for node in ast.walk(registries) if isinstance(node,ast.FunctionDef) and node.name in ('_migrate','defer_dead_hosts')):
     for call in ast.walk(function):
      if not isinstance(call,ast.Call) or not isinstance(call.func,ast.Attribute) or call.func.attr not in ('execute','query') or not call.args or not isinstance(call.args[0],ast.JoinedStr):continue
      parts=[]
      for value in call.args[0].values:
       if isinstance(value,ast.Constant):parts.append(value.value)
       elif isinstance(value,ast.FormattedValue):
        names={part.id for part in ast.walk(value.value) if isinstance(part,ast.Name)}
        constants={'gateways':'IPFS_HOSTS','shared':'SHARED_HOSTS','SHARED_HOSTS':'SHARED_HOSTS'}
        selected=[constants[name] for name in names if name in constants]
        if len(selected)!=1:raise ValueError('Unreviewed registry query builder.')
        parts.append(','.join('?'*len(host_sets[selected[0]])))
       else:raise ValueError('Unreviewed registry query builder.')
      statement('collector.registry.hosts',''.join(parts))
    from scripts.application_postgres_extra_families import build_extra_families
    build_extra_families(root,statement,entries)
    extra_helper=root/'scripts/application_postgres_extra_families.py'
    source.append({'file':'scripts/application_postgres_extra_families.py','sha256':hashlib.sha256(extra_helper.read_bytes()).hexdigest()})
    # Native retention uses its stable composite version key, rather than a
    # fictitious rowid. No runtime statement or identifier is rewritten.
    maintenance=ast.parse((root/'agent_market/workflow_maintenance.py').read_text())
    run=next(node for node in ast.walk(maintenance) if isinstance(node,ast.FunctionDef) and node.name=='run')
    app_guard=next(node.value for node in ast.walk(run) if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='app_guard' for t in node.targets))
    guards=[ast.literal_eval(app_guard.body),ast.literal_eval(app_guard.orelse)]
    def retention_sql(node,guard):
     if isinstance(node,ast.Constant) and isinstance(node.value,str):return node.value
     if isinstance(node,ast.Name) and node.id=='app_guard':return guard
     if isinstance(node,ast.BinOp) and isinstance(node.op,ast.Add):return retention_sql(node.left,guard)+retention_sql(node.right,guard)
     raise ValueError('Unknown retention source builder.')
    for call in ast.walk(run):
     if not isinstance(call,ast.Call) or not isinstance(call.func,ast.Attribute) or call.func.attr!='execute' or not call.args:continue
     constants=[part.value for part in ast.walk(call.args[0]) if isinstance(part,ast.Constant) and isinstance(part.value,str)]
     if not any('DELETE FROM workflow_versions WHERE rowid IN' in text for text in constants):continue
     for guard in guards:
      sql=retention_sql(call.args[0],guard)
      pg=convert(sql).replace('WHERE rowid IN (SELECT v.rowid','WHERE (workflow_id,digest) IN (SELECT v.workflow_id,v.digest')
      entries.append({'name':'workflow.retention.versions','sqlite':sql,'postgres':pg,'readonly':False,'generated_id':None})
    for table in ('workflow_run_events','workflow_routing_attempts','workflow_routing_decisions','workflow_fallback_shadow','workflow_run_authority'):
     statement('workflow.retention.metadata','DELETE FROM '+table+' WHERE run_id=?')
    entries.append({'name':'workflow.retention.app_guard','sqlite':"SELECT 1 FROM sqlite_master WHERE name='workflow_apps' AND type='table'",'postgres':"SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='workflow_apps'",'readonly':True,'generated_id':None})
    rag_source=root/'agent_market/gateway/rag.py'
    rag_tree=ast.parse(rag_source.read_text())
    pending=next(node.value for node in ast.walk(rag_tree) if isinstance(node,ast.Constant) and isinstance(node.value,str) and node.value.startswith('SELECT 1 FROM vec_outbox o JOIN resources r'))
    statement('rag.pipeline.pending',pending)
    source.append({'file':'agent_market/gateway/rag.py','sha256':hashlib.sha256(rag_source.read_bytes()).hexdigest()})
    # Explicit native conflict-target qualification for two legacy upserts.
    for entry in entries:
        if entry['name'].startswith('ledger.') and 'service LIKE %s' in entry['postgres']:
            entry['postgres']=entry['postgres'].replace('service LIKE %s',
                "translate(service,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz') LIKE translate(%s,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz')")
        if 'INSERT INTO resource_observation_owners' in entry['sqlite']:
            entry['postgres']=entry['postgres'].replace('issued_sequence=issued_sequence+1','issued_sequence=resource_observation_owners.issued_sequence+1').replace('applied_sequence=issued_sequence+1','applied_sequence=resource_observation_owners.issued_sequence+1').replace('COALESCE(observed_at,0)','COALESCE(resource_observation_owners.observed_at,0)')
        if 'INSERT INTO tool_inertia' in entry['sqlite']:
            entry['postgres']=entry['postgres'].replace('count=count+1','count=tool_inertia.count+1')
        if 'INSERT INTO agent_interests' in entry['sqlite']:
            entry['postgres']=entry['postgres'].replace('MAX(COALESCE(best_score,0), COALESCE(excluded.best_score,0))',
                'GREATEST(COALESCE(agent_interests.best_score,0), COALESCE(excluded.best_score,0))').replace('COALESCE(excluded.hint, hint)',
                'COALESCE(excluded.hint, agent_interests.hint)')
        if 'INSERT INTO agent_hits' in entry['sqlite']:
            entry['postgres']=entry['postgres'].replace('hits=hits+1','hits=agent_hits.hits+1')
        if 'LIMIT -1 OFFSET ?' in entry['sqlite']:
            entry['postgres']=entry['postgres'].replace('LIMIT -1 OFFSET %s','OFFSET %s')
    from agent_market.postgres_lexical import COUNT_PREFIX, LEGACY_PREFIX, MATCH_PREFIX
    for entry in entries:
        if entry.get('adapter') in ('explore-fts5-v1','explore-fts5-page-v1','explore-fts5-count-v1'):
            prefix = re.match(r'\AWITH\s+matches\s+AS\s+\(SELECT\s+\(value->>0\)::bigint\s+AS\s+id,\(value->>1\)::double\s+precision\s+AS\s+rank\s+FROM\s+json_array_elements\(%s::json\)\)\s+', entry['postgres'])
            if prefix is None:
                raise ValueError('Unreviewed native lexical query shape: '+entry['name'])
            entry['postgres_lexical'] = (COUNT_PREFIX if entry['adapter'] == 'explore-fts5-count-v1' else MATCH_PREFIX) + entry['postgres'][prefix.end():]
    # Explicitly migrated operator domains (workspace_admin_events.SCHEMA) create their own tables on
    # demand. Startup validation and fresh-database DDL must not require them.
    from agent_market.workspace_admin_events import SCHEMA as explicit_schema
    from agent_market.agent_access.storage import SCHEMA as adoption_schema
    explicit_schema=tuple(explicit_schema)+tuple(adoption_schema)
    explicit={name for sql in explicit_schema for name in re.findall(r'CREATE TABLE IF NOT EXISTS (\w+)',sql)}
    ddl=[sql for sql in ddl if not any(sql.startswith('CREATE TABLE IF NOT EXISTS "'+name+'" ') for name in explicit)]
    native={name:sql for name,sql in native.items() if name not in explicit}
    constraints={name:value for name,value in constraints.items() if name not in explicit}
    metadata={name:value for name,value in metadata.items() if name not in explicit}
    sqlite_tables={name:value for name,value in sqlite_tables.items() if name not in explicit}
    model.update({'schema':ddl,'tables':list(native)+['resources_fts','application_store_state','vec_resources'],'statements':entries,'source_manifest':source,'scripts':script_entries,'metadata':metadata,'rowid_tables':sorted(rowid_tables),'constraints':constraints,'sqlite_tables':sqlite_tables,'runtime_profile':'explicit-service-runtime-v1'})

    db.close()
    return model


def keep_registered(model, existing):
    """Append the already-registered pairs this build does not produce; registration only ever grows.

    11-12: a --write dropped 18 registered pairs the build could not see, among them the report query
    front._trusted_report_rows builds from REPORT_COLUMNS in an f-string; Explore cards would have failed on
    PostgreSQL (unsupported_application_sql). Removing a registration is a separate, reviewed change.
    Kept entries are renamed by their text, like generated ones."""
    produced = {(item['sqlite'], item['postgres']) for item in model['statements']}
    kept = []
    for item in (existing or {}).get('statements', []):
        if (item['sqlite'], item['postgres']) in produced:
            continue
        produced.add((item['sqlite'], item['postgres']))
        prefix = re.sub(r'(\.source|\.schema|\.registered)?(\.[0-9a-f]{12}|\.\d+)(\.limit\d+)?$', '', item['name'])
        kept.append({**item, 'name': stable_name(prefix + '.registered', item['sqlite'])})
    model['statements'] = model['statements'] + kept
    return model


def encoded(model):
    # Keep each dialect pair and each table's metadata on one reviewable line.
    lines = ['{']
    for index, (key, value) in enumerate(model.items()):
        suffix = ',' if index < len(model)-1 else ''
        if isinstance(value, list):
            lines.append('  '+json.dumps(key)+': [')
            lines.extend('    '+json.dumps(item, ensure_ascii=True, sort_keys=True)+(',' if i < len(value)-1 else '') for i,item in enumerate(value))
            lines.append('  ]'+suffix)
        elif isinstance(value, dict):
            lines.append('  '+json.dumps(key)+': {')
            lines.extend('    '+json.dumps(name)+': '+json.dumps(item,ensure_ascii=True,sort_keys=True)+(',' if i < len(value)-1 else '') for i,(name,item) in enumerate(value.items()))
            lines.append('  }'+suffix)
        else: lines.append('  '+json.dumps(key)+': '+json.dumps(value,ensure_ascii=True)+suffix)
    lines.append('}')
    return '\n'.join(lines)+'\n'


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check',action='store_true')
    mode.add_argument('--write',action='store_true')
    args=parser.parse_args(argv)
    # Schema-only fixtures must never bootstrap a real account or read the
    # deployment's bootstrap-password configuration. This isolated build CLI
    # temporarily substitutes only the local fixture initializer.
    from agent_market.gateway import store as store_module
    from agent_market.gateway.admin_auth import ADMIN_SCHEMA
    original=store_module.init_admin_auth_db
    store_module.init_admin_auth_db=lambda db: db.executescript(ADMIN_SCHEMA)
    try: model=build_catalog()
    finally: store_module.init_admin_auth_db=original
    target=Path(__file__).resolve().parents[1]/'agent_market/application_store_sql.json'
    keep_registered(model, json.loads(target.read_text()) if target.exists() else None)
    data=encoded(model)
    changed=target.read_text()!=data if target.exists() else True
    if args.write: target.write_text(data)
    print(json.dumps({'profile':model['profile'],'changed':changed,'written':args.write,
        'tables':len(model['tables']),'statements':len(model['statements'])},sort_keys=True))
    return 1 if args.check and changed else 0


if __name__=='__main__':raise SystemExit(main())
