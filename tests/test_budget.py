from __future__ import annotations

import unittest

import helpers  # noqa: F401  (puts the package on sys.path)

from context_bridge.budget import MAX_CHARS, deduplicate, normalise, select
from context_bridge.model import CRITICAL, Item


def item(section: str, text: str, source: str = "S1", order: int = 0, origin_rank: int = 3) -> Item:
    return Item(section, text, "fact", source, "test", order=order, origin_rank=origin_rank)


class DedupTests(unittest.TestCase):
    def test_exact_duplicates_merge_and_keep_the_higher_priority_copy(self) -> None:
        items = [
            item("conventions", "Never upload data without approval.", "S2"),
            item("constraints", "**Never** upload data without approval", "S1"),
        ]
        kept, removed = deduplicate(items)
        self.assertEqual(removed, 1)
        self.assertEqual([(i.section, i.source, i.also_in) for i in kept], [("constraints", "S1", ["S2"])])

    def test_near_duplicates(self) -> None:
        a = item("goals", "Ship the offline sync engine for field teams by March", "S1")
        b = item("goals", "Ship the offline sync engine for the field teams by March", "S2")
        c = item("goals", "Ship the online dashboard for managers by June", "S3")
        kept, removed = deduplicate([a, b, c])
        self.assertEqual(removed, 1)
        self.assertEqual([i.source for i in kept], ["S1", "S3"])

    def test_file_backed_copy_wins_over_the_session_copy(self) -> None:
        file_item = item("next_steps", "Write the verify command", "S1", origin_rank=2)
        session = item("next_steps", "Write the verify command.", "S9", origin_rank=0)
        kept, removed = deduplicate([file_item, session])
        self.assertEqual(removed, 1)
        self.assertEqual([(i.source, i.also_in) for i in kept], [("S1", ["S9"])])  # verifiable copy, session noted

    def test_session_only_statements_stay_with_the_session(self) -> None:
        kept, _ = deduplicate([item("goals", "Ship v2", "S9", origin_rank=0), item("goals", "Ship v3", "S1")])
        self.assertEqual(sorted(i.source for i in kept), ["S1", "S9"])

    def test_normalise(self) -> None:
        self.assertEqual(normalise("  **Use** `TOML`, please. "), "use toml , please")


class SelectTests(unittest.TestCase):
    def mixed(self) -> list[Item]:
        items = [item("structure", f"dir{n}/: {n} files (py {n})", "S5", order=n) for n in range(30)]
        items += [item("goals", "Ship v1 to two pilot teams.", "S1"), item("constraints", "No network access.", "S1"),
                  item("decisions", "Use SQLite as the local store.", "S1", order=1),
                  item("next_steps", "Write the sync queue.", "S1", order=2),
                  item("state", "Scan works; pack in progress.", "S1", order=3)]  # fmt: skip
        return items

    def test_context_is_dropped_before_critical_and_important(self) -> None:
        selection = select(self.mixed(), budget=400)
        kept_sections = {i.section for i in selection.kept}
        self.assertTrue({"goals", "constraints", "decisions", "next_steps", "state"} <= kept_sections)
        self.assertTrue(all(i.section == "structure" for i in selection.dropped))
        self.assertLessEqual(selection.estimated_tokens, 400)
        self.assertEqual(selection.critical_loss, [])
        self.assertEqual(selection.retention["structure"]["dropped"], len(selection.dropped))

    def test_critical_items_are_protected_by_default(self) -> None:
        items = [item("goals", f"Goal number {n} with enough words to cost tokens.", order=n) for n in range(40)]
        selection = select(items, budget=300)
        self.assertEqual(len(selection.kept), 40)
        self.assertTrue(selection.exceeded_to_protect_critical)
        self.assertEqual(selection.critical_loss, [])

    def test_hard_budget_reports_critical_loss(self) -> None:
        items = [item("goals", f"Goal number {n} with enough words to cost tokens.", order=n) for n in range(40)]
        selection = select(items, budget=300, hard_budget=True)
        self.assertLessEqual(selection.estimated_tokens, 300)
        self.assertGreater(len(selection.critical_loss), 0)
        self.assertTrue(all(reason == "dropped" for _i, reason in selection.critical_loss))
        self.assertEqual(selection.kept[0].text, "Goal number 0 with enough words to cost tokens.")

    def test_truncated_critical_items_count_as_loss(self) -> None:
        long_goal = item("goals", "x" * (MAX_CHARS[CRITICAL] + 50))
        selection = select([long_goal], budget=5000)
        self.assertEqual([(i.section, r) for i, r in selection.critical_loss], [("goals", "truncated")])
        self.assertIn("truncated", long_goal.flags)
        self.assertTrue(long_goal.text.endswith("…"))

    def test_section_caps_apply_to_non_critical_sections_only(self) -> None:
        overview = [item("overview", f"Overview sentence {n}.", order=n) for n in range(10)]
        decisions = [item("decisions", f"Decision {n}.", order=n) for n in range(40)]
        selection = select(overview + decisions, budget=100000)
        self.assertEqual(sum(1 for i in selection.kept if i.section == "overview"), 4)
        self.assertEqual(sum(1 for i in selection.kept if i.section == "decisions"), 40)


if __name__ == "__main__":
    unittest.main()
