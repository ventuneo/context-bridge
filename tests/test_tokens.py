"""Calibrated token estimate: accuracy on the measured samples, language handling, bounds, speed.

The measurements in quality/tokens/measurements.json are real token counts of the committed
samples (see quality/tokens/measure.py). These tests keep the estimate tied to that data.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import time
import unittest

from helpers import REPO_ROOT

from context_bridge import budget, tokens

TOKENS_DIR = REPO_ROOT / "quality" / "tokens"
if "cb_tokens_calibrate" in sys.modules:
    calibrate = sys.modules["cb_tokens_calibrate"]
else:
    _spec = importlib.util.spec_from_file_location("cb_tokens_calibrate", TOKENS_DIR / "calibrate.py")
    assert _spec and _spec.loader
    calibrate = importlib.util.module_from_spec(_spec)
    sys.modules["cb_tokens_calibrate"] = calibrate
    _spec.loader.exec_module(calibrate)

SAMPLES = calibrate.load()


class CalibrationTests(unittest.TestCase):
    def test_every_measured_sample_is_estimated_within_the_stated_error(self) -> None:
        errors = {}
        for name, text, measured in SAMPLES:
            errors[name] = (tokens.estimate(text) - measured) / measured
            with self.subTest(sample=name):
                self.assertLessEqual(abs(errors[name]), tokens.MAX_ERROR)
        self.assertLess(sum(map(abs, errors.values())) / len(errors), 0.05)  # mean error below 5 %

    def test_characters_divided_by_four_was_far_off(self) -> None:
        # The estimate this replaces: kept as a measured fact, not as code.
        old = [abs(len(text) / 4 - measured) / measured for _name, text, measured in SAMPLES]
        self.assertGreater(sum(old) / len(old), 0.3)

    def test_the_upper_bound_is_never_below_a_real_count(self) -> None:
        for name, text, measured in SAMPLES:
            with self.subTest(sample=name):
                self.assertGreaterEqual(tokens.upper_bound(text), measured)
                self.assertGreaterEqual(tokens.upper_bound(text), tokens.estimate(text))

    def test_weights_still_match_a_fresh_fit_of_the_data(self) -> None:
        fitted = calibrate.fit(SAMPLES)
        for name, weight in tokens.WEIGHTS.items():
            with self.subTest(feature=name):
                self.assertAlmostEqual(fitted[name], weight, delta=weight * calibrate.TOLERANCE)

    def test_leave_one_out_error_stays_within_max_error(self) -> None:
        errors = calibrate.leave_one_out(SAMPLES)
        self.assertLessEqual(max(map(abs, errors.values())), tokens.MAX_ERROR)

    def test_measurements_cover_german_english_and_markdown(self) -> None:
        names = {name for name, _text, _measured in SAMPLES}
        self.assertTrue({"text-de-prose.md", "text-en-prose.md", "text-markdown.md", "pack-german.md"} <= names)
        data = json.loads((TOKENS_DIR / "measurements.json").read_text(encoding="utf-8"))
        self.assertEqual(data["baseline_tokens"][0], data["baseline_tokens"][1])  # the measurement was stable
        opus = json.loads((TOKENS_DIR / "measurements-opus.json").read_text(encoding="utf-8"))
        haiku = {r["sample"]: r["tokens"] for r in data["samples"]}
        for row in opus["samples"]:  # a second model counted the same tokens
            self.assertEqual(row["tokens"], haiku[row["sample"]], row["sample"])


class BehaviourTests(unittest.TestCase):
    def test_empty_text_costs_nothing(self) -> None:
        self.assertEqual(tokens.estimate(""), 0)
        self.assertEqual(tokens.upper_bound(""), 0)

    def test_german_lines_cost_more_per_letter_than_english_ones(self) -> None:
        en = "The app is ready and the tests run on every commit before the release."
        de = "Die App ist bereit und die Tests laufen bei jedem Commit vor der Freigabe."
        self.assertEqual(tokens.features(en)["de_letters"], 0)
        self.assertEqual(tokens.features(de)["en_letters"], 0)
        per_letter = lambda t: tokens.estimate(t) / sum(c.isalpha() for c in t)  # noqa: E731
        self.assertGreater(per_letter(de), per_letter(en) * 1.3)

    def test_lines_without_function_words_follow_the_whole_text(self) -> None:
        german = "## Nächste Schritte\n- Die Übersicht der Ausleihen ist fertig und wird getestet.\n"
        english = "## Next steps\n- The overview of the loans is done and it is tested.\n"
        self.assertEqual(tokens.features(german)["en_letters"], 0)
        self.assertEqual(tokens.features(english)["de_letters"], 0)

    def test_digits_symbols_and_markup_are_counted(self) -> None:
        plain = tokens.estimate("version one")
        self.assertGreater(tokens.estimate("version 1.4.2 · `make test` | **x**"), plain)
        self.assertEqual(tokens.features("a\nb\nc")["newlines"], 2)

    def test_the_estimate_grows_with_the_text(self) -> None:
        text = "- [fact] Keep the API stable for old clients. — S3 README.md:4-6\n"
        self.assertLess(tokens.estimate(text), tokens.estimate(text * 2))
        self.assertAlmostEqual(tokens.estimate(text * 10) / tokens.estimate(text), 10, delta=0.5)

    def test_budget_constants_use_the_same_estimate(self) -> None:
        self.assertEqual(budget.ITEM_OVERHEAD_TOKENS, tokens.estimate("- [fact]  — S12 docs/notes.md:12-34\n"))
        self.assertGreater(budget.HEADER_TOKENS, 200)  # the trust notice, coverage and status lines are not free

    def test_large_inputs_stay_fast(self) -> None:
        text = (SAMPLES[0][1] + "\n") * 400  # about half a megabyte
        started = time.perf_counter()
        tokens.estimate(text)
        self.assertLess(time.perf_counter() - started, 2.0)


if __name__ == "__main__":
    unittest.main()
