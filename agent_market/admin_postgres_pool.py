"""Small per-runtime pool of dedicated native read sessions for administrator GETs."""
from contextlib import contextmanager
import threading
import time


class AdminReaderPool:
    def __init__(self, factory, maximum=3, wait_seconds=5, max_idle=None, idle_seconds=None):
        self.factory,self.maximum=factory,maximum
        self.wait_seconds=wait_seconds
        # Idle sessions older than this are closed, so a retained standby slot gives its
        # connections back to the shared database budget (11-01: 7 of 21 slots held idle).
        if idle_seconds is not None and (type(idle_seconds) not in (int,float) or idle_seconds<=0):
            raise ValueError("Invalid idle session lifetime")
        self.idle_seconds=idle_seconds
        self.released=[]
        self.reaper=None
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
        began=time.perf_counter()
        with self.condition:
            self.waiting+=1
            try:
                while not self.idle and self.total>=self.maximum and not self.closed:
                    remaining=deadline-time.monotonic()
                    if remaining<=0:raise TimeoutError('admin_read_pool_busy')
                    self.condition.wait(remaining)
            finally:
                self.waiting-=1
                # The time a request waited for a pooled session (Server-Timing pool_wait, 11-11).
                from .concierge.retrieval_metrics import add
                add('pool_wait',(time.perf_counter()-began)*1000)
            if self.closed:raise RuntimeError('admin_read_pool_closed')
            resource=self.idle.pop() if self.idle else None
            if resource is not None:self.released.pop()
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
                else:
                    self.idle.append(resource);self.released.append(time.monotonic())
                    self._start_reaper()
                self.condition.notify_all()
            if close_idle:
                try:resource[0].close()
                finally:resource[1].close()

    def free_sessions(self):
        """Sessions a lease could take right now without waiting (idle ones plus room to open). A hint only:
        another thread may take one first, and lease_store then waits as usual."""
        with self.condition:
            return 0 if self.closed else len(self.idle) + max(0, self.maximum - self.total)

    def _start_reaper(self):
        # Caller holds the condition.
        if self.idle_seconds is None or self.reaper is not None or self.closed:return
        self.reaper=threading.Thread(target=self._reap,name='db-idle-reaper',daemon=True)
        self.reaper.start()

    def close_expired(self):
        """Close idle sessions unused for idle_seconds; returns how many were closed."""
        if self.idle_seconds is None:return 0
        cutoff=time.monotonic()-self.idle_seconds
        with self.condition:
            # Oldest sessions sit at the front; leases take from the back.
            count=0
            while count<len(self.released) and self.released[count]<=cutoff:count+=1
            expired,self.idle=self.idle[:count],self.idle[count:]
            self.released=self.released[count:]
            self.total-=count
            if count:self.condition.notify_all()
        for store,connection in expired:
            try:store.close()
            finally:connection.close()
        return count

    def _reap(self):
        interval=min(30.0,self.idle_seconds/2)
        while True:
            with self.condition:
                if self.closed:
                    self.reaper=None;return
                self.condition.wait(interval)
                if self.closed:
                    self.reaper=None;return
            try:self.close_expired()
            except Exception:pass

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
            self.released=[]
            self.total=0
            self.condition.notify_all()
        for store,connection in resources:
            store.close();connection.close()
