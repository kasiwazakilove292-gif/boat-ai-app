from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import csv
import json
import unittest

from build_validation import build, write_outputs, ENTRY_FIELDS, RESULT_FIELDS, BEFORE_FIELDS


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.entries = []
        self.results = []
        self.before = []

    def race(self, day="2026-10-01", race=1, outcome="1-2-3", payout=1230):
        self.entries.extend({
            "date": day, "venue": "24", "race_no": str(race), "boat_no": str(n),
            "racer_id": str(4000+n), "racer_name": f"選手{n}",
            "national_win_rate": str(7-n/10),
            "collected_at": "2026-10-31T01:00:00+09:00",
        } for n in range(1, 7))
        self.results.append({"date": day, "race": str(race),
                             "trifecta": outcome, "payout_yen": str(payout)})

    def snapshots(self, captured="2026-10-01T14:50:00+09:00", **changes):
        self.before.extend({
            "date": "2026-10-01", "venue": "24", "race_no": "1", "boat_no": str(n),
            "racer_name": f"選手{n}", "exhibition_status": "published",
            "exhibition_time": "6.90", "deadline_at": "2026-10-01T15:00:00+09:00",
            "collected_at": captured, "captured_before_deadline": "true", **changes,
        } for n in range(1, 7))

    def write(self, name, rows, fields):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=sorted(fields))
            writer.writeheader()
            writer.writerows(rows)

    def run_build(self):
        self.write("omura_entries.csv", self.entries, ENTRY_FIELDS)
        self.write("omura_results.csv", self.results, RESULT_FIELDS)
        if self.before:
            self.write("beforeinfo/2026-10-01.csv", self.before, BEFORE_FIELDS)
        return build(self.root)

    def test_payout_roi_and_retrospective_flag(self):
        self.race(payout=1230)
        summary, races = self.run_build()
        self.assertEqual(summary["benchmarks"][0]["all"]["roi_pct"], 1230)
        self.assertEqual(summary["benchmarks"][0]["all"]["net_yen"], 1130)
        self.assertEqual(summary["data"]["retrospective_entry_races"], 1)
        self.assertEqual(races[0]["national_win_rate"], "1-2-3")

    def test_duplicate_results_are_not_double_counted_or_chosen(self):
        self.race()
        self.results.append(dict(self.results[0], trifecta="4-5-6"))
        summary, races = self.run_build()
        self.assertEqual(races, [])
        self.assertEqual(summary["issues"]["duplicate_or_invalid_result_races"], 1)

    def test_invalid_duplicate_result_taints_valid_row(self):
        self.race()
        self.results.append(dict(self.results[0], payout_yen="NaN"))
        summary, races = self.run_build()
        self.assertEqual(races, [])
        self.assertEqual(summary["issues"]["invalid_result_rows"], 1)

    def test_six_rows_with_duplicate_boat_or_racer_are_incomplete(self):
        for field in ("boat_no", "racer_id"):
            with self.subTest(field=field):
                self.entries = []
                self.results = []
                self.race()
                self.entries[-1][field] = self.entries[0][field]
                summary, races = self.run_build()
                self.assertEqual(races, [])
                self.assertEqual(summary["data"]["result_races_without_complete_entries"], 1)

    def test_extra_invalid_entry_does_not_leave_a_complete_race(self):
        self.race()
        self.entries.append(dict(self.entries[0], boat_no="9"))
        summary, races = self.run_build()
        self.assertEqual(races, [])
        self.assertEqual(summary["issues"]["invalid_entry_rows"], 1)

    def test_missing_or_nan_rates_exclude_both_rules_equally(self):
        for rate in ("", "NaN", "inf", "-1"):
            with self.subTest(rate=rate):
                self.entries = []
                self.results = []
                self.race()
                self.entries[0]["national_win_rate"] = rate
                summary, _ = self.run_build()
                self.assertEqual(summary["data"]["joined_races_without_valid_rates"], 1)
                self.assertTrue(all(b["all"]["races"] == 0 for b in summary["benchmarks"]))

    def test_tied_rates_use_boat_order(self):
        self.race()
        for row in self.entries:
            row["national_win_rate"] = "6.00"
        self.entries.reverse()
        _, races = self.run_build()
        self.assertEqual(races[0]["national_win_rate"], "1-2-3")

    def test_archive_retains_valid_predeadline_data_despite_later_snapshot(self):
        self.race()
        self.snapshots()
        # Later current values must not erase genuine archived snapshots.
        later = [dict(r, collected_at="2026-10-01T16:00:00+09:00",
                      captured_before_deadline="false") for r in self.before]
        self.write("omura_beforeinfo.csv", later, BEFORE_FIELDS)
        summary, _ = self.run_build()
        self.assertEqual(summary["data"]["predeadline_exhibition_races"], 1)

    def test_untrusted_true_flag_cannot_make_late_or_exact_deadline_valid(self):
        self.race()
        for captured in ("2026-10-01T15:00:00+09:00", "2026-10-01T16:00:00+09:00"):
            with self.subTest(captured=captured):
                self.before = []
                self.snapshots(captured=captured)
                summary, _ = self.run_build()
                self.assertEqual(summary["data"]["predeadline_exhibition_races"], 0)

    def test_identity_change_or_missing_boat_does_not_count_full_exhibition(self):
        self.race()
        self.snapshots()
        self.before[0]["racer_name"] = "交代選手"
        summary, _ = self.run_build()
        self.assertEqual(summary["data"]["predeadline_exhibition_races"], 0)
        self.before.pop()
        summary, _ = self.run_build()
        self.assertEqual(summary["data"]["predeadline_exhibition_races"], 0)

    def test_recent_window_uses_whole_dates(self):
        for n in range(1, 11):
            self.race(day=date(2026, 10, n).isoformat())
        self.race(day="2026-10-09", race=2)
        summary, _ = self.run_build()
        self.assertEqual(summary["data"]["recent_start"], "2026-10-09")
        self.assertEqual(summary["benchmarks"][0]["recent"]["races"], 3)

    def test_empty_data_is_explicit_and_repeat_build_does_not_churn(self):
        summary, races = self.run_build()
        self.assertIsNone(summary["benchmarks"][0]["all"]["roi_pct"])
        write_outputs(self.root, summary, races)
        original = (self.root / "validation_summary.json").read_bytes()
        newer, rows = build(self.root)
        newer["generated_at"] = "2099-01-01T00:00:00+00:00"
        write_outputs(self.root, newer, rows)
        self.assertEqual((self.root / "validation_summary.json").read_bytes(), original)

    def test_bad_schema_aborts_instead_of_overwriting_previous_summary(self):
        self.write("omura_entries.csv", [], {"wrong"})
        self.write("omura_results.csv", [], RESULT_FIELDS)
        with self.assertRaises(ValueError):
            build(self.root)


if __name__ == "__main__":
    unittest.main()
