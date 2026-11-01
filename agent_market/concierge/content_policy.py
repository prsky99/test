"""Public listing policy: adult services stay out of browsing and task results.

They remain reachable when a caller searches for the listing by its own name."""
import re

# Explicit phrases only; "adult education" or a "police escort" must not match.
ADULT = re.compile(
    r"\b(?:escorts?\s+(?:directory|directories|service|services|agency|agencies|listings?|girls?|ads?)"
    r"|escort\s*fox|porn\w*|xxx|nsfw|onlyfans|erotic\w*|hentai|cam\s*girls?|camgirls?|strip\s*clubs?"
    r"|sex\s+(?:work|workers|chat|toys?|dating|cams?)"
    r"|adult\s+(?:content|entertainment|videos?|sites?|dating|chat|services?|industry))\b",
    re.I,
)


def adult_listing(resource):
    """True when the listing's own name or description describes an adult service."""
    text = ' '.join(str(resource.get(key) or '') for key in ('name', 'description'))
    return bool(ADULT.search(text))


def hidden_from_public_list(resource, query=''):
    """Adult listings are shown only to a query that names the listing itself."""
    if not adult_listing(resource):
        return False
    wanted = str(query or '').strip().casefold()
    return not wanted or wanted != str(resource.get('name') or '').strip().casefold()
