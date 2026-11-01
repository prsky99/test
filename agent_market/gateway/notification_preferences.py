"""Read-only Customer Requests view of purpose-scoped notification settings."""
class NotificationPreferences:
    def __init__(self, store, updates=None):
        self.store, self.updates = store, updates

    def _public(self, row):
        if self.updates:
            item = self.updates.admin_summary(dict(row))
        else:
            item = {key:row[key] for key in ('id','task','protocol','channel','state','created','expires','last_checked')}
            item.update(destination='Unavailable', destination_verified=False,
                        marketing_status='unavailable', marketing_eligible=False, permission_current=False)
        # Explicit projection: sealed destinations and private session identifiers stay private.
        keys = ('id','task','protocol','channel','state','created','expires','last_checked',
                'destination','destination_verified','verified_at','destination_confirmed_at',
                'marketing_status','marketing_eligible','marketing_requested_at','marketing_verified_at',
                'marketing_withdrawn_at','marketing_expires','permission_current','notice_version')
        return {key:item.get(key) for key in keys}

    def list(self, q='', state='all', channel='all', limit=50, offset=0):
        if self.updates:
            self.updates.maintain()
        conditions, params = [], []
        if q:
            pattern = '%'+q.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
            conditions.append("(w.id LIKE ? ESCAPE '\\' OR w.task LIKE ? ESCAPE '\\')")
            params.extend([pattern,pattern])
        if state != 'all':
            conditions.append('w.state=?'); params.append(state)
        if channel != 'all':
            conditions.append('w.channel=?'); params.append(channel)
        where = ' WHERE '+' AND '.join(conditions) if conditions else ''
        # Keep count and page consistent while another request changes preferences.
        with self.store.tx() as db:
            summary = dict(db.execute("""SELECT COUNT(*) AS total,
                COALESCE(SUM(w.state='active'),0) AS active,
                COALESCE(SUM(w.state='paused'),0) AS paused,
                COALESCE(SUM(w.state='pending_verification'),0) AS pending,
                COALESCE(SUM(w.state IN ('revoked','expired','failed')),0) AS stopped
                FROM agent_task_watches w"""+where,params).fetchone())
            rows = db.execute("""SELECT w.*,
                (SELECT MAX(p.at) FROM agent_task_permissions p WHERE p.watch_id=w.id) AS latest_action
                FROM agent_task_watches w"""+where+
                ' ORDER BY MAX(w.created,COALESCE(latest_action,0)) DESC,w.id LIMIT ? OFFSET ?',
                (*params,limit,offset)).fetchall()
            items = [self._public(row) for row in rows]
        return {'items':items, 'summary':summary,
                'pagination':{'total':summary['total'],'offset':offset,'limit':limit,
                              'has_more':offset+len(items)<summary['total']}}

    def detail(self, watch_id):
        if self.updates:
            self.updates.maintain()
        with self.store.tx() as db:
            row = db.execute('SELECT * FROM agent_task_watches WHERE id=?',(watch_id,)).fetchone()
            if not row:
                raise LookupError('Notification preference not found or removed.')
            item = self._public(row)
            history = [dict(r) for r in db.execute('''SELECT id,action,purpose,notice_version,at
                FROM agent_task_permissions WHERE watch_id=? ORDER BY at DESC,id DESC LIMIT 100''',(watch_id,))]
            total = db.execute('SELECT COUNT(*) FROM agent_task_permissions WHERE watch_id=?',(watch_id,)).fetchone()[0]
            deliveries = [dict(r) for r in db.execute('''SELECT id,created,status,attempts
                FROM agent_task_events WHERE watch_id=? ORDER BY created DESC,id LIMIT 20''',(watch_id,))]
        return {'item':item,'history':history,'history_total':total,'deliveries':deliveries,
                'policy':{'read_only':True,'advertising_enabled':False,'customer_permission_required':True}}
