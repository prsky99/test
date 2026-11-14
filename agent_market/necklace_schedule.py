"""jobs scheduler step for the necklaces (PM 14:2x 11-14: watch, daily summary and judge were never installed).

NecklaceStep runs inside the jobs scheduler (gateway/server.py, same place as FallbackWatchStep):

- every hour at :20, outside the quiet windows (:55-:10 and 03:50-05:10): the hourly watch
  (necklaces.watch.NecklaceWatch), then the judge rewrites gateway-data/necklaces/necklaces.json
  (and members.json), so held, testing and live entries follow within the hour
- once a day, at the first run from 05:20: the daily summary (necklaces.daily), digest in
  logs/ops/necklace-watch/<day>.md
- every run appends one line to logs/ops/necklace-watch/runs-<day>.jsonl, also with nothing to watch
  ("definitions": 0), so "did not run" and "nothing to do" are told apart

Retests (01:15 trial, 03:10 live) are not started here yet: no necklace is in trial or live. The line
records how many would be due ("retest_targets") so the first one shows up before it is missed.
Each part logs and swallows its own failure; a failing part never stops the scheduler.
"""
import json
import logging
import time
from pathlib import Path

log = logging.getLogger(__name__)

DAILY_FROM = 520          # local HHMM: after the 03:50-05:10 real-task window


class NecklaceStep:
    def __init__(self, store, root=Path("gateway-data/necklaces"), logs=Path("logs/ops/necklace-watch"),
                 definitions_dir=None, fingerprints=Path("gateway-data/fingerprints/pearls.json"), clock=time.time,
                 watch=None):
        from .necklaces import model
        self.store, self.root, self.logs, self.clock = store, Path(root), Path(logs), clock
        self.definitions_dir = Path(definitions_dir or model.DEFINITIONS)
        self.fingerprints = Path(fingerprints)
        self._watch = watch
        self.last_daily = None

    def watch(self):
        if self._watch is None:
            from .necklaces.watch import NecklaceWatch
            self._watch = NecklaceWatch(self.store, root=self.root, fingerprints=self.fingerprints,
                                        definitions_dir=self.definitions_dir, clock=self.clock)
        return self._watch

    def run_due(self, force=False):
        try:
            watch = self.watch()
            if not force and not watch.due():
                return None
        except Exception as exc:
            log.warning("necklace step failed before running: %s", type(exc).__name__)
            return {"necklaces": "failed"}
        now = self.clock()
        line = {"at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(now)), "ok": True}
        try:
            from .necklaces import model
            definitions = model.load_valid(self.definitions_dir)
            statuses = [d["status"] for d in definitions]
            line["definitions"] = len(definitions)
            line["by_status"] = {s: statuses.count(s) for s in sorted(set(statuses))}
            line["retest_targets"] = {"trial": statuses.count("trial"), "live": statuses.count("live")}
        except Exception as exc:
            definitions = None
            line.update(ok=False, definitions_error=type(exc).__name__)
            self.watch().last_hour = int(now // 3600)      # one failure line an hour, not one per loop
        for name, part in (("watch", self._run_watch), ("daily", lambda: self._run_daily(definitions, now)),
                           ("judge", self._run_judge)):
            if definitions is None:
                break
            try:
                result = part()
                if result is not None:
                    line[name] = result
            except Exception as exc:
                line["ok"] = False
                line[name] = {"error": type(exc).__name__}
                log.warning("necklace %s failed: %s", name, type(exc).__name__)
        self._append(line, now)
        if not line["ok"] or (line.get("watch") or {}).get("holds"):
            log.info("necklace step: %s", line)
        return {"necklaces": line}

    def _run_watch(self):
        return self.watch().run()

    def _run_daily(self, definitions, now):
        local = time.localtime(now)
        day = time.strftime("%Y%m%d", local)
        if self.last_daily == day or local.tm_hour * 100 + local.tm_min < DAILY_FROM:
            return None
        from .necklaces import daily
        result = daily.run(definitions, self.root, self.logs, now)
        self.last_daily = day
        return result

    def _run_judge(self):
        from .necklaces import judge
        result = judge.run_once(self.root, self.definitions_dir)
        return {"entries": result["entries"], "bytes": result["bytes"]}

    def _append(self, line, now):
        try:
            self.logs.mkdir(parents=True, exist_ok=True)
            path = self.logs / ("runs-" + time.strftime("%Y%m%d", time.localtime(now)) + ".jsonl")
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n")
        except OSError as exc:
            log.warning("necklace run line not written: %s", type(exc).__name__)
