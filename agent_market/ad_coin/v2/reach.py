"""Measured reach by budget, on the Korean operator screen /ad-coin/v2/admin (PM 11-18 19:13 and 19:4x; AI AD Coin).

Not on the public /advertise page until measured outside shows reach PM's bar (about 20 a day per surface).

Only measured numbers. A daily snapshot (scripts/ad_coin_reach_snapshot.py, run off the request path) holds the last
7 full UTC days:
  - booked placement-days that have ended (coin and USDC bookings): the denominator;
  - Sponsored cards or lines actually shown, per surface: Explore, Chat, agent answers (MCP and A2A) from
    adc2_sponsored_impressions, necklace answers from the necklace served log (sponsored_agent).
Shown counts never include our own measurement requests (X-Agentcon-QA) or Early-Data replays; those are not counted
where they are recorded.

The operator screen turns that into "about N shown" per budget: placements (budget / price) times shown per booked
placement-day, per surface, rounded to the nearest whole number. A zero stays 0. A missing, unreadable or stale
snapshot (older than STALE_DAYS) shows no table at all rather than old figures.
"""
import html
import json
import os
import time
from pathlib import Path

SNAPSHOT = "gateway-data/ads/reach-7d.json"
WINDOW_DAYS = 7
STALE_DAYS = 3
BUDGETS_USDC = (10, 25, 50, 100)
SURFACES = (("explore", "Explore"), ("chat", "Chat"), ("agent_answers", "에이전트 답변"),
            ("necklace", "목걸이 답변"))
_cache = {"key": None, "value": None}


def parse_counts(lines):
    """kind|key|value lines from deploy/ops/adcoin-reach-7d.sql -> (booked placement-days, {placement: shown})."""
    booked, shown = 0, {}
    for line in lines:
        parts = line.strip().split("|")
        if len(parts) != 3 or not parts[2].strip().lstrip("-").isdigit():
            continue
        kind, key, value = parts[0].strip(), parts[1].strip(), int(parts[2])
        if kind == "booked" and key == "placement_days":
            booked = value
        elif kind == "served" and key:
            shown[key] = shown.get(key, 0) + value
    return booked, shown


def build_snapshot(booked, shown, necklace_shown, *, measured_at, through_day):
    """The snapshot written once a day. NECKLACE_SHOWN is the necklace log total for the same window."""
    return {"window_days": WINDOW_DAYS, "through_day": through_day, "measured_at": int(measured_at),
            "booked_placement_days": int(booked),
            "shown": {"explore": int(shown.get("explore", 0)), "chat": int(shown.get("chat", 0)),
                      "agent_answers": int(shown.get("mcp", 0)) + int(shown.get("a2a", 0)),
                      "necklace": int(necklace_shown)}}


def write_snapshot(path, snapshot):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(snapshot, sort_keys=True))
    os.replace(tmp, path)


def read_snapshot(path, now=None):
    """The snapshot if it is readable and fresh, else None. Re-read only when the file changes (one stat a call)."""
    try:
        stat = Path(path).stat()
    except OSError:
        return None
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    if _cache["key"] != key:
        try:
            value = json.loads(Path(path).read_text())
            int(value["booked_placement_days"])
            {name: int(value["shown"][name]) for name, _ in SURFACES}
        except (OSError, ValueError, KeyError, TypeError):
            value = None
        _cache.update(key=key, value=value)
    value = _cache["value"]
    now = time.time() if now is None else now
    if value is None or now - int(value.get("measured_at", 0)) > STALE_DAYS * 86400:
        return None
    return value


def expected(snapshot, budget_usdc, price_usdc):
    """{surface: about how many shown} for a budget, from the measured shown per booked placement-day."""
    placements = int(budget_usdc // price_usdc)
    booked = int(snapshot["booked_placement_days"])
    return placements, {name: (round(placements * int(snapshot["shown"][name]) / booked) if booked else 0)
                        for name, _ in SURFACES}


def table_html(snapshot, price_usdc):
    """The Korean operator card, or '' when there is no fresh snapshot."""
    if not snapshot:
        return ""
    e = html.escape
    shown = snapshot["shown"]
    # one column per budget and one row per surface: five short columns stay readable at 375 px
    plans = [expected(snapshot, budget, price_usdc) for budget in BUDGETS_USDC]
    head = "".join("<th scope=\"col\">%d</th>" % budget for budget in BUDGETS_USDC)
    rows = ["<tr><th scope=\"row\">예약 칸-일</th>%s</tr>" % "".join("<td>%d</td>" % placements
                                                                    for placements, _ in plans)]
    for name, label in SURFACES:
        rows.append("<tr><th scope=\"row\">%s</th>%s</tr>" % (e(label), "".join("<td>%d</td>" % about[name]
                                                                              for _, about in plans)))
    measured = ", ".join("%s %d회" % (label, int(shown[name])) for name, label in SURFACES)
    return ('<section class="card" id="reach" aria-labelledby="reach-h"><h2 id="reach-h">예산별 예상 노출</h2>'
            '<p>지난 %d일 동안 예약 칸-일 하나에 실제로 나간 노출을 예산의 칸 수에 곱한 값입니다. 반올림했고, 0은 그 화면에 '
            '나간 노출이 없었다는 뜻입니다. 공개 화면에는 아직 싣지 않습니다(화면별 외부 노출이 하루 평균 20회 이상이 되면 PM이 정함).</p>'
            '<div class="table-wrap"><table class="data-table"><caption class="caption">예산별로 Sponsored 칸이 나갔을 '
            '횟수(화면별)</caption><thead><tr><th scope="col">예산(USDC)</th>%s</tr></thead><tbody>%s</tbody>'
            '</table></div><p class="caption">%s(UTC)까지: 끝난 예약 칸-일 %d개, 실제 노출 %s. 우리 측정 요청(X-Agentcon-QA)과 '
            'Early-Data 재전송은 세지 않지만, 헤더 없는 우리 방문은 가려지지 않습니다. 예약 칸-일은 자체 광고주 몫을 포함합니다.</p>'
            '</section>'
            % (int(snapshot["window_days"]), head, "".join(rows), e(str(snapshot["through_day"])),
               int(snapshot["booked_placement_days"]), e(measured)))
