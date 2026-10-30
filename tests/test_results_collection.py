from datetime import date
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
from unittest.mock import patch
from urllib.error import HTTPError
import csv

from collect_data import (parse_results, collect_one, read_saved, write_saved,
                          archive_url, RESULT_FIELDS, VOID_FIELDS)

DAY = date(2026, 5, 24)


def sample(void=(), venue="大　村", day="2026/ 5/24"):
    header = f"   第 1日          {day}                    ボートレース{venue}\n"
    return header + "\n".join(f" {n:2}R  中止" if n in void
                              else f" {n:2}R  1-2-3  1,230   1-2-3  560"
                              for n in range(1, 13)) + "\n"


class ResultParserTests(TestCase):
    def test_twelve_results_and_comma_dividend(self):
        rows, voids = parse_results(sample(), DAY)
        self.assertEqual(len(rows), 12)
        self.assertEqual(rows[0], {"date": "2026-05-24", "race": 1,
                                   "trifecta": "1-2-3", "payout_yen": 1230})
        self.assertEqual(voids, [])

    def test_only_explicit_voids_fill_the_twelve_races(self):
        rows, voids = parse_results(sample(void=(10, 12)).replace("10R  中止", "10R  不成立"), DAY)
        self.assertEqual(len(rows), 10)
        self.assertEqual([r["status"] for r in voids], ["not_established", "cancelled"])

    def test_no_meeting_is_distinct_from_unparseable_archive(self):
        self.assertEqual(parse_results(sample(venue="唐　津"), DAY), ([], []))
        with self.assertRaises(ValueError):
            parse_results("HTML error page", DAY)

    def test_wrong_day_rejected_even_when_no_omura_meeting(self):
        for venue in ("大　村", "唐　津"):
            with self.subTest(venue=venue), self.assertRaises(ValueError):
                parse_results(sample(venue=venue, day="2026/ 5/25"), DAY)

    def test_other_venues_cannot_fill_missing_omura_races(self):
        text = sample().replace(" 12R  1-2-3  1,230   1-2-3  560", "") + sample(venue="唐　津")
        with self.assertRaises(ValueError):
            parse_results(text, DAY)

    def test_partial_duplicate_out_of_range_or_conflicting_results_fail(self):
        for text in [sample().replace(" 12R", " 13R"),
                     sample() + " 1R  1-2-3  100\n",
                     sample() + " 1R  中止\n",
                     sample().replace("1-2-3", "1-1-3"),
                     sample().replace("1,230", "0"),
                     sample() + sample()]:
            with self.subTest(text=text[-70:]), self.assertRaises(ValueError):
                parse_results(text, DAY)


class CollectionTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.results = {}
        self.voids = {}

    def extract(self, command, check):
        directory = Path(command[-1])
        (directory / "K260524.TXT").write_bytes(sample(void=(12,)).encode("cp932"))

    def collect(self):
        with patch("collect_data.urllib.request.urlopen", return_value=BytesIO(b"archive")), \
             patch("collect_data.subprocess.run", side_effect=self.extract):
            return collect_one(DAY, self.root, self.results, self.voids)

    def test_success_saves_official_void_separately_and_repeat_is_stable(self):
        self.assertEqual(self.collect(), 11)
        self.assertEqual(len(self.results), 11)
        self.assertEqual(self.voids[("2026-05-24", 12)]["source_url"], archive_url(DAY))
        previous = (self.root / "omura_void_races.csv").read_bytes()
        self.collect()
        self.assertEqual((self.root / "omura_void_races.csv").read_bytes(), previous)

    def test_unpublished_archive_fails_without_erasing_previous_verified_day(self):
        self.collect()
        previous = (self.root / "omura_results.csv").read_bytes()
        error = HTTPError(archive_url(DAY), 404, "not published", None, None)
        with patch("collect_data.urllib.request.urlopen", side_effect=error):
            with self.assertRaisesRegex(RuntimeError, "収集位置を進めず"):
                collect_one(DAY, self.root, self.results, self.voids)
        self.assertEqual((self.root / "omura_results.csv").read_bytes(), previous)
        self.assertEqual(len(self.results), 11)

    def test_parsing_failure_preserves_previous_file_and_in_memory_data(self):
        self.collect()
        previous = (self.root / "omura_results.csv").read_bytes()
        with patch("collect_data.urllib.request.urlopen", return_value=BytesIO(b"archive")), \
             patch("collect_data.subprocess.run", side_effect=self.extract), \
             patch("collect_data.parse_results", side_effect=ValueError("invalid")):
            with self.assertRaises(ValueError):
                collect_one(DAY, self.root, self.results, self.voids)
        self.assertEqual((self.root / "omura_results.csv").read_bytes(), previous)
        self.assertEqual(len(self.results), 11)

    def test_conflicting_existing_result_is_not_silently_deleted(self):
        self.results[("2026-05-24", 12)] = {"date": "2026-05-24", "race": 12,
                                            "trifecta": "1-2-3", "payout_yen": 100}
        with self.assertRaisesRegex(ValueError, "矛盾"):
            self.collect()
        self.assertFalse((self.root / "omura_results.csv").exists())
        self.assertEqual(len(self.results), 1)

    def test_duplicate_saved_results_are_not_silently_collapsed(self):
        path = self.root / "omura_results.csv"
        path.write_text("date,race,trifecta,payout_yen\n2026-05-24,1,1-2-3,100\n2026-05-24,1,4-5-6,200\n")
        with self.assertRaisesRegex(ValueError, "重複"):
            read_saved(path, RESULT_FIELDS)


if __name__ == "__main__":
    main()
