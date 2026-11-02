"""No undefined names in the application code (pyflakes, added to requirements-dev 11-02).

Unused imports and redefinitions (about 3,700 across the repository) are not checked here; an
undefined name is a NameError waiting for its code path, as /chat lost its JSON handler on 11-01.
"""
import pytest

pyflakes_api = pytest.importorskip('pyflakes.api')
from pyflakes import messages, reporter  # noqa: E402
from pathlib import Path  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
# Reviewed false positives: (file, name). report_snapshot reads `worked` only from the second
# chunk on, after the first chunk has set it.
ALLOWED = {('agent_market/concierge/report_snapshot.py', 'worked')}


class Collect(reporter.Reporter):
    def __init__(self):
        super().__init__(None, None)
        self.found = []

    def flake(self, message):
        self.found.append(message)

    def syntaxError(self, filename, msg, lineno, offset, text):
        self.found.append('%s:%s: %s' % (filename, lineno, msg))

    def unexpectedError(self, filename, msg):
        self.found.append('%s: %s' % (filename, msg))


def test_application_code_has_no_undefined_names():
    collect = Collect()
    for path in sorted((ROOT / 'agent_market').rglob('*.py')):
        pyflakes_api.checkPath(str(path), collect)
    problems = []
    for found in collect.found:
        if isinstance(found, str):
            problems.append(found)
        elif isinstance(found, messages.UndefinedName):
            name = Path(found.filename).resolve().relative_to(ROOT).as_posix()
            if (name, found.message_args[0]) not in ALLOWED:
                problems.append(str(found))
    assert problems == []
