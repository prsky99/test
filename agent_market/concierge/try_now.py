"""The one call that works right now (PM 11-17 22:xx, growth item 1).

One source for the line that leads the MCP instructions (initialize and server/discover) and, next, the agent pages.
Only an example that succeeds today goes here: until a necklace is public it is find_agents with a task whose first
recommendation carries a filled "Run here" line (checked at the origin and the public address on 11-17); once
website-trust-brief is public it becomes that necklace's call.
"""

TASK = 'Weather forecast for Seoul'


def line():
    """English text an agent can act on at once; one call, no key, no session state needed."""
    return ('Try it now (one call, no key): call `find_agents` with {"task": "' + TASK + '"}. '
            'Each of the up to three results carries a "Run here: call {...}" line; send that object to `call` '
            'as it is to get the answer in this session.')
