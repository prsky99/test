"""Real Lua admission/replay semantics through a disposable Unix-only Redis."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

import redis


def test_atomic_redis_remainders_and_nonce_replay(monkeypatch):
    from agent_market.infra.redis_hub import RedisHub,SLIDING_WINDOW_LUA
    from agent_market.concierge.web_bot_auth import reserve_nonce
    with tempfile.TemporaryDirectory(prefix='ac-redis-',dir='/tmp') as directory:
        socket=str(Path(directory)/'redis.sock')
        process=subprocess.Popen([shutil.which('redis-server'),'--port','0','--unixsocket',socket,'--unixsocketperm','700','--save','','--appendonly','no'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        client=redis.Redis(unix_socket_path=socket,socket_timeout=1)
        hub=RedisHub()
        try:
            for _ in range(60):
                try:
                    if client.ping():break
                except redis.ConnectionError:time.sleep(.03)
            assert client.ping()
            script=client.register_script(SLIDING_WINDOW_LUA)
            monkeypatch.setattr(hub,'_operation',lambda:(client,script,None))
            with ThreadPoolExecutor(max_workers=16) as pool:
                rows=list(pool.map(lambda _:hub.sliding_window_snapshot('fixture:admission',16),range(24)))
            assert sum(row['allowed'] for row in rows)==16
            assert sorted(row['remaining'] for row in rows if row['allowed'])==list(range(16))
            assert all(row['remaining']==0 for row in rows if not row['allowed'])
            assert all(1<=row['reset']<=60 for row in rows)
            monkeypatch.setattr(RedisHub,'get_instance',classmethod(lambda cls:hub))
            assert reserve_nonce('fixture-unique-replay',60) is True
            assert reserve_nonce('fixture-unique-replay',60) is False
            Path('reports/feature-remediation-2026-10-29/native-redis.json').write_text(json.dumps({'concurrent_requests':24,'limit':16,'admitted':16,'atomic_remainders':True,'nonce_replay_blocked':True})+'\n')
        finally:
            client.close();process.terminate();process.wait(timeout=5)
