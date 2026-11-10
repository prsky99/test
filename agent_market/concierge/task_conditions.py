"""Declared task-condition evidence; this never verifies execution or grants authority."""

import re

from ..gateway.constraints import normalize_language, normalize_region, places_in_text

LANGUAGE = re.compile(
    r"\b(english|korean|japanese|chinese|spanish|french|german|arabic|portuguese|italian|russian|hindi)\b",
    re.I,
)
WORLD = re.compile(
    r"\b(?:worldwide|globally|global coverage|all countries|any country|any city|any location|anywhere)\b",
    re.I,
)
US_RESTRICTED = re.compile(
    r"\b(?:US NWS|US[- ]only|US weather|for (?:a |an )?US (?:location|city)|National Weather Service|NOAA|NWS)\b",
    re.I,
)


def requested(task):
    from .chat_task_spec import canonical_text
    from .query_intent import interpret

    text = interpret(canonical_text(task)).positive
    weather = bool(
        re.search(
            r"\b(?:weather|forecasts?|temperature)\b|\ub0a0\uc528|\uc608\ubcf4|\uae30\uc628",
            text,
            re.I,
        )
    )
    translation = bool(
        re.search(r"\b(?:translat\w*|translation)\b|\ubc88\uc5ed", text, re.I)
    )
    languages = (
        list(dict.fromkeys(normalize_language(m[0]) for m in LANGUAGE.finditer(text)))
        if translation
        else []
    )
    names = LANGUAGE.pattern.removeprefix(r"\b").removesuffix(r"\b")
    source = (
        re.search(r"\bfrom\s+" + names + r"\b", text, re.I) if translation else None
    )
    target = (
        re.search(r"\b(?:to|into)\s+" + names + r"\b", text, re.I)
        if translation
        else None
    )
    before = (
        list(LANGUAGE.finditer(text[: target.start()])) if target and not source else []
    )
    geographic_text = re.sub(
        r"\bin\s+(?:the\s+)?" + LANGUAGE.pattern + r"(?:\s+language)?",
        "",
        text,
        flags=re.I,
    )
    days = re.search(r"\bnext\s+(\d{1,3})\s+days?\b", text, re.I)
    horizon = (
        int(days[1])
        if days
        else 1
        if re.search(r"\btomorrow\b|\ub0b4\uc77c", text, re.I)
        else 7
        if re.search(r"\bnext week\b", text, re.I)
        else None
    )
    return {
        "regions": places_in_text(geographic_text) if weather else [],
        "languages": languages,
        "source_language": normalize_language(source[1])
        if source
        else normalize_language(before[-1][0])
        if before
        else None,
        "target_language": normalize_language(target[1]) if target else None,
        "forecast_days": horizon if weather else None,
        "forecast": bool(
            weather
            and re.search(
                r"\b(?:tomorrow|forecasts?|next\s+\d+\s+days?)\b|\ub0b4\uc77c|\uc608\ubcf4",
                text,
                re.I,
            )
        ),
    }


def _enums(tool, pattern, normalize):
    schema = tool.get("inputSchema") or {}
    properties = schema.get("properties") or {} if isinstance(schema, dict) else {}
    values = set()
    for name, field in properties.items() if isinstance(properties, dict) else []:
        if (
            isinstance(name, str)
            and re.fullmatch(pattern, name, re.I)
            and isinstance(field, dict)
            and isinstance(field.get("enum"), list)
        ):
            values.update(filter(None, (normalize(v) for v in field["enum"][:100])))
    return values


