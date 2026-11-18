"""The six fortune and 16-type contracts (workflow d1f863e9) are in the one role list but never queued: our own
computed substitutes fill them and none has a role task yet (검색과 RAG, after the 11-20 verdict)."""
from scripts import role_catalog

SIX = ('calendar.lunar_convert.v1', 'astro.western_sign.v1', 'saju.pillars.v1', 'fortune.daily.v1',
       'persona.personality_profile.v1', 'fortune.personality_daily.v1')


def test_the_six_are_listed_and_match_no_tool():
    for role in SIX:
        assert role_catalog.ROLES[role]['queue'].startswith('blocked')
        assert not role_catalog.default_checks(role)
    for name in ('calculate_bazi', 'get_bazi_chart', 'get_personality_daily_reading', 'get_personality_sample_profile',
                 'get_zodiac_sign', 'convert_lunar', ''):
        assert not set(SIX) & set(role_catalog.roles_for_tool(name)), name
