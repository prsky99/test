"""The action a task asks for against the action a chosen tool does (PM 11-17 06:3x).

user_slo "send email" passed three times on a2a/87188's verify-email: a check of an address, not a sent message. A task
that asks to send gets no tool whose name says it only checks, looks up or reads, unless the task asks for that check
itself. Judged by the tool's name: descriptions of A2A skills say 'send "verify-email <email>"' for the protocol call.
Shared by the recommendation (gateway_exposure) and the measurement (scripts/user_slo.py), so both use one rule;
this module imports nothing from the service so the measurement stays light.
"""
import re

# Asking to send something. Not 'forward' (forward geocoding) or 'deliver' (delivery tracking reads a status).
SEND_TASK = re.compile(r'\b(?:send|sending|transmit|transmitting|dispatch)\b', re.I)
# A tool name that only checks, looks up or reads: at the start of the name or of one of its words.
CHECK_NAME = re.compile(r"""(?:^|[^a-z])(?:verif|validat|check|look[\s_-]?up|inspect|audit|intel|search|find|list|get
  |read|fetch|status)""", re.I | re.X)
# A tool name that sends.
SEND_NAME = re.compile(r'send|transmit|dispatch|deliver|compose|outbound|forward', re.I)


def _words(name):
    """camelCase split, so 'verifyEmail' and 'getStatus' show their verbs to CHECK_NAME."""
    return re.sub(r'(?<=[a-z0-9])(?=[A-Z])', ' ', str(name or ''))


def action_mismatch(task, tool_name):
    """True when TASK asks to send and TOOL_NAME only checks or reads (verify-email for "send email")."""
    if not isinstance(task, str) or not isinstance(tool_name, str) or not tool_name:
        return False
    if not SEND_TASK.search(task) or CHECK_NAME.search(task):
        return False   # the task does not send, or it asks for the check itself ("send ... and verify")
    name = _words(tool_name)
    return bool(CHECK_NAME.search(name)) and not SEND_NAME.search(name)
