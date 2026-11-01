"""Small per-runtime pool of dedicated native read sessions for administrator GETs."""
from contextlib import contextmanager
import threading
import time


class AdminReaderPool:
    def __init__(self, factory, maximum=3, wait_seconds=5, max_idle=None):
        self.factory,self.maximum=factory,maximum
        self.wait_seconds=wait_seconds
        self.max_idle=maximum if max_idle is None else max_idle
        if type(self.max_idle) is not int or not 0<=self.max_idle<=maximum:
            raise ValueError("Invalid idle pool capacity")
        self.condition=threading.Condition()
        self.idle=[]
        self.total=self.leased=self.waiting=0
        self.closed=False

    @contextmanager
    def lease_store(self):
        """Lease an explicitly configured session; the caller owns transaction scope."""
        deadline=time.monotonic()+self.wait_seconds
        with self.condition:
            self.waiting+=1
            try:
                while not self.idle and self.total>=self.maximum and not self.closed:
                    remaining=deadline-time.monotonic()
                    if remaining<=0:raise TimeoutError('admin_read_pool_busy')
                    self.condition.wait(remaining)
            finally:
                self.waiting-=1
            if self.closed:raise RuntimeError('admin_read_pool_closed')
            resource=self.idle.pop() if self.idle else None
            if resource is None:self.total+=1
            self.leased+=1
        discard=False
        try:
            if resource is None:resource=self.factory()
            yield resource[0]
        finally:
            if resource is not None:
                # A store that reconnected owns a new session; track it instead of the closed one.
                current=getattr(resource[0],'_connection',resource[1])
                if current is not resource[1]:resource=(resource[0],current)
                discard=bool(getattr(resource[0],'_broken',False) or resource[1].closed)
                if discard:
                    resource[0].close();resource[1].close()
            close_idle=False
            with self.condition:
                self.leased-=1
                close_idle=resource is not None and not discard and len(self.idle)>=max(self.max_idle,self.waiting)
                if resource is None or discard or close_idle:self.total-=1
                else:self.idle.append(resource)
                self.condition.notify_all()
            if close_idle:
                try:resource[0].close()
                finally:resource[1].close()

    @contextmanager
    def reader(self):
        with self.lease_store() as store:
            with store.tx(readonly=True) as db:
                yield db

    def close(self):
        with self.condition:
            if self.leased:raise RuntimeError('admin_readers_not_drained')
            if self.closed:return
            self.closed=True
            resources,self.idle=self.idle,[]
            self.total=0
            self.condition.notify_all()
        for store,connection in resources:
            store.close();connection.close()
