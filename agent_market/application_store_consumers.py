"""Named native current administrator consumer projections.

Identifiers/predicates are fixed source allowlists. Caller values remain bound;
no generic legacy SQL translation or arbitrary query adapter is provided.
"""
import json
import time

_BASE = "WITH base AS (\n          SELECT v.id,v.name,v.channel,v.user_agent,v.first_seen,v.last_seen,v.visits,v.visit_days,v.messages,v.tier,\n            (SELECT task FROM agent_interests i WHERE i.visitor_id=v.id ORDER BY updated DESC LIMIT 1) AS last_task,\n            (SELECT kind FROM agent_interests i WHERE i.visitor_id=v.id ORDER BY updated DESC LIMIT 1) AS requested_protocol,\n            (SELECT COUNT(*) FROM agent_task_watches w WHERE w.visitor_id=v.id AND w.state='active' AND w.expires>%s) AS active_watches,\n            (SELECT COUNT(*) FROM agent_task_watches w WHERE w.visitor_id=v.id AND w.channel!='poll' AND w.sealed IS NOT NULL) AS inbox_contacts,\n            (SELECT COUNT(*) FROM agent_contacts c WHERE c.visitor_id=v.id AND c.url!='') AS legacy_contacts,\n            (SELECT COUNT(*) FROM agent_task_watches w WHERE w.visitor_id=v.id AND w.channel!='poll' AND w.state='active' AND w.expires>%s AND w.verified_at IS NOT NULL AND w.sealed IS NOT NULL AND w.authority=1 AND w.notice_version=%s) AS authorized_inboxes,\n            (SELECT COUNT(*) FROM agent_task_watches w WHERE w.visitor_id=v.id AND w.state='pending_verification' AND w.code_expires>%s) AS pending_contacts,\n            (SELECT COUNT(*) FROM agent_task_events e JOIN agent_task_watches w ON w.id=e.watch_id WHERE w.visitor_id=v.id AND e.status='sent') AS digests,\n            (SELECT COUNT(*) FROM agent_marketing_permissions m WHERE m.visitor_id=v.id AND m.withdrawn_at IS NULL) AS marketing_opt_ins,\n            (SELECT COUNT(*) FROM agent_marketing_permissions m JOIN agent_task_watches w ON w.id=m.watch_id WHERE m.visitor_id=v.id AND m.withdrawn_at IS NULL AND m.verified_at IS NOT NULL AND m.notice_version=%s AND m.expires>%s AND w.state='active' AND w.expires>%s AND w.verified_at IS NOT NULL AND w.sealed IS NOT NULL AND w.authority=1 AND w.notice_version=%s) AS marketing_eligible_contacts,\n            COALESCE(c.status,'new') AS case_status,COALESCE(c.owner,'') AS owner,c.next_followup,c.updated AS case_updated\n          FROM agent_visitors v LEFT JOIN agent_visitor_cases c ON c.visitor_id=v.id\n        ) "


def _like(field):
    return "translate("+field+",'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz') LIKE translate(%s,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz') ESCAPE '\\'"


