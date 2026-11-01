"""Conditional GET comparison, including weak validators across proxies."""
import re

_TAG = r'(?:W/)?"[\x21\x23-\x7e\x80-\xff]*"'
_LIST = re.compile(r'\s*' + _TAG + r'\s*(?:,\s*' + _TAG + r'\s*)*\Z')
_VALUES = re.compile(_TAG)


def etag_matches(header, current):
    """If-None-Match on GET uses weak comparison; authorization comes first."""
    if not isinstance(header, str) or len(header) > 4096:
        return False
    if header.strip() == '*':
        return True
    if not _LIST.fullmatch(header):
        return False
    opaque = current.removeprefix('W/')
    return any(value.removeprefix('W/') == opaque for value in _VALUES.findall(header))


def prefers_markdown(accept):
    """Only explicit, acceptable Markdown requests override the default JSON/HTML."""
    if not isinstance(accept,str) or len(accept)>4096:
        return False
    choices=[]
    for index,part in enumerate(accept.lower().split(',')):
        media,*parameters=part.strip().split(';')
        if media not in ('text/markdown','application/json','text/html'):
            continue
        quality=1.0
        try:
            for parameter in parameters:
                if parameter.strip().startswith('q='):quality=float(parameter.strip()[2:])
        except ValueError:
            continue
        if 0<quality<=1:choices.append((quality,-index,media))
    return bool(choices and max(choices)[2]=='text/markdown')
