"""Rule table for today's reading (fortune.daily.v1, daily-fortune-brief synthesis; PM 11-17, user request).

Every sentence comes from the fixed tables below; nothing is generated. The same inputs and date give the same text.
Traditions the tables follow (meanings summarised in our own words, for entertainment):
- Ten gods (sipsin 十神): the relation of today's day stem to the birth day master by the five elements' generation
  (wood > fire > earth > metal > water > wood) and control (wood > earth > water > fire > metal > wood) cycles and
  the stems' yin/yang, as in standard Four Pillars (saju, BaZi) texts.
- Western: the element of the Sun sign and of today's Moon sign (fire, earth, air, water); same element and the
  classic complements (fire with air, earth with water) read as easy, other pairs as contrasting.
- Colour of the day: the traditional colour of today's stem element (wood green, fire red, earth yellow, metal white,
  water black/navy).
Kept out: health, money or investment, legal and medical statements or advice, and frightening words; BANNED is
checked on every answer before it is returned.
"""
from __future__ import annotations

import re

RULES_VERSION = "fortune-rules-v1"
DISCLAIMER = "For entertainment; not advice."
THEMES = {  # ten god of today's stem against the day master -> (short headline, sentence)
    "Bigyeon 比肩": ("steady and self-reliant", "Today's stem matches your day master: a good day to work at your own "
                     "pace and to stand alongside people who share your goals."),
    "Geopjae 劫財": ("share the stage", "Today's stem is your element in the other polarity: things go more smoothly "
                     "when you share credit and keep plans simple."),
    "Siksin 食神": ("easy creativity", "Today's stem is born from your day master: a pleasant day for making, "
                    "cooking, writing or enjoying small pleasures."),
    "Sanggwan 傷官": ("bold ideas", "Today's stem is born from your day master in the other polarity: bold ideas come "
                      "easily, so choose your words with a little extra care."),
    "Pyeonjae 偏財": ("open to the new", "Today's stem is shaped by your day master: a day for new contacts, side "
                      "projects and flexible plans."),
    "Jeongjae 正財": ("orderly routines", "Today's stem is shaped by your day master in the other polarity: steady "
                      "routines and tidy finishing work feel rewarding."),
    "Pyeongwan 偏官": ("clear priorities", "Today's stem shapes your day master: a brisk day that rewards focus and a "
                       "short list of priorities."),
    "Jeonggwan 正官": ("keep your word", "Today's stem shapes your day master in the other polarity: a good day for "
                       "keeping commitments and doing things by the book."),
    "Pyeonin 偏印": ("quiet insight", "Today's stem feeds your day master: a day for quiet study, reflection and "
                     "unusual perspectives."),
    "Jeongin 正印": ("learn and receive", "Today's stem feeds your day master in the other polarity: a good day for "
                     "learning from others and accepting a helping hand."),
}
WESTERN = {
    "same": "Your {sign} Sun and today's {moon} Moon share the {element} element: an easy, familiar mood.",
    "complement": "Your {sign} Sun ({element}) and today's {moon} Moon ({moon_element}) are a classic complement: "
                  "things flow with little effort.",
    "contrast": "Your {sign} Sun ({element}) and today's {moon} Moon ({moon_element}) contrast: take things at an "
                "unhurried pace and enjoy the change of tone.",
}
COLOURS = {"wood": "green", "fire": "red", "earth": "yellow", "metal": "white", "water": "navy"}
COMPLEMENT = {frozenset({"fire", "air"}), frozenset({"earth", "water"})}
BANNED = re.compile(r"\b(health|ill|illness|sick|disease|accident|injur\w*|death|die|dying|invest\w*|stock|money|"
                    r"loan|debt|lawsuit|legal|lawyer|medical|doctor|diagnos\w*|surgery|hospital|danger\w*|disaster)\b",
                    re.IGNORECASE)


def western_tone(element: str, moon_element: str) -> str:
    e, m = element.lower(), moon_element.lower()
    if e == m:
        return "same"
    return "complement" if frozenset({e, m}) in COMPLEMENT else "contrast"


def reading(*, sign: str | None, element: str | None, moon_sign: str, moon_element: str, ten_god: str | None,
            today_element: str | None, today: str, hour_pillar_given: bool | None) -> dict:
    parts, head = [], []
    if ten_god in THEMES:
        head.append(THEMES[ten_god][0])
        parts.append(THEMES[ten_god][1])
    if sign and element:
        tone = western_tone(element, moon_element)
        head.append({"same": "familiar mood", "complement": "easy flow", "contrast": "change of tone"}[tone])
        parts.append(WESTERN[tone].format(sign=sign, element=element.lower(), moon=moon_sign,
                                          moon_element=moon_element.lower()))
    if today_element in COLOURS:
        parts.append(f"Colour of the day: {COLOURS[today_element]} ({today_element}, today's stem element).")
    if hour_pillar_given is False:
        parts.append("No hour pillar was used (birth hour not given), so the reading uses three pillars.")
    parts.append("Dates follow the Korean lunar calendar (KASI rules) and Korea standard time.")
    text = " ".join(parts)
    headline = f"{today}: " + (", ".join(head) if head else "a quiet day")
    if BANNED.search(text) or BANNED.search(headline):      # the tables must never produce these words
        raise ValueError("rule table produced a banned word")
    return {"disclaimer": DISCLAIMER, "headline": headline[:200], "reading": text[:3000],
            "rules_version": RULES_VERSION}