class PostgresConsumerMixin:
    def public_catalog_metrics(self, start, end):
        from .application_store_public_metrics import catalog
        return catalog(self, start, end)

    def public_execution_metrics(self, start, end):
        from .application_store_public_metrics import execution
        return execution(self, start, end)

    def visitor_desk_list(self, q='', contact='all', protocol='', case_state='', offset=0, limit=100, tier='', source='all'):
        from .application_store_postgres import ApplicationStoreError
        from .concierge.task_updates import NOTICE_VERSION, MARKETING_NOTICE
        if (type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=1000
                or any(type(v) is not str or '\0' in v or len(v.encode())>4096 for v in (q,contact,protocol,case_state,tier,source))):
            raise ApplicationStoreError('invalid_parameters')
        now=time.time();conditions=[];values=[]
        if q:
            pattern='%'+q.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
            conditions.append('('+_like('name')+' OR '+_like('id')+' OR '+_like('last_task')+')');values.extend([pattern]*3)
        filters={'registered':'inbox_contacts+legacy_contacts>0','authorized':'authorized_inboxes>0',
            'marketing':'marketing_eligible_contacts>0','pending':'pending_contacts>0','legacy':'legacy_contacts>0','none':'inbox_contacts+legacy_contacts=0'}
        if contact in filters:conditions.append(filters[contact])
        if protocol:conditions.append("COALESCE(requested_protocol,'any')=%s");values.append(protocol)
        if case_state:conditions.append('case_status=%s');values.append(case_state)
        if tier:conditions.append('tier=%s');values.append(tier)
        if source=='live':conditions.append("COALESCE(channel,'')!='admin-test'")
        elif source=='simulation':conditions.append("channel='admin-test'")
        where=' WHERE '+' AND '.join(conditions) if conditions else ''
        # Exact source CTE placeholders only; this source-owned native constant
        # does not accept or rewrite SQL from a caller.
        base=_BASE
        base_params=[now,now,NOTICE_VERSION,now,MARKETING_NOTICE,now,now,NOTICE_VERSION]
        with self.tx(readonly=True):
            rows=[dict(row) for row in self._execute(base+'SELECT * FROM base'+where+' ORDER BY last_seen DESC,id LIMIT %s OFFSET %s',base_params+values+[limit,offset]).fetchall()]
            summary=dict(self._execute(base+"""SELECT COUNT(*) AS total,
                COALESCE(SUM((inbox_contacts+legacy_contacts>0)::integer),0) AS registered,
                COALESCE(SUM((authorized_inboxes>0)::integer),0) AS authorized,
                COALESCE(SUM((pending_contacts>0)::integer),0) AS pending,
                COALESCE(SUM((marketing_eligible_contacts>0)::integer),0) AS marketing_eligible,
                COALESCE(SUM((case_status IN ('new','reviewing'))::integer),0) AS needs_review,
                COALESCE(SUM((case_status NOT IN ('resolved','archived') AND next_followup IS NOT NULL AND next_followup<=%s)::integer),0) AS followup_due
                FROM base"""+where,base_params+[now]+values).fetchone())
        return {'items':rows,'filtered_stats':summary,'pagination':{'total':summary['total'],'offset':offset,'limit':limit,'has_more':offset+len(rows)<summary['total']}}

    def agent_telemetry_raw(self, since: float, now: float, source: str = 'live') -> dict:
        if source == 'live':
            src_cond = "COALESCE(v.channel, '') != 'admin-test'"
        elif source == 'simulation':
            src_cond = "v.channel = 'admin-test'"
        else:
            src_cond = "1=1"
        with self.tx(readonly=True):
            hit_summary = dict(self._execute(
                """SELECT COUNT(*) AS readers,
                          COALESCE(SUM(hits), 0) AS total_reads,
                          COALESCE(SUM(CASE WHEN last_seen >= %s THEN 1 ELSE 0 END), 0) AS readers_period,
                          COALESCE(SUM(CASE WHEN last_seen >= %s THEN hits ELSE 0 END), 0) AS reads_period
                   FROM agent_hits""",
                (since, since),
            ).fetchone() or {})
            entry_paths = [dict(r) for r in self._execute(
                """SELECT COALESCE(NULLIF(last_path, ''), '/') AS path,
                          COUNT(*) AS unique_agents,
                          COALESCE(SUM(hits), 0) AS total_hits,
                          MAX(last_seen) AS last_seen
                   FROM agent_hits
                   WHERE last_seen >= %s
                   GROUP BY COALESCE(NULLIF(last_path, ''), '/')
                   ORDER BY total_hits DESC, unique_agents DESC
                   LIMIT 12""",
                (since,),
            ).fetchall()]
            hit_uas = [dict(r) for r in self._execute(
                "SELECT user_agent, hits FROM agent_hits WHERE last_seen >= %s ORDER BY last_seen DESC LIMIT 500",
                (since,),
            ).fetchall()]
            v_stats = dict(self._execute(
                f"""SELECT COUNT(*) AS total_visitors,
                           COALESCE(SUM(CASE WHEN first_seen >= %s THEN 1 ELSE 0 END), 0) AS new_visitors,
                           COALESCE(SUM(CASE WHEN last_seen >= %s THEN 1 ELSE 0 END), 0) AS active_24h,
                           COALESCE(SUM(CASE WHEN visits >= 2 THEN 1 ELSE 0 END), 0) AS returning_visitors,
                           COALESCE(SUM(CASE WHEN visit_days >= 2 THEN 1 ELSE 0 END), 0) AS multi_day_visitors,
                           COALESCE(SUM(CASE WHEN visits = 1 AND messages <= 1 THEN 1 ELSE 0 END), 0) AS single_turn_bounce,
                           COALESCE(SUM(CASE WHEN tier='regular' THEN 1 ELSE 0 END), 0) AS tier_regular,
                           COALESCE(SUM(CASE WHEN tier='returning' THEN 1 ELSE 0 END), 0) AS tier_returning,
                           COALESCE(SUM(CASE WHEN tier='new' THEN 1 ELSE 0 END), 0) AS tier_new,
                           COALESCE(SUM(messages), 0) AS total_messages
                    FROM agent_visitors v
                    WHERE v.last_seen >= %s AND {src_cond}""",
                (since, now - 86400, since),
            ).fetchone() or {})
            channel_rows = [dict(r) for r in self._execute(
                f"""SELECT COALESCE(NULLIF(v.channel, ''), 'unknown') AS channel,
                           COUNT(*) AS visitors,
                           COALESCE(SUM(v.visits), 0) AS visits,
                           COALESCE(SUM(v.messages), 0) AS messages,
                           COALESCE(SUM(CASE WHEN v.visits >= 2 THEN 1 ELSE 0 END), 0) AS returning_count
                    FROM agent_visitors v
                    WHERE v.last_seen >= %s AND {src_cond}
                    GROUP BY COALESCE(NULLIF(v.channel, ''), 'unknown')
                    ORDER BY visitors DESC""",
                (since,),
            ).fetchall()]
            visitor_uas = [dict(r) for r in self._execute(
                f"SELECT v.user_agent, v.visits FROM agent_visitors v WHERE v.last_seen >= %s AND {src_cond} LIMIT 500",
                (since,),
            ).fetchall()]
            msg_rows = [dict(r) for r in self._execute(
                f"""SELECT m.id, m.visitor_id, m.at, m.role, m.channel, m.text, m.data
                    FROM agent_messages m
                    JOIN agent_visitors v ON v.id = m.visitor_id
                    WHERE m.at >= %s AND {src_cond}
                    ORDER BY m.id DESC
                    LIMIT 1500""",
                (since,),
            ).fetchall()]
            interest_rows = [dict(r) for r in self._execute(
                f"""SELECT i.visitor_id, i.task, i.category, COALESCE(i.kind, 'any') AS protocol,
                           i.recommended, i.best_score, i.updated
                    FROM agent_interests i
                    JOIN agent_visitors v ON v.id = i.visitor_id
                    WHERE i.updated >= %s AND {src_cond}
                    ORDER BY i.updated DESC
                    LIMIT 500""",
                (since,),
            ).fetchall()]
            outcome_rows = [dict(r) for r in self._execute(
                f"""SELECT o.visitor_id, o.resource_id, o.success, o.at,
                           r.name, r.kind, r.category, r.eval_grade AS grade, r.health_status
                    FROM agent_outcomes o
                    LEFT JOIN agent_visitors v ON v.id = o.visitor_id
                    LEFT JOIN resources r ON r.id = o.resource_id
                    WHERE o.at >= %s AND (SUBSTR(o.visitor_id, 1, 11) = '__admin_cb_' OR {src_cond})
                    ORDER BY o.at DESC""",
                (since,),
            ).fetchall()]
            inertia_rows = [dict(r) for r in self._execute(
                """SELECT ti.from_resource_id, ti.from_tool, ti.to_resource_id, ti.to_tool,
                          ti.count, ti.last_transition,
                          r1.name AS from_name, r1.kind AS from_kind, r1.category AS from_category,
                          r2.name AS to_name, r2.kind AS to_kind, r2.category AS to_category
                   FROM tool_inertia ti
                   LEFT JOIN resources r1 ON r1.id = ti.from_resource_id
                   LEFT JOIN resources r2 ON r2.id = ti.to_resource_id
                   ORDER BY ti.count DESC, ti.last_transition DESC
                   LIMIT 15"""
            ).fetchall()]
            watch_visitors = [
                r["visitor_id"]
                for r in self._execute(
                    f"""SELECT DISTINCT w.visitor_id
                        FROM agent_task_watches w
                        JOIN agent_visitors v ON v.id = w.visitor_id
                        WHERE w.state IN ('active', 'pending_verification') AND {src_cond}"""
                ).fetchall()
            ]
            returning_visitor_ids = [
                r["id"]
                for r in self._execute(
                    f"SELECT v.id FROM agent_visitors v WHERE v.last_seen >= %s AND v.visits >= 2 AND {src_cond}",
                    (since,),
                ).fetchall()
            ]
            supply_by_kind = {
                r["kind"]: dict(r)
                for r in self._execute(
                    """SELECT kind,
                              COUNT(*) AS active_total,
                              COALESCE(SUM(CASE WHEN health_status IN ('healthy', 'reachable') THEN 1 ELSE 0 END), 0) AS healthy_total,
                              COALESCE(SUM(CASE WHEN COALESCE(trial_ok, 0) = 1 THEN 1 ELSE 0 END), 0) AS verified_total,
                              COALESCE(SUM(CASE WHEN eval_grade = 'A' THEN 1 ELSE 0 END), 0) AS grade_a_total
                       FROM resources
                       WHERE active = 1 AND COALESCE(eval_security, '') != 'quarantine'
                       GROUP BY kind"""
                ).fetchall()
            }
            workflow_count = int((self._execute(
                "SELECT COUNT(*) AS n FROM agent_workflows WHERE is_active = 1"
            ).fetchone() or {"n": 0})["n"] or 0)
            recent_visitors = [dict(r) for r in self._execute(
                f"""SELECT v.id, v.name, v.channel, v.user_agent, v.first_seen, v.last_seen,
                           v.visits, v.visit_days, v.messages, v.tier,
                           (SELECT i.task FROM agent_interests i WHERE i.visitor_id = v.id ORDER BY i.updated DESC LIMIT 1) AS last_task,
                           (SELECT i.kind FROM agent_interests i WHERE i.visitor_id = v.id ORDER BY i.updated DESC LIMIT 1) AS requested_protocol,
                           (SELECT COUNT(*) FROM agent_task_watches w WHERE w.visitor_id = v.id AND w.state = 'active' AND w.expires > %s) AS active_watches,
                           (SELECT COUNT(*) FROM agent_outcomes o WHERE o.visitor_id = v.id AND o.success = 1) AS outcomes_ok,
                           (SELECT COUNT(*) FROM agent_outcomes o WHERE o.visitor_id = v.id AND o.success = 0) AS outcomes_fail
                    FROM agent_visitors v
                    WHERE v.last_seen >= %s AND {src_cond}
                    ORDER BY v.last_seen DESC
                    LIMIT 25""",
                (now, since),
            ).fetchall()]
        return {
            "hit_summary": hit_summary,
            "entry_paths": entry_paths,
            "hit_uas": hit_uas,
            "v_stats": v_stats,
            "channel_rows": channel_rows,
            "visitor_uas": visitor_uas,
            "msg_rows": msg_rows,
            "interest_rows": interest_rows,
            "outcome_rows": outcome_rows,
            "inertia_rows": inertia_rows,
            "watch_visitors": set(watch_visitors),
            "returning_visitor_ids": set(returning_visitor_ids),
            "supply_by_kind": supply_by_kind,
            "workflow_count": workflow_count,
            "recent_visitors": recent_visitors,
        }

    def global_failing_resources(self, min_fails: int = 3) -> set[int]:
        from .concierge.recommendation_circuit import controls_for
        if type(min_fails) is not int or not 1 <= min_fails <= 1000:
            min_fails = 3
        with self.tx(readonly=True):
            controls = controls_for(self)
            rows = self._execute(
                """SELECT o.resource_id FROM agent_outcomes o
                   LEFT JOIN meta m ON m.key='recommendation_circuit_controls_v1'
                   WHERE o.at > COALESCE((m.value::jsonb -> o.resource_id::text ->> 'reset_at')::double precision, 0)
                   GROUP BY o.resource_id
                   HAVING SUM(CASE WHEN o.visitor_id IN ('__admin_cb_1__','__admin_cb_2__','__admin_cb_3__') THEN 1 ELSE 0 END) > 0
                      OR (SUM(CASE WHEN o.success=0 THEN 1 ELSE 0 END) >= %s
                      AND SUM(CASE WHEN o.success=0 THEN 1 ELSE 0 END) > SUM(CASE WHEN o.success=1 THEN 1 ELSE 0 END) * 2)
                   LIMIT 500""",
                (min_fails,),
            ).fetchall()
            direct = {int(r['resource_id']) for r in rows if r['resource_id'] is not None}
            direct.update(int(key) for key, row in controls.items() if row['state'] == 'open')
            if not direct:
                return set()
            named = self._execute(
                "SELECT id,kind,name FROM resources WHERE id IN (SELECT value::bigint FROM jsonb_array_elements_text(%s::jsonb))",
                (json.dumps(sorted(direct)),),
            ).fetchall()
            ascii_ids = [row['id'] for row in named if str(row['name'] or '').isascii()]
            other_ids = [row['id'] for row in named if not str(row['name'] or '').isascii()]
            duplicates = []
            if ascii_ids:
                # resources_admin_name instead of scanning every active listing
                # (about 0.15s per Chat request); LOWER() keeps the original match.
                duplicates += self._execute(
                    """SELECT r2.id AS resource_id FROM resources r1
                       JOIN resources r2 ON r2.active=1
                        AND translate(r2.name,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz') COLLATE "C"
                           =translate(r1.name,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz') COLLATE "C"
                        AND r2.kind=r1.kind AND LOWER(r2.name)=LOWER(r1.name)
                       WHERE r1.id IN (SELECT value::bigint FROM jsonb_array_elements_text(%s::jsonb))""",
                    (json.dumps(ascii_ids),),
                ).fetchall()
            if other_ids:
                duplicates += self._execute(
                    """SELECT r2.id AS resource_id FROM resources r1
                       JOIN resources r2 ON r2.kind=r1.kind AND LOWER(r2.name)=LOWER(r1.name)
                       WHERE r1.id IN (SELECT value::bigint FROM jsonb_array_elements_text(%s::jsonb))
                         AND r2.active=1""", (json.dumps(other_ids),),
                ).fetchall()
        return direct | {int(row['resource_id']) for row in duplicates}

    def remediate_agent_telemetry(self, action: str, *, resource_id: int | None = None, task_norm: str | None = None,
                                  recommended_json: str | None = None, best_score: float | None = None, now: float = 0.0,
                                  protocol: str = 'any') -> dict:
        with self.tx():
            if action in ('trip_circuit', 'reset_circuit') and type(resource_id) is int and resource_id > 0:
                from .concierge.recommendation_circuit import CONTROL_KEY, changed_controls
                # Lock a dedicated metadata row so concurrent staff actions retain each other's controls.
                self._execute("INSERT INTO meta(key,value) VALUES (%s,'{}') ON CONFLICT(key) DO NOTHING", (CONTROL_KEY,))
                row = self._execute('SELECT value FROM meta WHERE key=%s FOR UPDATE', (CONTROL_KEY,)).fetchone()
                controls = changed_controls(json.loads(row['value']), resource_id, action, now)
                self._execute('UPDATE meta SET value=%s WHERE key=%s', (json.dumps(controls), CONTROL_KEY))
                return {'ok': True, 'action': action, 'resource_id': resource_id,
                        'circuit_open': resource_id in self.global_failing_resources(),
                        'manual_open': action == 'trip_circuit', 'cleared': 0, 'history_preserved': True}
            if action == "resolve_unmet" and isinstance(task_norm, str) and task_norm:
                if recommended_json and best_score is not None:
                    cur = self._execute(
                        """UPDATE agent_interests
                           SET recommended = %s, best_score = GREATEST(COALESCE(best_score, 0), %s), last_checked = %s
                           WHERE task_norm = %s AND COALESCE(kind,'any') = %s
                             AND (recommended = '[]' OR best_score IS NULL)""",
                        (recommended_json, best_score, now, task_norm, protocol),
                    )
                else:
                    return {'ok': False, 'error': 'no_verified_match_available'}
                return {"ok": True, "action": action, "task_norm": task_norm, "updated": int(cur.rowcount or 0),
                        'status': 'catalog_match_found', 'execution_verified': False}
        return {"ok": False, "error": "unsupported_remediation_action"}
