"""Page-bounded current execution evidence under one local read snapshot."""
from contextlib import contextmanager

from ..capability_registry import digest,version_parts
from ..concierge.discovery_state import execution_state


@contextmanager
def snapshot(store):
    if getattr(store,'backend',None)=='postgresql':
        with store.tx(readonly=True):yield
    else:
        with store._lock:yield


def current_states(store,ids):
    if len(ids)>100 or any(type(r)is not int or r<=0 for r in ids):raise ValueError('INVALID_INPUT')
    ids=list(dict.fromkeys(ids));resources={};evidence={}
    with snapshot(store):
        if getattr(store,'backend',None)=='postgresql':
            from ..application_store_resource_batches import resources as native_resources
            resources={r['id']:dict(r)for r in native_resources(store,ids,'active IN (0,1)',())}
        else:
            for offset in range(0,len(ids),16):
                values=ids[offset:offset+16];values+=([values[-1]]*(16-len(values)))
                rows=store.query('SELECT * FROM resources WHERE id IN (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',values)
                resources.update({r['id']:dict(r)for r in rows})
        versions=[]
        for r in resources.values():
            binding,schema,profile,_=version_parts(r)
            versions.append('cv_'+digest([r['id'],binding,schema,profile])[:32])
        for offset in range(0,len(versions),16):
            values=versions[offset:offset+16];values+=([values[-1]]*(16-len(values)))
            rows=store.query('''SELECT * FROM (SELECT e.*,ROW_NUMBER() OVER
                (PARTITION BY version_id ORDER BY finished DESC,recorded DESC,id DESC) AS adoption_rn
                FROM capability_evidence e WHERE version_id IN (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) AND scope='execution') batch
                WHERE adoption_rn<=2''',values)
            for row in rows:evidence.setdefault(row['version_id'],[]).append(row)
        controls=store.query('SELECT * FROM execution_controls WHERE id=1')
        class View:
            def query(self,sql,parameters=()):
                if sql=='SELECT * FROM execution_controls WHERE id=1':return controls
                if sql.startswith('SELECT * FROM capability_evidence')and len(parameters)==1:
                    return evidence.get(parameters[0],[])[:1]
                raise ValueError('UNREVIEWED_PROJECTION_QUERY')
        view=View()
        states={rid:execution_state(view,resource)for rid,resource in resources.items()}
    return resources,states
