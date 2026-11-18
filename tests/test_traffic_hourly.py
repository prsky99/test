"""PM 11-18: the reading script for the hourly counters (files only; UTC, four time zones, the quietest three hours)."""
import json

from scripts import traffic_hourly as th


def write(folder, day, pid, hourly=None):
    data = {'day': day, 'requests': {}}
    if hourly is not None:
        data['hourly'] = hourly
    (folder / f'{day}.{pid}.json').write_text(json.dumps(data))


def test_days_are_merged_per_process_and_days_without_counters_are_listed_not_zeroed(tmp_path):
    write(tmp_path, '2026-11-20', 1, {'page|08': 3, 'page|09': 2})
    write(tmp_path, '2026-11-20', 2, {'page|08': 4})                 # a second process of the same day adds
    write(tmp_path, '2026-11-19', 1)                                 # a day file from before the counters
    write(tmp_path, '2026-11-21', 1, {'page|08': 1, 'bad|99': 5, 'page|10': -4, 'page|11': 'x'})
    days, skipped, wanted = th.read_days(tmp_path, 3, end='2026-11-21')
    assert wanted == ['2026-11-19', '2026-11-20', '2026-11-21'] and skipped == ['2026-11-19']
    assert days['2026-11-20'] == {'page|08': 7, 'page|09': 2}
    utc = th.by_utc_hour(days)
    assert utc['page'][8] == 8 and utc['page'][9] == 2 and sum(utc['page']) == 10 and 'bad' not in utc   # bad hour, negative, text ignored


def test_zones_move_each_day_by_its_own_offset_and_the_quietest_window_wraps_midnight():
    # 2026-11-20 is winter (New York UTC-5, Seoul UTC+9); 2026-07-20 is summer (New York UTC-4)
    winter = {'2026-11-20': {'page|12': 10}}
    summer = {'2026-07-20': {'page|12': 10}}
    assert th.by_local_hour(winter, 'America/New_York')['page'][7] == 10
    assert th.by_local_hour(summer, 'America/New_York')['page'][8] == 10
    assert th.by_local_hour(winter, 'Asia/Seoul')['page'][21] == 10
    assert th.by_local_hour(winter, 'Europe/Berlin')['page'][13] == 10
    assert th.by_local_hour(winter, 'America/Los_Angeles')['page'][4] == 10
    busy = [5] * 24
    for hour in (23, 0, 1):
        busy[hour] = 0
    assert th.quietest_window(busy) == (23, 0)                       # 23:00-02:00, across midnight
    assert th.quietest_window([1] * 24) == (0, 3)                    # a tie goes to the earliest start


def test_report_prints_the_five_tables_and_says_so_when_nothing_has_counters(tmp_path):
    write(tmp_path, '2026-11-20', 1, {'mcp_call|03': 2, 'page|14': 9})
    days, skipped, wanted = th.read_days(tmp_path, 1, end='2026-11-20')
    text = th.render(days, skipped, wanted)
    for name in ('UTC (UTC)', 'US Eastern', 'US Pacific', 'Central Europe', 'Korea'):
        assert '## ' + name in text
    assert '| mcp_call | 2 |' in text and '| page | 9 |' in text and 'quietest 3 h' in text
    empty = th.render({}, ['2026-11-20'], ['2026-11-20'])
    assert 'No day in the window has hourly counters yet.' in empty
    assert th.read_days(tmp_path / 'missing', 2, end='2026-11-20')[0] == {}        # a missing folder is not an error