def assess(task, resource, tool=None, *, conditions=None):
    """Known restrictions deny; unrecorded support remains explicitly unknown."""
    wanted = requested(task) if conditions is None else conditions
    tool = tool or {}
    primary = (
        str(resource.get("name") or "") + " " + str(resource.get("description") or "")
    )
    detail = (
        str(tool.get("name") or "").replace("_", " ")
        + " "
        + str(tool.get("description") or "")
    )
    matched, unknown, violated = [], [], []
    if wanted["regions"]:
        target = set(wanted["regions"])
        enum = _enums(
            tool, r"country|country_?code|region|jurisdiction", normalize_region
        )
        text = primary + " " + detail
        scope = set(places_in_text(text))
        excluded = set()
        for match in re.finditer(
            r"\b(?:not available|not supported|unavailable|excluding|except|does not cover)\b[^.;\n]{0,80}",
            text,
            re.I,
        ):
            excluded.update(places_in_text(match[0]))
        expanded = enum | ({"de", "fr"} if "eu" in enum else set())
        # A generic map coordinate is not evidence that a regional provider is global.
        restricted_us = bool(
            US_RESTRICTED.search(detail)
            or US_RESTRICTED.search(primary)
            and not WORLD.search(primary)
        )
        explicit_only = bool(
            re.search(r"\b(?:US[- ]only|United States only)\b", text, re.I)
        )
        if (
            target.intersection(excluded)
            or enum
            and not target.issubset(expanded)
            or "us" not in target
            and (restricted_us or explicit_only)
        ):
            violated.append("region")
        elif (
            enum
            and target.issubset(expanded)
            or WORLD.search(text)
            or target.issubset(scope)
        ):
            matched.append("region")
        elif scope and not target.intersection(scope):
            violated.append("region")
        else:
            unknown.append("region")
    if wanted["languages"]:
        languages = set(wanted["languages"])
        enum = _enums(tool, r"language|lang", normalize_language)
        source = _enums(tool, r"(?:source|from)_?lang(?:uage)?", normalize_language)
        target = _enums(
            tool, r"(?:target|output|to)_?lang(?:uage)?", normalize_language
        )
        text = primary + " " + detail
        named = {normalize_language(m[0]) for m in LANGUAGE.finditer(text)}
        directional_mismatch = (
            source
            and wanted["source_language"]
            and wanted["source_language"] not in source
            or target
            and wanted["target_language"]
            and wanted["target_language"] not in target
        )
        if enum and not languages.issubset(enum) or directional_mismatch:
            violated.append("language_pair")
        elif languages.issubset(named | enum) or (
            wanted["source_language"] in source and wanted["target_language"] in target
        ):
            matched.append("language_pair")
        elif re.search(r"\bonly\b", text, re.I) and named:
            violated.append("language_pair")
        else:
            unknown.append("language_pair")
    if wanted["forecast"]:
        if re.search(
            r"\b(?:forecast|forecasts|forecasting)\b", detail or primary, re.I
        ):
            matched.append("forecast")
        else:
            unknown.append("forecast")
    if wanted["forecast_days"]:

        def horizons(value):
            return [
                int(match[1] or match[2])
                for match in re.finditer(
                    r"\b(\d{1,3})[- ]day\s+(?:weather\s+)?forecasts?\b|\bforecasts?\s+(?:up to|for|the next)\s+(\d{1,3})\s+days?\b",
                    value,
                    re.I,
                )
            ]

        horizon = horizons(detail) or horizons(primary)
        schema = tool.get("inputSchema") or {}
        enum = schema.get("properties", {}) if isinstance(schema, dict) else {}
        fields = (
            [
                value
                for key, value in enum.items()
                if key in ("days", "forecast_days", "horizon")
                and isinstance(value, dict)
            ]
            if isinstance(enum, dict)
            else []
        )
        maximum = [
            field["maximum"]
            for field in fields
            if type(field.get("maximum")) in (int, float)
        ]
        limits = maximum or horizon
        if limits and wanted["forecast_days"] > max(limits):
            violated.append("forecast_window")
        elif limits:
            matched.append("forecast_window")
        else:
            unknown.append("forecast_window")
    return {
        "status": "mismatch" if violated else "unknown" if unknown else "match",
        "matched": matched,
        "unknown": unknown,
        "violated": violated,
        "requested": wanted,
        "evidence_source": "declared_contract",
        "execution_verified": False,
    }


def explanation(check):
    """English product copy contains neither raw requests nor provider instructions."""
    labels = {
        "region": "requested region",
        "language_pair": "requested language pair",
        "forecast": "forecast capability",
        "forecast_window": "requested forecast window",
        "requested_condition": "additional requested condition",
    }
    parts = []
    if check.get("matched"):
        parts.append(
            "Recorded support: "
            + ", ".join(labels[k] for k in check["matched"] if k in labels)
            + "."
        )
    if check.get("unknown"):
        parts.append(
            "Not confirmed: "
            + ", ".join(labels[k] for k in check["unknown"] if k in labels)
            + ". Review before running."
        )
    if check.get("violated"):
        parts.append(
            "Recorded restrictions do not cover the "
            + ", ".join(labels[k] for k in check["violated"] if k in labels)
            + "."
        )
    return " ".join(parts)
