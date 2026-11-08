"""Token estimate for budgets, calibrated against real Claude token counts.

The standard library has no tokenizer, so tokens are estimated from a few text features:
letters (German lines cost about 1.5 times as much per letter as English ones), ASCII
punctuation, digits, other symbols and line breaks. A line counts as German when it
contains more German than English function words; lines without any count like the
whole text.

The weights were fitted to the measured token counts of synthetic samples (English and
German prose, rendered packs, resume output, a hook digest, Markdown with tables and
code, manifests). In leave-one-out validation the mean error is about 4 % and the
largest about 10 %; ``characters / 4`` was off by 39 % on average. Claude Haiku 5.5 and
Opus 5.5 counted the same tokens. Samples, measurements and the fitting script are in
``quality/tokens/``, the method in ``docs/quality.md``.
"""

from __future__ import annotations

import math
import re

ESTIMATOR = "calibrated-v1"  # recorded in every pack; a new calibration gets a new name
# Tokens per feature, fitted by quality/tokens/calibrate.py (tests check that they still match the data).
WEIGHTS = {
    "en_letters": 0.3436,
    "de_letters": 0.5103,
    "punct": 0.9120,
    "digits": 1.2926,
    "symbols": 0.7847,
    "newlines": 1.0254,
}
MAX_ERROR = 0.11  # largest leave-one-out error on the calibration samples, rounded up

_WORD = re.compile(r"[^\W\d_]+")
_DIGIT = re.compile(r"\d")
_PUNCT = re.compile(r"[!-/:-@\[-`{-~]")
_SYMBOL = re.compile(r"[^\x00-\x7f\w\s]")
DE_FUNCTION_WORDS = frozenset(
    "der die das den dem des ein eine einen einem einer und oder aber ist sind war wird werden nicht mit für auf "
    "aus bei von zu zum zur im an als auch wie wenn dass weil nur noch schon wir ich sie es er uns kein keine mehr "
    "bis nach über unter vor durch ohne gegen um ob sehr alle diese dieser dieses jede jeder jedes kann können muss "
    "soll sollen hat haben sich".split()
)
EN_FUNCTION_WORDS = frozenset(
    "the a an and or but is are was were be been not with for on of to in at by from as it its this that these "
    "those we you they can should must will would has have had do does every each all no more before after when "
    "if so than only into over about which there their".split()
)


def features(text: str) -> dict[str, int]:
    """The counts the estimate is based on."""
    words_per_line = [_WORD.findall(line) for line in text.split("\n")]
    votes = []
    for words in words_per_line:
        lowered = [w.lower() for w in words]
        votes.append(sum(w in DE_FUNCTION_WORDS for w in lowered) - sum(w in EN_FUNCTION_WORDS for w in lowered))
    german_text = sum(votes) > 0
    en_letters = de_letters = 0
    for words, vote in zip(words_per_line, votes, strict=True):
        letters = sum(map(len, words))
        if vote > 0 or (vote == 0 and german_text):
            de_letters += letters
        else:
            en_letters += letters
    return {
        "en_letters": en_letters,
        "de_letters": de_letters,
        "punct": len(_PUNCT.findall(text)),
        "digits": len(_DIGIT.findall(text)),
        "symbols": len(_SYMBOL.findall(text)),
        "newlines": text.count("\n"),
    }


def _raw(text: str) -> float:
    counts = features(text)
    return sum(weight * counts[name] for name, weight in WEIGHTS.items())


def estimate(text: str) -> int:
    """Estimated number of tokens (mean error about 4 %)."""
    return math.ceil(_raw(text)) if text else 0


def upper_bound(text: str) -> int:
    """An estimate that the real count stayed below on every calibration sample, for hard limits."""
    return math.ceil(_raw(text) * (1 + MAX_ERROR)) if text else 0
