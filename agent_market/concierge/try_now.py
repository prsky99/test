"""The one call that works right now (PM 11-17 22:xx, growth item 1; changed PM 11-18).

One source for the line that leads the MCP instructions (initialize and server/discover) and, next, the agent pages.
Only an example that succeeds today goes here. 11-17 it was find_agents "Weather forecast for Seoul", but its first
result (214768, faceabot.com) is a member whose terms verdict is prohibits, and from 11-19 00:30 such members are not
relayed (PM 11-18). It is now a direct call of our own Country Profile agent (133020, World Bank data, terms
allowed): it does not depend on how a search ranks, so it cannot lead to a prohibited member when rankings change
(checked at the origin on 11-18: 0.27 s, Japan / Tokyo / East Asia & Pacific). find_agents stays the way to your own
task. Once website-trust-brief is public the example becomes that necklace's call.
"""
import json

CALL = {'resource_id': 133020, 'tool': 'get_country_profile', 'arguments': {'country_code': 'JP'}}


def line():
    """English text an agent can act on at once; one call, no key, no session state needed."""
    return ('Try it now (one call, no key): call `call` with ' + json.dumps(CALL, separators=(',', ':')) +
            ' for a country profile from World Bank data. For your own task, call `find_agents` with '
            '{"task": "<what you need>"}; each result carries a "Run here: call {...}" line you can send to `call` '
            'as it is.')
