"""Signed per-run budgets; extended execution is an explicit private admin choice."""
import json
import hmac

SCHEMA='''CREATE TABLE IF NOT EXISTS workflow_execution_budgets (
 run_id TEXT PRIMARY KEY,payload TEXT NOT NULL,signature TEXT NOT NULL);'''
NOTICE='workflow-budget-v1'


class Budgets:
    def __init__(self,runtime):
        self.runtime,self.store=runtime,runtime.store
        with self.store._lock:self.store._db.executescript(SCHEMA)

    def admit(self,db,run_id,digest,source,claims,profile,notice):
        if type(profile) is not str or profile not in ('standard','extended'):
            raise ValueError('Choose a supported execution profile.')
        if profile=='extended' and (source!='admin' or claims['kind']!='admin' or claims['role']!='superadmin' or notice!=NOTICE):
            raise ValueError('Extended execution requires explicit superadmin authorization.')
        payload={'audience':NOTICE,'run_id':run_id,'digest':digest,'source':source,'profile':profile,
                 'total_seconds':60 if profile=='extended' else 25,'node_seconds':15 if profile=='extended' else 25}
        db.execute('INSERT INTO workflow_execution_budgets VALUES (?,?,?)',(run_id,json.dumps(payload),self.runtime.authority.signature(payload)))

    def get(self,row):
        rows=self.store.query('SELECT * FROM workflow_execution_budgets WHERE run_id=?',(row['id'],))
        if not rows:return {'profile':'standard','total_seconds':25,'node_seconds':25}
        p=json.loads(rows[0]['payload'])
        if (not hmac.compare_digest(rows[0]['signature'],self.runtime.authority.signature(p))
                or any(p.get(k)!=v for k,v in {'audience':NOTICE,'run_id':row['id'],'digest':row['digest'],'source':row['source']}.items())
                or (p.get('total_seconds'),p.get('node_seconds'))!=((60,15) if p.get('profile')=='extended' and row['source']=='admin' else (25,25))):
            raise ValueError('Execution budget authorization is invalid.')
        return p
