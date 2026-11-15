"""jobs step for the verified MCP registry (E7, docs/VERIFIED_REGISTRY.md; ops wiring 11-15, public from 11-18).

Once an hour, in its own thread so a slow catalog read never holds the scheduler's other steps, it calls
verified_registry.run_job(store): one registered SELECT read in id pages, the snapshot gateway-data/registry/verified.json
and the change feed written atomically. run_job skips the public measurement windows itself; a skipped or failed run is
tried again at the next scheduler pass, not an hour later. Each finished run appends one line to
logs/ops/registry-job.jsonl (listed servers, entries, feed changes, seconds, or the error class).
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

EVERY_S = 3600
LOG = Path("logs/ops/registry-job.jsonl")


class VerifiedRegistryStep:
    EVERY_S = EVERY_S
    NAME = "verified_registry"
    JOB = ("verified_registry", "run_job")

    def __init__(self, store, clock=time.time, job=None, background=True, log: Path | None = None):
        self.store, self.clock, self._job = store, clock, job
        self.background, self.log = background, Path(log or LOG)
        self.thread, self.last_done = None, 0.0

    def _run(self, started):
        line = {"at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(started))}
        try:
            job = self._job
            if job is None:
                import importlib
                module, name = self.JOB
                job = getattr(importlib.import_module("agent_market." + module), name)
            result = job(self.store) or {}
            line["step"] = self.NAME
            line.update({k: v for k, v in result.items() if isinstance(v, (int, float, str)) and len(str(v)) < 200})
            if "skipped" not in result:
                self.last_done = started
        except Exception as exc:  # noqa: BLE001 - the next pass tries again; other steps keep running
            line["error"] = type(exc).__name__
        line["seconds"] = round(self.clock() - started, 1)
        try:
            self.log.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log, "a") as out:
                out.write(json.dumps(line) + "\n")
        except OSError:
            pass
        return line

    def run_due(self):
        now = self.clock()
        if now - self.last_done < self.EVERY_S or (self.thread is not None and self.thread.is_alive()):
            return None
        if not self.background:
            return {self.NAME: self._run(now)}
        self.thread = threading.Thread(target=self._run, args=(now,), name=self.NAME.replace("_", "-"), daemon=True)
        self.thread.start()
        return {self.NAME: "started"}


class LifecycleStep(VerifiedRegistryStep):
    """E6 lifecycle signals (agent team, docs/VERIFIED_REGISTRY.md): once a day, its own thread (up to 300 RDAP reads
    a second apart, about five minutes). tool_lifecycle.run_job skips the measurement windows itself."""
    EVERY_S = 86400
    NAME = "tool_lifecycle"
    JOB = ("tool_lifecycle", "run_job")
