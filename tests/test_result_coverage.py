from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main

from result_coverage import classify, load_context

TODAY = date(2026, 10, 31)


def void(day="2025-03-13", race=10):
    d = date.fromisoformat(day)
    return {"date": day, "race": str(race), "status": "not_established",
            "source_url": f"https://www1.mbrace.or.jp/od2/K/{d:%Y%m}/k{d:%y%m%d}.lzh",
            "checked_at": "2026-10-31T00:00:00+09:00"}


class CoverageTests(TestCase):
    def test_unmatched_partition_is_complete_and_does_not_guess_cancellation(self):
        keys = [("2025-03-13", 10), ("2026-01-01", 1), ("2026-05-24", 1),
                ("2026-10-31", 1), ("2026-11-01", 1), ("2026-02-01", 1), ("2026-03-01", 1)]
        result = classify(keys, {keys[-1]}, {keys[-2]}, [void()], TODAY, date(2026, 5, 13))
        counts = {c["status"]: c["races"] for c in result["categories"]}
        self.assertEqual(counts, {"official_void": 1, "past_unresolved": 1, "history_pending": 1,
                                  "current_or_future": 2, "invalid_result": 1})
        self.assertEqual(sum(counts.values()), result["total_unmatched"])
        self.assertEqual(sum(d["races"] for d in result["days"]), result["total_unmatched"])
        self.assertEqual(len(result["races"]), 6)

    def test_no_cursor_does_not_label_past_races_as_scheduled_for_collection(self):
        result = classify({("2026-05-24", 1)}, set(), set(), [], TODAY)
        self.assertEqual(result["races"][0]["status"], "past_unresolved")

    def test_invalid_saved_result_wins_over_a_void_marker(self):
        result = classify({("2025-03-13", 10)}, set(), {("2025-03-13", 10)}, [void()], TODAY)
        self.assertEqual(result["races"][0]["status"], "invalid_result")

    def test_old_today_bucket_becomes_past_on_next_jst_day(self):
        key = {("2026-10-31", 1)}
        before = classify(key, set(), set(), [], TODAY)
        after = classify(key, set(), set(), [], date(2026, 11, 1))
        self.assertEqual(before["races"][0]["status"], "current_or_future")
        self.assertEqual(after["races"][0]["status"], "past_unresolved")

    def test_void_marker_requires_matching_official_source_and_no_duplicates(self):
        for changes in [{"status": "unknown"}, {"source_url": "https://example.com"},
                        {"source_url": "https://www1.mbrace.or.jp/od2/K/202503/k250314.lzh"},
                        {"race": "13"}, {"checked_at": "2026-10-31T00:00:00"}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                classify({("2025-03-13", 10)}, set(), set(), [{**void(), **changes}], TODAY)
        with self.assertRaises(ValueError):
            classify(set(), set(), set(), [void(), void()], TODAY)

    def test_valid_result_and_void_cannot_both_be_accepted(self):
        with self.assertRaises(ValueError):
            classify({("2025-03-13", 10)}, {("2025-03-13", 10)}, set(), [void()], TODAY)

    def test_missing_optional_metadata_is_supported_but_bad_cursor_fails(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            self.assertEqual(load_context(root), (None, []))
            (root / "history_cursor.txt").write_text("invalid date")
            with self.assertRaises(ValueError):
                load_context(root)


if __name__ == "__main__":
    main()
