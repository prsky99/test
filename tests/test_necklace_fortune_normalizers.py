"""daily-fortune-brief normalizers (PM 11-17): our substitutes' flat fields, the outside saju members' pillar lists
(agent team mapping: 35054 pillars[{key, value}], 405618 pillars[{name, chinese}]), today's pillar computed offline,
constant arguments passed as they are. Synthetic answers only."""
import json

from agent_market.necklaces import runner


def test_day_pillar_offline_matches_the_anchor():
    assert runner.day_pillar_of("2000-01-01") == "Mu-o 戊午"
    assert runner.day_pillar_of("2000-01-02") == "Gi-mi 己未"
    assert runner.day_pillar_of("not a date") is None


def test_calendar_stages_the_solar_date():
    ours = {"solar_date": "1990-05-15", "lunar_date": "1990-04-21", "is_leap_month": False, "calendar_basis": "korean_kasi"}
    out = runner.normalize("calendar.lunar_convert.v1", {"content": [{"type": "text", "text": json.dumps(ours)}]}, {})
    assert out == ours
    assert runner.normalize("calendar.lunar_convert.v1", {"lunar_date": "1990-04-21"}, {}) is None   # nothing to stage


def test_western_reads_fields_or_the_sign_name_in_text():
    assert runner.normalize("astro.western_sign.v1", {"sign": "Taurus", "element": "Earth"}, {}) == {"sign": "Taurus", "element": "Earth"}
    text = runner.normalize("astro.western_sign.v1", {"profile": "Born under the sign of Pisces; life path 7."}, {})
    assert text == {"sign": "Pisces", "element": "Water"}
    assert runner.normalize("astro.western_sign.v1", {"profile": "life path 7"}, {}) is None


def test_saju_from_our_substitute_and_both_outside_shapes():
    ours = {"year_pillar": "Gyeong-o 庚午", "month_pillar": "Sin-sa 辛巳", "day_pillar": "Gyeong-jin 庚辰",
            "hour_pillar": None, "day_master": "Gyeong 庚", "today": "2026-11-18", "today_day_pillar": "Gap-ja 甲子"}
    out = runner.normalize("saju.pillars.v1", ours, {})
    assert out["day_pillar"] == "Gyeong-jin 庚辰" and out["today_day_pillar"] == "Gap-ja 甲子" and "hour_pillar" not in out
    wenbu = {"pillars": [{"key": "year", "value": "庚午"}, {"key": "month", "value": "辛巳"}, {"key": "day", "value": "庚辰"},
                         {"key": "hour", "value": None}], "dayMaster": "庚 Metal"}
    a = runner.normalize("saju.pillars.v1", wenbu, {"today": "2026-11-18"})
    assert (a["year_pillar"], a["day_pillar"], a["day_master"]) == ("Gyeong-o 庚午", "Gyeong-jin 庚辰", "Gyeong 庚")
    assert a["today"] == "2026-11-18" and a["today_day_pillar"] == runner.day_pillar_of("2026-11-18")
    chinese = {"item": {"pillars": [{"name": "Year", "chinese": "庚午"}, {"name": "Month", "chinese": "辛巳"},
                                    {"name": "Day", "chinese": "庚辰"}], "dayMaster": {"stem": {"character": "庚"}}}}
    b = runner.normalize("saju.pillars.v1", chinese, {"today": "2026-11-18"})
    assert b["month_pillar"] == "Sin-sa 辛巳" and b["day_master"] == "Gyeong 庚"
    assert runner.normalize("saju.pillars.v1", {"text": "no pillars"}, {}) is None


def test_staged_fields_are_scalars_the_normalizers_give():
    for norm in (runner.norm_lunar, runner.norm_western, runner.norm_saju):
        assert norm in runner.STAGED_FIELDS
    out = runner.norm_saju({"day_pillar": "庚辰"}, {"today": "2026-11-18"})
    assert set(out) <= runner.STAGED_FIELDS[runner.norm_saju]
    assert all(isinstance(v, str) for v in out.values())


def test_constant_arguments_pass_as_they_are():
    args = runner.render({"date": "{{slot.calendar.solar_date}}", "timezone": "Asia/Seoul", "solarTime": False,
                          "time": "{{input.birth_hour}}"}, {"slot.calendar.solar_date": "1990-05-15"})
    assert args == {"date": "1990-05-15", "timezone": "Asia/Seoul", "solarTime": False}   # no hour: left out
