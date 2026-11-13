"""Version ordering for GitHub advisory ranges (``>= 1.0, < 2.3.1``), npm semver and PyPI PEP 440.

GitHub's ``affects=name@version`` filter missed advisories whose package name
differs in case ("Scrapy") and pre-release versions (gold set 11-14: 3 of 30
cases). The agent therefore lists a package's advisories and checks the ranges
here. Unparseable versions or ranges are reported as unknown, never as safe.
"""
from __future__ import annotations

import re

_INF = float("inf")
_PEP440 = re.compile(
    r"v?(?:(?P<epoch>[0-9]+)!)?(?P<release>[0-9]+(?:\.[0-9]+)*)"
    r"(?:[-_.]?(?P<pre_l>a|alpha|b|beta|c|rc|pre|preview)[-_.]?(?P<pre_n>[0-9]*))?"
    r"(?:-(?P<post_n1>[0-9]+)|[-_.]?(?P<post_l>post|rev|r)[-_.]?(?P<post_n2>[0-9]*))?"
    r"(?:[-_.]?(?P<dev_l>dev)[-_.]?(?P<dev_n>[0-9]*))?"
    r"(?:\+[a-z0-9]+(?:[-_.][a-z0-9]+)*)?", re.I)
_PRE_RANK = {"a": 0, "alpha": 0, "b": 1, "beta": 1, "c": 2, "rc": 2, "pre": 2, "preview": 2}
_SEMVER = re.compile(r"v?([0-9]+)(?:\.([0-9]+))?(?:\.([0-9]+))?(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?")


def pep440_key(text: str):
    m = _PEP440.fullmatch(text.strip())
    if not m:
        raise ValueError("not a PEP 440 version")
    release = [int(x) for x in m["release"].split(".")]
    while len(release) > 1 and release[-1] == 0:
        release.pop()
    pre = (_PRE_RANK[m["pre_l"].lower()], int(m["pre_n"] or 0)) if m["pre_l"] else None
    post = m["post_n1"] or (m["post_n2"] or "0" if m["post_l"] else None)
    dev = int(m["dev_n"] or 0) if m["dev_l"] else None
    if pre is None and post is None and dev is not None:
        pre_key = (-_INF, 0)
    elif pre is None:
        pre_key = (_INF, 0)
    else:
        pre_key = pre
    return (int(m["epoch"] or 0), tuple(release), pre_key,
            -_INF if post is None else int(post), _INF if dev is None else dev)


def semver_key(text: str):
    m = _SEMVER.fullmatch(text.strip())
    if not m:
        raise ValueError("not a semver version")
    core = tuple(int(x or 0) for x in m.group(1, 2, 3))
    if not m[4]:
        return core + ((1,),)
    ids = tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in m[4].split("."))
    return core + ((0,) + ids,)


def key_for(ecosystem: str):
    return pep440_key if ecosystem in ("PyPI", "pip") else semver_key


def in_range(version: str, spec: str, ecosystem: str):
    """True / False, or None when the version or range cannot be read."""
    key = key_for(ecosystem)
    try:
        v = key(version)
        for part in spec.split(","):
            part = part.strip()
            m = re.fullmatch(r"(>=|<=|>|<|=|==)?\s*(\S+)", part)
            if not m:
                return None
            op, bound = m[1] or "=", key(m[2])
            if not {"<": v < bound, "<=": v <= bound, ">": v > bound, ">=": v >= bound,
                    "=": v == bound, "==": v == bound}[op]:
                return False
        return True
    except ValueError:
        return None
