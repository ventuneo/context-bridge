"""Prioritisation, duplicate removal and the token budget.

Order of importance: tier (critical, important, context), then section, then origin
(session handoff before files), then document order. Selection is greedy in that
order, so context goes first when space runs out.

Critical items (goals, constraints, decisions, next steps) are never dropped silently:
by default they are kept even if that exceeds the budget. With ``hard_budget`` they
can be dropped, and every dropped or shortened critical item is reported as
critical information loss.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from .model import CONTEXT, CRITICAL, FLAG_TRUNCATED, IMPORTANT, SECTION_BY_KEY, SECTION_INDEX, TIER_RANK, Item

DEFAULT_BUDGET = 2000
MIN_BUDGET = 200
HEADER_TOKENS = 120  # title, trust notice, status line
SOURCE_ROW_TOKENS = 18  # one row in the sources table
ITEM_OVERHEAD_CHARS = 40  # bullet, status label and source reference
MAX_CHARS = {CRITICAL: 2000, IMPORTANT: 500, CONTEXT: 300}
SIMILARITY = 0.85  # Jaccard similarity of word sets for near-duplicates
_STRIP = re.compile(r"[*_`~>#\[\]()|]")
_WORD = re.compile(r"\w+")


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / 4)


def item_tokens(item: Item) -> int:
    return math.ceil((len(item.text) + ITEM_OVERHEAD_CHARS) / 4)


def normalise(text: str) -> str:
    text = _STRIP.sub(" ", unicodedata.normalize("NFKC", text).casefold())
    return re.sub(r"\s+", " ", text).strip(" .;:,-")


def priority_key(item: Item) -> tuple[int, int, int, int]:
    return (TIER_RANK[item.tier], SECTION_INDEX[item.section], item.origin_rank, item.order)


def _replace(kept: list[Item], exact: dict[str, Item], by_size: dict[int, list[tuple[frozenset[str], Item]]],
             old: Item, new: Item) -> None:  # fmt: skip
    kept[kept.index(old)] = new
    for key, value in list(exact.items()):
        if value is old:
            exact[key] = new
    for entries in by_size.values():
        for index, (words, value) in enumerate(entries):
            if value is old:
                entries[index] = (words, new)


def deduplicate(items: list[Item]) -> tuple[list[Item], int]:
    """Remove exact and near-duplicates, keeping the highest-priority copy.

    The kept copy records the sources of removed copies in ``also_in``. When a session statement is
    also found in a file, the file copy is kept because it can be verified.
    """
    kept: list[Item] = []
    exact: dict[str, Item] = {}
    by_size: dict[int, list[tuple[frozenset[str], Item]]] = defaultdict(list)
    removed = 0
    for item in sorted(items, key=priority_key):
        norm = normalise(item.text)
        if not norm:
            removed += 1
            continue
        words = frozenset(_WORD.findall(norm))
        duplicate = exact.get(norm)
        if duplicate is None and len(words) >= 5:
            size = len(words)
            for other_size in range(math.ceil(size * SIMILARITY), math.floor(size / SIMILARITY) + 1):
                for other_words, other in by_size.get(other_size, ()):
                    if len(words & other_words) / len(words | other_words) >= SIMILARITY:
                        duplicate = other
                        break
                if duplicate is not None:
                    break
        if duplicate is not None:
            if duplicate.origin_rank == 0 and item.origin_rank > 0:
                # A session statement that a file also contains: keep the verifiable file copy as the
                # main item and record the session as an additional source.
                item.also_in = [s for s in [duplicate.source, *duplicate.also_in] if s != item.source]
                _replace(kept, exact, by_size, duplicate, item)
            elif item.source != duplicate.source and item.source not in duplicate.also_in:
                duplicate.also_in.append(item.source)
            removed += 1
            continue
        exact[norm] = item
        by_size[len(words)].append((words, item))
        kept.append(item)
    return kept, removed


@dataclass
class Selection:
    kept: list[Item]
    dropped: list[Item]
    truncated: list[Item]
    estimated_tokens: int
    exceeded_to_protect_critical: bool
    retention: dict[str, dict[str, int]] = field(default_factory=dict)

    @property
    def critical_loss(self) -> list[tuple[Item, str]]:
        """Critical items that were dropped, or kept only in shortened form."""
        lost = [(item, "dropped") for item in self.dropped if item.tier == CRITICAL]
        lost += [(item, "truncated") for item in self.truncated if item.tier == CRITICAL and item in self.kept]
        return lost


def _truncate(item: Item) -> bool:
    cap = MAX_CHARS[item.tier]
    if len(item.text) <= cap:
        return False
    item.text = item.text[: cap - 1].rstrip() + "…"
    item.add_flag(FLAG_TRUNCATED)
    return True


def select(items: list[Item], budget: int = DEFAULT_BUDGET, hard_budget: bool = False) -> Selection:
    """Choose items for the pack within ``budget`` tokens (see module docstring)."""
    # Idempotent: select may run again on the same items when the rendered pack is too large.
    truncated = [item for item in items if _truncate(item) or FLAG_TRUNCATED in item.flags]
    used = HEADER_TOKENS
    sources: set[str] = set()
    per_section: Counter[str] = Counter()
    kept: list[Item] = []
    dropped: list[Item] = []
    exceeded = False
    for item in sorted(items, key=priority_key):
        spec = SECTION_BY_KEY[item.section]
        if spec.max_items is not None and per_section[item.section] >= spec.max_items:
            dropped.append(item)
            continue
        cost = item_tokens(item) + (0 if item.source in sources else SOURCE_ROW_TOKENS)
        fits = used + cost <= budget
        if fits or (item.tier == CRITICAL and not hard_budget):
            exceeded = exceeded or not fits
            kept.append(item)
            used += cost
            sources.add(item.source)
            per_section[item.section] += 1
        else:
            dropped.append(item)

    retention: dict[str, dict[str, int]] = {}
    for item in items:
        stats = retention.setdefault(item.section, {"extracted": 0, "kept": 0, "dropped": 0, "truncated": 0})
        stats["extracted"] += 1
    for item in kept:
        retention[item.section]["kept"] += 1
    for item in dropped:
        retention[item.section]["dropped"] += 1
    for item in truncated:
        retention[item.section]["truncated"] += 1
    return Selection(kept, dropped, truncated, used, exceeded, retention)


def tier_counts(items: list[Item]) -> dict[str, int]:
    counts = {CRITICAL: 0, IMPORTANT: 0, CONTEXT: 0}
    for item in items:
        counts[item.tier] += 1
    return counts


# --- coverage ------------------------------------------------------------------------
COVERAGE_ALL = "all_extracted_items_kept"
COVERAGE_PARTIAL = "partial"
COVERAGE_CRITICAL = "critical_loss"
COVERAGE_STATUSES = (COVERAGE_ALL, COVERAGE_PARTIAL, COVERAGE_CRITICAL)


def coverage_of(retention: dict[str, dict[str, int]], kept_items: int, truncated_kept: int, critical_loss: int) -> dict:
    """The pack's declared coverage, derived only from counts so ``verify`` can recompute it.

    A pack is never called complete or lossless: even when every extracted item is kept,
    extraction itself is selective (text outside recognised sections is not packed).
    """
    dropped = {CRITICAL: 0, IMPORTANT: 0, CONTEXT: 0}
    extracted = 0
    for key, stats in retention.items():
        dropped[SECTION_BY_KEY[key].tier] += stats["dropped"]
        extracted += stats["extracted"]
    total = sum(dropped.values())
    detail = ", ".join(f"{tier} {n}" for tier, n in dropped.items() if n) or "none"
    if critical_loss:
        status = COVERAGE_CRITICAL
        statement = (
            f"CRITICAL INFORMATION LOSS: {critical_loss} critical item(s) were dropped or shortened; "
            f"{total} of {extracted} extracted items were left out ({detail})."
        )
    elif total or truncated_kept:
        status = COVERAGE_PARTIAL
        statement = (
            f"PARTIAL: {total} of {extracted} extracted items were left out to fit the budget ({detail}) "
            f"and {truncated_kept} were shortened. Extraction is selective as well."
        )
    else:
        status = COVERAGE_ALL
        statement = (
            f"All {kept_items} extracted items are included. Extraction is selective: text outside "
            "recognised sections is not in the pack, so the pack is not a full copy of the project."
        )
    return {
        "status": status,
        "extracted_items": extracted,
        "kept_items": kept_items,
        "dropped_items": dropped,
        "truncated_items": truncated_kept,
        "extraction": "selective",
        "statement": statement,
    }
