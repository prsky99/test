"""Deterministic screening of sponsor text and of free text near money moves.

Sponsor creatives are untrusted data. Rules here run without a model and reject
instructions aimed at agents, self-vouching safety claims and requests for keys
or wallets. Passing this screen is not a quality or truth review.
"""
import re
import unicodedata

MAX_TITLE = 80
MAX_BODY = 400
MAX_QUESTION = 160
MAX_ANSWER = 40

_PATTERNS = (
    ('agent_instruction', r'\b(ignore|disregard|forget|override)\b.{0,40}\b(previous|prior|above|earlier|all|system)\b.{0,20}\b(instruction|prompt|rule|message)s?\b'),
    ('agent_instruction', r'\b(you are|act as|as an ai|system prompt|developer message|assistant:)\b'),
    ('agent_instruction', r'(\uc774\uc804|\uc704\uc758|\uc55e\uc758|\ubaa8\ub4e0)\s*(\uc9c0\uc2dc|\uba85\ub839|\uaddc\uce59|\ud504\ub86c\ud504\ud2b8).{0,10}(\ubb34\uc2dc|\uc78a)'),
    ('self_vouching', r'\b(risk|safety)\s*(level|score)?\s*[:=]?\s*(low|none|safe|verified)\b'),
    ('self_vouching', r'\b(pre-?approved|already verified|verified offline|auto-?approve|safe to (sign|send|transfer))\b'),
    ('self_vouching', r'(\uc704\ud5d8\ub3c4|\uc548\uc804\ub3c4)\s*[:：]?\s*(\ub0ae\uc74c|\uc5c6\uc74c|\uc548\uc804)|\uac80\uc99d\s*\uc644\ub8cc|\uc0ac\uc804\s*\uc2b9\uc778'),
    ('wallet_request', r'\b(seed|recovery|secret)\s*(phrase|words?|key)\b|\bprivate\s*key\b|\bmnemonic\b'),
    ('wallet_request', r'\b(send|transfer|move)\b.{0,30}\b(coins?|tokens?|funds|balance|wallet)\b.{0,30}\b(to|into)\b'),
    ('wallet_request', r'(\uc2dc\ub4dc|\ubcf5\uad6c)\s*(\ubb38\uad6c|\uad6c\ubb38)|\uac1c\uc778\s*\ud0a4|\ube44\ubc00\s*\ud0a4|(\ucf54\uc778|\uc794\uc561|\uc9c0\uac11).{0,15}(\uc1a1\uae08|\uc774\uc804|\ubcf4\ub0b4)'),
    ('hidden_markup', r'<\s*(script|iframe|img|style|svg)|javascript:|data:text/html|!\[[^\]]*\]\('),
)
_COMPILED = tuple((name, re.compile(pattern, re.IGNORECASE | re.DOTALL)) for name, pattern in _PATTERNS)
_INVISIBLE = re.compile('[​-‏‪-‮⁠-⁤﻿]')


class ScreeningRejected(ValueError):
    def __init__(self, reasons):
        super().__init__('Rejected: ' + ', '.join(reasons))
        self.reasons = reasons


def normalize(text):
    if type(text) is not str:
        raise ScreeningRejected(['not_text'])
    if _INVISIBLE.search(text):
        raise ScreeningRejected(['invisible_characters'])
    text = unicodedata.normalize('NFKC', text)
    return re.sub(r'\s+', ' ', text).strip()


def findings(text):
    return sorted({name for name, pattern in _COMPILED if pattern.search(text)})


def screen_text(text, limit):
    value = normalize(text)
    if not value or len(value) > limit:
        raise ScreeningRejected(['length'])
    found = findings(value)
    if found:
        raise ScreeningRejected(found)
    return value


def screen_creative(title, body, question, answer):
    return {'title': screen_text(title, MAX_TITLE), 'body': screen_text(body, MAX_BODY),
            'question': screen_text(question, MAX_QUESTION), 'answer': screen_text(answer, MAX_ANSWER)}


def memo_findings(text):
    """For free text attached to transfers or spends: never blocks by itself,
    but any finding sends the move to a hold for the person to confirm."""
    if not text:
        return []
    try:
        return findings(normalize(text))
    except ScreeningRejected as exc:
        return exc.reasons
