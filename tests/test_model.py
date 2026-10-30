from pathlib import Path
from tempfile import TemporaryDirectory
import json
import subprocess
import unittest

import numpy as np

from train_model import (FEATURES, SPECS, ORDERS, features, fit, objective,
                         distributions, chronological_split, metrics, write_model)


def rows(**overrides):
    return [{"boat_no": str(n), "racer_id": str(4000+n),
             "national_win_rate": str(4+n*.2), "national_2rate": str(30+n),
             "local_win_rate": str(3+n*.3), "motor_2rate": str(20+n*2),
             "average_st": str(.12+n*.01), "f_count": str(n % 2), **overrides}
            for n in range(1, 7)]


class ModelTests(unittest.TestCase):
    def test_feature_values_and_optional_missing_imputation(self):
        r = rows()
        r[0]["average_st"] = ""
        x = features(r)
        self.assertEqual(x.shape, (6, 12))
        np.testing.assert_allclose(x[:, :6], np.eye(6))
        np.testing.assert_allclose(x[:, 6:].sum(axis=0), np.zeros(6), atol=1e-12)
        self.assertEqual(x[0, 10], 0)
        self.assertGreater(x[1, 10], x[5, 10])  # Faster ST has a larger feature.

    def test_features_do_not_depend_on_input_order(self):
        np.testing.assert_allclose(features(rows()), features(list(reversed(rows()))))

    def test_python_and_browser_use_identical_feature_values(self):
        for missing in (False, True):
            inputs = rows()
            if missing:
                inputs[0]["average_st"] = ""
                inputs[-1]["local_win_rate"] = "-"
            script = "const m=require('./prediction-model.js');process.stdout.write(JSON.stringify(m.matrix(JSON.parse(process.argv[1]))));"
            result = subprocess.check_output(["node", "-e", script, json.dumps(inputs)],
                                             cwd=Path(__file__).resolve().parents[1], text=True)
            np.testing.assert_allclose(features(inputs), json.loads(result), atol=1e-12)

    def test_missing_required_invalid_numbers_and_duplicate_boats_rejected(self):
        for changes in [{"national_win_rate": ""}, {"national_win_rate": "NaN"},
                        {"average_st": "Infinity"}, {"motor_2rate": "101"},
                        {"boat_no": "1"}, {"racer_id": "4001"}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                features(rows(**changes))

    def test_analytic_gradient_matches_finite_difference(self):
        rng = np.random.default_rng(53)
        x = rng.normal(size=(4, 6, 12))
        y = np.array([[0, 1, 2], [5, 3, 1], [2, 0, 4], [1, 4, 5]])
        weights = rng.normal(size=12) * .2
        _, gradient = objective(weights, x, y)
        expected = []
        for i in range(12):
            plus, minus = weights.copy(), weights.copy()
            plus[i] += 1e-6
            minus[i] -= 1e-6
            expected.append((objective(plus, x, y)[0] - objective(minus, x, y)[0]) / 2e-6)
        np.testing.assert_allclose(gradient, expected, atol=1e-8)

    def test_probability_mass_and_uniform_model(self):
        x = np.array([features(rows()), features(rows())])
        p = distributions(x, np.zeros(12))
        self.assertEqual(p.shape, (2, 120))
        np.testing.assert_allclose(p, np.full((2, 120), 1/120), atol=1e-14)
        np.testing.assert_allclose(p.sum(axis=1), [1, 1])

    def test_optimizer_learns_from_training_targets_and_is_deterministic(self):
        x = np.array([features(rows()) for _ in range(10)])
        y = np.array([[0, 1, 2] for _ in range(10)])
        before = objective(np.zeros(12), x, y)[0]
        weights = fit(x, y, epochs=40)
        self.assertLess(objective(weights, x, y)[0], before)
        np.testing.assert_array_equal(weights, fit(x, y, epochs=40))

    def test_split_never_divides_a_date_and_future_targets_do_not_enter_fit(self):
        races = [{"date": f"2026-01-{n:02d}", "race": race}
                 for n in range(1, 11) for race in range(1, 3)]
        train, val, test = chronological_split(races)
        self.assertEqual((len(train), len(val), len(test)), (12, 4, 4))
        self.assertLess(max(races[i]["date"] for i in train), min(races[i]["date"] for i in val))
        self.assertLess(max(races[i]["date"] for i in val), min(races[i]["date"] for i in test))
        x = np.array([features(rows()) for _ in races])
        y = np.array([[0, 1, 2] for _ in races])
        original = fit(x[train], y[train], epochs=10)
        y[val + test] = [5, 4, 3]
        np.testing.assert_array_equal(original, fit(x[train], y[train], epochs=10))

    def test_test_payout_uses_official_dividend_and_same_cohort(self):
        p = np.zeros((2, 120))
        p[:, ORDERS.index((0, 1, 2))] = 1
        y = np.array([[0, 1, 2], [5, 4, 3]])
        races = [{"date": "2026-01-01", "race": i+1,
                  "trifecta": "1-2-3" if i == 0 else "6-5-4",
                  "payout_yen": 1230, "lane_order": "1-2-3", "national_win_rate": "6-5-4"}
                 for i in range(2)]
        result, _ = metrics(p, y, races)
        self.assertEqual(result["model"]["payout_yen"], 1230)
        self.assertEqual(result["model"]["roi_pct"], 615)
        self.assertTrue(all(result[k]["races"] == 2 for k in ["model", "lane_order", "national_win_rate"]))

    def test_unchanged_model_does_not_change_timestamp(self):
        with TemporaryDirectory() as directory:
            path = Path(directory)
            write_model(path, {"generated_at": "2026-01-01", "weights": [1, 2]})
            write_model(path, {"generated_at": "2099-01-01", "weights": [1, 2]})
            self.assertEqual(json.loads((path / "prediction_model.json").read_text())["generated_at"], "2026-01-01")


if __name__ == "__main__":
    unittest.main()
