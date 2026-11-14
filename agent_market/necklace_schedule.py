"""jobs scheduler step for the necklaces (PM 14:2x 11-14: watch, daily summary and judge were never installed).

NecklaceStep runs inside the jobs scheduler (gateway/server.py, same place as FallbackWatchStep):

- every hour at :20, outside the quiet windows (:55-:10 and 03:50-05:10): the hourly watch
  (necklaces.watch.NecklaceWatch), then the judge rewrites gateway-data/necklaces/necklaces.json
  (and members.json), so held, testing and live entries follow within the hour
- once a day, at the first run from 05:20: the daily summary (necklaces.daily), digest in
  logs/ops/necklace-watch/<day>.md
- every run appends one line to logs/ops/necklace-watch/runs-<day>.jsonl, also with nothing to watch
  ("definitions": 0), so "did not run" and "nothing to do" are told apart

RetestStep starts the daily retests (watch design section 4): trial necklaces from 01:15 (done by 02:25,
before the 02:30 report batch), live necklaces from 03:10 (done by 03:48, before the 03:50 window). Each
runs 30 held-out cases, r1 and r2 on alternate days, with the single-pearl baseline on Mondays, through the
public relay under the shared provider budget. A necklace runs at most once a day (retest/started-<day>.json),
the run is a background thread so the scheduler never waits, and every window leaves a line in
runs-<day>.jsonl, also with no targets.
Each part logs and swallows its own failure; a failing part never stops the scheduler.
"""
import threading
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


# kind: (status, start HHMM, last start HHMM, finish by HHMM)
WINDOWS = {"trial": ("trial", 115, 145, 225), "live": ("live", 310, 320, 348)}
MIN_LEFT_S = 60


def _hhmm(now):
    local = time.localtime(now)
    return local.tm_hour * 100 + local.tm_min


def _at(now, hhmm):
    local = time.localtime(now)
    return time.mktime((local.tm_year, local.tm_mon, local.tm_mday, hhmm // 100, hhmm % 100, 0, 0, 0, -1))


class RetestStep:
    def __init__(self, root=Path("gateway-data/necklaces"), logs=Path("logs/ops/necklace-watch"), definitions_dir=None,
                 clock=time.time, run=None, background=True):
        from .necklaces import model
        self.root, self.logs, self.clock = Path(root), Path(logs), clock
        self.definitions_dir = Path(definitions_dir or model.DEFINITIONS)
        self._run, self.background = run, background
        self.last = {}            # kind -> day already handled by this process
        self.thread = None

    def run_due(self, force_kind=None):
        now = self.clock()
        day = time.strftime("%Y%m%d", time.localtime(now))
        kind = force_kind or next((k for k, (_, start, last, _end) in WINDOWS.items() if start <= _hhmm(now) <= last), None)
        if kind is None or self.last.get(kind) == day or (self.thread is not None and self.thread.is_alive()):
            return None
        self.last[kind] = day
        try:
            from .necklaces import model
            status = WINDOWS[kind][0]
            started = self._started(day)
            targets = [d for d in model.load_valid(self.definitions_dir)
                       if d["status"] == status and d["slug"] not in started]
        except Exception as exc:
            line = {"step": "retest", "kind": kind, "ok": False, "error": type(exc).__name__}
            _append(self.logs, line, now)
            return {"necklace_retest": line}
        if not targets:
            line = {"step": "retest", "kind": kind, "ok": True, "targets": 0}
            _append(self.logs, line, now)
            return {"necklace_retest": line}
        for defn in targets:
            started[defn["slug"]] = {"kind": kind, "at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(now))}
        self._write_started(day, started)
        work = lambda: self._work(kind, targets, now)
        if self.background:
            self.thread = threading.Thread(target=work, name="necklace-retest", daemon=True)
            self.thread.start()
            return {"necklace_retest": {"kind": kind, "started": [d["slug"] for d in targets]}}
        return {"necklace_retest": work()}

    def _work(self, kind, targets, started_at):
        from .necklaces import retest
        run = self._run or retest.run_daily
        finish = _at(started_at, WINDOWS[kind][3])
        split = retest.daily_split(started_at)
        singles = time.localtime(started_at).tm_wday == 0
        results, ok = [], True
        for defn in targets:
            left = finish - self.clock()
            if left < MIN_LEFT_S:
                results.append({"slug": defn["slug"], "skipped": "no_time"})
                continue
            try:
                results.append(run(defn, root=self.root, split=split, singles=singles, budget_s=left))
            except Exception as exc:
                ok = False
                results.append({"slug": defn["slug"], "error": type(exc).__name__})
                log.warning("necklace retest %s failed: %s", defn["slug"], type(exc).__name__)
        line = {"step": "retest", "kind": kind, "ok": ok, "targets": len(targets), "split": split, "singles": singles,
                "results": results}
        _append(self.logs, line, self.clock())
        return line

    def _started(self, day):
        try:
            return json.loads((self.root / "retest" / f"started-{day}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _write_started(self, day, started):
        from .necklaces.judge import write_atomic
        write_atomic(self.root / "retest" / f"started-{day}.json", started)


def _append(logs, line, now):
    line = {"at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(now)), **line}
    try:
        Path(logs).mkdir(parents=True, exist_ok=True)
        path = Path(logs) / ("runs-" + time.strftime("%Y%m%d", time.localtime(now)) + ".jsonl")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError as exc:
        log.warning("necklace run line not written: %s", type(exc).__name__)
