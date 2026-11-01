"""Bounded immutable-contract cache and cancellation-safe synchronous single flight."""
from collections import OrderedDict
from concurrent.futures import Future, TimeoutError
import threading
import time


class BoundedCache:
    def __init__(self, entries=128, ttl=60, max_waiters=32):
        self.entries,self.ttl,self.max_waiters=entries,ttl,max_waiters
        self.lock=threading.Lock();self.values=OrderedDict();self.pending={}

    def get(self,key,build):
        with self.lock:
            found=self.values.pop(key,None)
            if found and found[0]>time.monotonic():
                self.values[key]=found;return found[1]
            state=self.pending.get(key)
            if state:
                if state[1]>=self.max_waiters:raise ValueError('SERVICE_BUSY')
                state[1]+=1;future=state[0];leader=False
            else:
                if len(self.pending)>=self.entries:raise ValueError('SERVICE_BUSY')
                future=Future();self.pending[key]=[future,1];leader=True
        if not leader:
            try:return future.result(timeout=5)
            except TimeoutError:raise ValueError('SERVICE_BUSY') from None
            finally:
                with self.lock:
                    if key in self.pending:self.pending[key][1]-=1
        try:
            value=build()
            with self.lock:
                self.values[key]=(time.monotonic()+self.ttl,value)
                while len(self.values)>self.entries:self.values.popitem(last=False)
            future.set_result(value);return value
        except BaseException as error:
            future.set_exception(error);raise
        finally:
            with self.lock:self.pending.pop(key,None)
