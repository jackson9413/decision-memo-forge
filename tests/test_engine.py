"""Engine tests for Decision Memo Forge.

Run with:  python3 -m unittest discover -s tests -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import engine  # noqa: E402
import samples  # noqa: E402


STRONG = samples.SAMPLES["checkout-postgres-memo"]["text"]
WEAK = ("Hey team, we should probably maybe look at moving to the new database thing at some "
        "point soon. It might be a bit risky but we could possibly do it. Let me know what you "
        "think.")


def ids(report):
    return [f["id"] for f in report["findings"]]


class ParseTests(unittest.TestCase):
    def test_empty_text_is_safe(self):
        rep = engine.analyze("")
        self.assertIsInstance(rep["score"], float)
        self.assertIn("doc_too_short", ids(rep))

    def test_whitespace_only_is_safe(self):
        rep = engine.analyze("   \n\n  ")
        self.assertIn("doc_too_short", ids(rep))

    def test_headings_are_detected(self):
        doc = engine.parse_document("Context\n\nSome text here.\n\nDecision\n\nMore text.\n")
        titles = [h["text"] for h in doc["headings"]]
        self.assertIn("Context", titles)
        self.assertIn("Decision", titles)

    def test_markdown_table_is_parsed(self):
        doc = engine.parse_document("| A | B |\n| --- | --- |\n| 1 | 2 |\n| 3 | 4 |\n")
        self.assertEqual(len(doc["tables"]), 1)
        self.assertEqual(doc["tables"][0]["header"], ["A", "B"])
        self.assertEqual(len(doc["tables"][0]["rows"]), 2)

    def test_sentence_split_protects_abbreviations(self):
        sents = engine.split_sentences("We use e.g. Postgres. It works well. Cost is $5.")
        self.assertEqual(len(sents), 3)


class ArchetypeTests(unittest.TestCase):
    def test_memo_sample_detected(self):
        rep = engine.analyze(STRONG)
        self.assertEqual(rep["meta"]["doc_type"], "memo")

    def test_postmortem_sample_detected(self):
        rep = engine.analyze(samples.SAMPLES["incident-postmortem"]["text"])
        self.assertEqual(rep["meta"]["doc_type"], "postmortem")

    def test_explicit_hint_overrides_detection(self):
        rep = engine.analyze(STRONG, doc_type="proposal")
        self.assertEqual(rep["meta"]["doc_type"], "proposal")
        self.assertFalse(rep["meta"]["doc_type_detected"])

    def test_every_archetype_is_reachable(self):
        for key in engine.ARCHETYPE_ORDER:
            self.assertIn(key, engine.ARCHETYPE_INFO)


class StrongDocumentTests(unittest.TestCase):
    def setUp(self):
        self.rep = engine.analyze(STRONG, stakes="high", reversibility="two_way",
                                  audience="exec")

    def test_scores_high(self):
        self.assertGreaterEqual(self.rep["score"], 80)
        self.assertEqual(self.rep["verdict"]["key"], "decision_ready")

    def test_full_section_coverage(self):
        self.assertEqual(self.rep["coverage"]["coverage"], 1.0)
        self.assertEqual(self.rep["coverage"]["missing"], [])

    def test_options_come_from_the_table(self):
        self.assertEqual(self.rep["options"]["count"], 4)
        self.assertEqual(self.rep["options"]["method"], "table")
        self.assertEqual(self.rep["options"]["criteria"],
                         ["Cost", "Effort", "Risk", "Reversible"])

    def test_recommendation_traces_to_an_option(self):
        self.assertEqual(self.rep["options"]["traceable_to"], "Migrate to Postgres 16")

    def test_criteria_are_consistent(self):
        self.assertTrue(self.rep["options"]["criteria_consistent"])
        self.assertEqual(self.rep["options"]["missing_cells"], [])

    def test_numbers_owners_and_dates_are_found(self):
        self.assertGreaterEqual(self.rep["metrics"]["number_count"], 10)
        self.assertGreaterEqual(self.rep["metrics"]["owner_count"], 2)
        self.assertGreaterEqual(self.rep["metrics"]["date_count"], 3)

    def test_no_high_severity_findings(self):
        high = [f for f in self.rep["findings"] if f["severity"] == "high"]
        self.assertEqual(high, [])

    def test_weights_sum_to_one(self):
        weights = self.rep["meta"]["weights"]
        self.assertAlmostEqual(sum(weights.values()), 1.0, places=2)

    def test_report_is_json_serialisable(self):
        import json
        json.dumps(self.rep)


class WeakDocumentTests(unittest.TestCase):
    def setUp(self):
        self.rep = engine.analyze(WEAK)

    def test_flags_the_missing_blocks(self):
        found = ids(self.rep)
        for expected in ["no_decision_stated", "no_recommendation", "no_ask",
                         "no_owners", "no_timeline", "hedging"]:
            self.assertIn(expected, found)

    def test_scores_low(self):
        self.assertLess(self.rep["score"], 42)
        self.assertEqual(self.rep["verdict"]["key"], "not_a_decision_doc")

    def test_fix_plan_is_prioritised(self):
        plan = self.rep["fix_plan"]
        self.assertTrue(plan)
        self.assertEqual(plan[0]["rank"], 1)
        priorities = [p["priority"] for p in plan]
        self.assertEqual(priorities, sorted(priorities, reverse=True))

    def test_scaffold_lists_missing_sections(self):
        self.assertIn("Decision statement", self.rep["scaffold"]["missing_required"])
        self.assertIn("The ask", self.rep["scaffold"]["missing_required"])


class RuleTests(unittest.TestCase):
    def test_strawman_options_detected(self):
        rep = engine.analyze(samples.SAMPLES["pricing-proposal"]["text"])
        self.assertIn("strawman_options", ids(rep))
        self.assertGreaterEqual(rep["options"]["asymmetry"], 2.5)

    def test_one_way_without_rollback_is_flagged(self):
        rep = engine.analyze(samples.SAMPLES["payment-processor-rfc"]["text"],
                             stakes="high", reversibility="one_way")
        self.assertIn("no_reversibility", ids(rep))

    def test_high_stakes_without_risks_is_capped(self):
        rep = engine.analyze(samples.SAMPLES["payment-processor-rfc"]["text"],
                             stakes="high", reversibility="one_way")
        caps = [c["axis"] for c in rep["caps"]]
        self.assertTrue(caps)

    def test_placeholders_are_detected(self):
        rep = engine.analyze("Context\n\nWe need to decide about the TBD thing. TODO: ask Dana.\n")
        self.assertIn("placeholder_text", ids(rep))

    def test_jargon_is_detected(self):
        text = ("Context\n\nWe need to decide whether to leverage our core competency to "
                "unpack the low-hanging fruit and move the needle for the ecosystem.\n")
        rep = engine.analyze(text)
        self.assertIn("jargon", ids(rep))

    def test_passive_voice_is_detected(self):
        text = ("Context\n\nThe migration was completed. The budget was approved. "
                "The decision was made by the committee.\n")
        rep = engine.analyze(text)
        self.assertGreaterEqual(rep["metrics"]["passive_count"], 3)

    def test_no_numbers_is_flagged(self):
        sentence = ("We should probably move to a new system because the current one might be "
                    "a bit slow for us in the future and there could be many problems with "
                    "the way that it handles traffic during the busy season. ")
        text = "Context\n\n" + sentence * 6
        rep = engine.analyze(text)
        self.assertIn("no_numbers", ids(rep))

    def test_loaded_option_names_flagged(self):
        text = ("Decision\n\nWe need to decide on the approach.\n\nOptions\n"
                "- Scalable cloud hosting\n- Another approach\n- A third approach\n")
        rep = engine.analyze(text)
        self.assertIn("loaded_option_names", ids(rep))

    def test_status_quo_absence_flagged_for_one_way(self):
        text = ("Decision\n\nWe need to decide whether to move to vendor X.\n\nOptions\n"
                "- Vendor X platform\n- Vendor Y platform\n")
        rep = engine.analyze(text, reversibility="one_way")
        self.assertIn("no_status_quo_option", ids(rep))

    def test_status_quo_presence_is_a_strength(self):
        rep = engine.analyze(STRONG)
        self.assertTrue(any("honest" in s for s in rep["strengths"]))


class ScoringTests(unittest.TestCase):
    def test_high_stakes_shifts_weight_to_decisiveness(self):
        low = engine.compute_weights("low", "two_way")
        high = engine.compute_weights("high", "one_way")
        self.assertGreater(high["decisiveness"], low["decisiveness"])
        self.assertLess(high["clarity"], low["clarity"])

    def test_one_way_shifts_weight_away_from_clarity(self):
        two = engine.compute_weights("medium", "two_way")
        one = engine.compute_weights("medium", "one_way")
        self.assertGreater(one["decisiveness"], two["decisiveness"])

    def test_weights_always_sum_to_one(self):
        for stakes in ["low", "medium", "high"]:
            for rev in ["two_way", "one_way", "unknown"]:
                w = engine.compute_weights(stakes, rev)
                self.assertAlmostEqual(sum(w.values()), 1.0, places=2)

    def test_verdict_bands(self):
        self.assertEqual(engine.verdict_for(90)["key"], "decision_ready")
        self.assertEqual(engine.verdict_for(75)["key"], "mostly_ready")
        self.assertEqual(engine.verdict_for(60)["key"], "needs_revision")
        self.assertEqual(engine.verdict_for(45)["key"], "tight_but_usable")
        self.assertEqual(engine.verdict_for(10)["key"], "not_a_decision_doc")

    def test_caps_are_never_exceeded(self):
        rep = engine.analyze(WEAK)
        for cap in rep["caps"]:
            self.assertLessEqual(rep["axes"][cap["axis"]]["score"], cap["ceiling"])


class ExportTests(unittest.TestCase):
    def test_markdown_export_has_the_essentials(self):
        rep = engine.analyze(STRONG)
        md = engine.to_markdown(rep)
        self.assertIn("# Decision Memo Review", md)
        self.assertIn("Scorecard", md)
        self.assertIn("Findings", md)
        self.assertIn("Options analysis", md)
        self.assertIn("Rewrite scaffold", md)
        self.assertIn(str(rep["score"]), md)

    def test_markdown_export_handles_empty_findings(self):
        rep = engine.analyze(STRONG)
        rep["findings"] = []
        md = engine.to_markdown(rep)
        self.assertIn("No findings", md)


class SampleTests(unittest.TestCase):
    def test_all_samples_analyse(self):
        for sid in samples.SAMPLE_ORDER:
            sample = samples.SAMPLES[sid]
            rep = engine.analyze(sample["text"], doc_type=sample["doc_type"],
                                 stakes=sample["stakes"],
                                 reversibility=sample["reversibility"],
                                 audience=sample["audience"])
            self.assertIsInstance(rep["score"], float)
            self.assertGreaterEqual(rep["score"], 0)
            self.assertLessEqual(rep["score"], 100)
            self.assertIn(rep["verdict"]["key"], [v[1] for v in engine.VERDICTS])

    def test_strong_sample_is_the_best_scoring_sample(self):
        scores = {}
        for sid in samples.SAMPLE_ORDER:
            sample = samples.SAMPLES[sid]
            rep = engine.analyze(sample["text"], doc_type=sample["doc_type"],
                                 stakes=sample["stakes"],
                                 reversibility=sample["reversibility"],
                                 audience=sample["audience"])
            scores[sid] = rep["score"]
        self.assertEqual(max(scores, key=scores.get), "checkout-postgres-memo")

    def test_sample_list_metadata(self):
        listing = samples.list_samples()
        self.assertEqual(len(listing), len(samples.SAMPLE_ORDER))
        for item in listing:
            self.assertIn("blurb", item)
            self.assertGreater(item["words"], 50)


if __name__ == "__main__":
    unittest.main()
