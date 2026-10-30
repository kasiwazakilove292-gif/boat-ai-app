"""Fit an entry-only Plackett-Luce ranking model and evaluate chronologically.

The top-three order likelihood is the product of three conditional softmax
probabilities without replacement. Temperature is selected only on validation
dates. The test block is evaluated before a separate full-data deployment fit.
"""
from collections import defaultdict
from datetime import datetime, timezone
from itertools import permutations
from pathlib import Path
import argparse
import hashlib
import json
import math

import numpy as np

from build_validation import build, read_rows, ENTRY_FIELDS, benchmark

FEATURES = [f"lane_{n}" for n in range(1, 7)] + [
    "national_win_rate", "national_2rate", "local_win_rate",
    "motor_2rate", "average_st", "f_count",
]
# Missing optional values are imputed to the other boats' mean in that race.
# All feature normalization is within-race: no statistics from later races.
SPECS = [
    ("national_win_rate", 0, 10, 2.0, True),
    ("national_2rate", 0, 100, 25.0, False),
    ("local_win_rate", 0, 10, 2.0, False),
    ("motor_2rate", 0, 100, 25.0, False),
    ("average_st", 0, 1, -.05, False),
    ("f_count", 0, 9, 1.0, False),
]
ORDERS = list(permutations(range(6), 3))
ORDER_INDEX = {order: i for i, order in enumerate(ORDERS)}
EPOCHS = 300
L2 = .02
TEMPERATURES = [.7, 1.0, 1.3, 1.6, 2.0]
ALGORITHM = "entry_pl_v1"


def features(rows):
    if (len(rows) != 6 or {int(r["boat_no"]) for r in rows} != set(range(1, 7))
            or len({r["racer_id"] for r in rows}) != 6):
        raise ValueError("6艇の出走表がそろっていません")
    rows = sorted(rows, key=lambda r: int(r["boat_no"]))
    matrix = np.zeros((6, len(FEATURES)), dtype=np.float64)
    matrix[:, :6] = np.eye(6)
    for column, (field, minimum, maximum, scale, required) in enumerate(SPECS, 6):
        values = []
        for row in rows:
            raw = row.get(field, "")
            if raw in ("", "-", None):
                if required:
                    raise ValueError(f"{field}が欠損しています")
                values.append(None)
                continue
            value = float(raw)
            if not math.isfinite(value) or not minimum <= value <= maximum:
                raise ValueError(f"{field}が範囲外です")
            values.append(value)
        present = [v for v in values if v is not None]
        mean = sum(present) / len(present) if present else 0.0
        matrix[:, column] = [(v - mean) / scale if v is not None else 0.0
                             for v in values]
    return matrix


def objective(weights, x, y, l2=L2):
    scores = np.einsum("nbf,f->nb", x, weights)
    remaining = np.ones(scores.shape, dtype=bool)
    gradient = np.zeros(scores.shape)
    losses = np.zeros(len(x))
    row = np.arange(len(x))
    for stage in range(3):
        masked = np.where(remaining, scores, -np.inf)
        maximum = masked.max(axis=1, keepdims=True)
        exp = np.exp(masked - maximum)
        denominator = exp.sum(axis=1, keepdims=True)
        probabilities = exp / denominator
        losses += np.log(denominator[:, 0]) + maximum[:, 0] - scores[row, y[:, stage]]
        gradient += probabilities
        gradient[row, y[:, stage]] -= 1.0
        remaining[row, y[:, stage]] = False
    loss = float(losses.mean() + l2 / 2 * np.dot(weights, weights))
    grad = np.einsum("nb,nbf->f", gradient, x) / len(x) + l2 * weights
    return loss, grad


def fit(x, y, epochs=EPOCHS):
    if len(x) == 0:
        raise ValueError("学習データがありません")
    weights = np.zeros(x.shape[2], dtype=np.float64)
    first = np.zeros_like(weights)
    second = np.zeros_like(weights)
    # Deterministic full-batch Adam: no shuffling or random initialization.
    for step in range(1, epochs + 1):
        _, grad = objective(weights, x, y)
        first = .9 * first + .1 * grad
        second = .999 * second + .001 * grad * grad
        weights -= .04 * (first / (1 - .9 ** step)) / (
            np.sqrt(second / (1 - .999 ** step)) + 1e-8)
    if not np.isfinite(weights).all():
        raise ValueError("学習係数が不正です")
    return weights


def distributions(x, weights, temperature=1.0):
    if not math.isfinite(temperature) or temperature <= 0:
        raise ValueError("温度係数が不正です")
    scores = np.einsum("nbf,f->nb", x, weights) / temperature
    strengths = np.exp(scores - scores.max(axis=1, keepdims=True))
    total = strengths.sum(axis=1)
    result = np.empty((len(x), len(ORDERS)))
    # Summing remaining strengths avoids subtraction cancellation.
    for column, (a, b, c) in enumerate(ORDERS):
        after_a = strengths[:, [n for n in range(6) if n != a]].sum(axis=1)
        after_ab = strengths[:, [n for n in range(6) if n not in (a, b)]].sum(axis=1)
        result[:, column] = (strengths[:, a] / total * strengths[:, b] / after_a
                             * strengths[:, c] / after_ab)
    return result


def true_indices(y):
    return np.array([ORDER_INDEX[tuple(order)] for order in y], dtype=int)


def nll(probabilities, y):
    truth = probabilities[np.arange(len(y)), true_indices(y)]
    return float(-np.log(np.maximum(truth, 1e-300)).mean())


def chronological_split(races):
    days = sorted({r["date"] for r in races})
    if len(days) < 10:
        raise ValueError("時系列検証には10開催日以上必要です")
    first = int(len(days) * .6)
    second = int(len(days) * .8)
    val_start, test_start = days[first], days[second]
    train = [i for i, r in enumerate(races) if r["date"] < val_start]
    validation = [i for i, r in enumerate(races) if val_start <= r["date"] < test_start]
    test = [i for i, r in enumerate(races) if r["date"] >= test_start]
    return train, validation, test


def metrics(probabilities, y, races):
    chosen = probabilities.argmax(axis=1)
    truth = true_indices(y)
    enriched = [{**r, "model": "-".join(str(n + 1) for n in ORDERS[int(p)])}
                for r, p in zip(races, chosen)]
    first_prob = np.zeros((len(races), 6))
    for column, order in enumerate(ORDERS):
        first_prob[:, order[0]] += probabilities[:, column]
    winning_prob = probabilities[np.arange(len(races)), chosen]
    bins = []
    for low, high in [(0, .05), (.05, .1), (.1, .2), (.2, 1.000001)]:
        mask = (winning_prob >= low) & (winning_prob < high)
        count = int(mask.sum())
        bins.append({"low": low, "high": min(high, 1), "races": count,
                     "mean_probability": float(winning_prob[mask].mean()) if count else None,
                     "actual_hit_rate": float((chosen[mask] == truth[mask]).mean()) if count else None})
    brier = (np.square(probabilities).sum(axis=1)
             - 2 * probabilities[np.arange(len(y)), truth] + 1).mean()
    return {
        "model": benchmark(enriched, "model"),
        "lane_order": benchmark(enriched, "lane_order"),
        "national_win_rate": benchmark(enriched, "national_win_rate"),
        "negative_log_likelihood": round(nll(probabilities, y), 6),
        "uniform_negative_log_likelihood": round(math.log(120), 6),
        "brier_score": round(float(brier), 6),
        "first_place_hit_pct": round(float((first_prob.argmax(axis=1) == y[:, 0]).mean() * 100), 2),
        "top5_hit_pct": round(float(np.any(np.argsort(-probabilities, axis=1, kind="stable")[:, :5]
                                            == truth[:, None], axis=1).mean() * 100), 2),
        "calibration": bins,
    }, enriched


def dataset(data_dir):
    audit, races = build(data_dir)
    groups = defaultdict(list)
    for row in read_rows(data_dir / "omura_entries.csv", ENTRY_FIELDS):
        groups[(row["date"], int(row["race_no"]))].append(row)
    usable, matrices, targets = [], [], []
    excluded = 0
    for race in races:
        try:
            matrix = features(groups[(race["date"], race["race"])])
        except (ValueError, TypeError, KeyError):
            excluded += 1
            continue
        usable.append(race)
        matrices.append(matrix)
        targets.append([int(n) - 1 for n in race["trifecta"].split("-")])
    return audit, usable, np.asarray(matrices), np.asarray(targets, dtype=int), excluded


def build_model(data_dir, epochs=EPOCHS, min_training_races=200):
    audit, races, x, y, excluded = dataset(data_dir)
    train, validation, test = chronological_split(races)
    if len(train) < min_training_races:
        raise ValueError(f"学習データ不足: {len(train)}R（最低{min_training_races}R）")
    eval_weights = fit(x[train], y[train], epochs)
    validation_losses = [(nll(distributions(x[validation], eval_weights, t), y[validation]), t)
                         for t in TEMPERATURES]
    _, temperature = min(validation_losses)
    test_probabilities = distributions(x[test], eval_weights, temperature)
    result, test_rows = metrics(test_probabilities, y[test], [races[i] for i in test])
    # The test scores above belong to the frozen evaluation model. The model
    # shipped for strictly later race dates is fitted separately to all rows.
    deploy_weights = fit(x, y, epochs)
    digest_input = {"algorithm": ALGORITHM, "epochs": epochs, "l2": L2,
                    "implementation": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    "features": FEATURES, "temperature_grid": TEMPERATURES,
                    "races": [{"date": r["date"], "race": r["race"],
                               "trifecta": r["trifecta"], "payout_yen": r["payout_yen"],
                               "retrospective": r["entries_retrieved_after_race_day"]} for r in races],
                    "x": x.tolist()}
    digest = hashlib.sha256(json.dumps(digest_input, sort_keys=True,
                                      separators=(",", ":")).encode()).hexdigest()
    def block(indices):
        return {"races": len(indices), "first_date": races[indices[0]]["date"],
                "last_date": races[indices[-1]]["date"]}
    artifact = {
        "schema_version": 1, "algorithm": ALGORITHM,
        "version": ALGORITHM + "_" + digest[:12], "training_data_sha256": digest,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "features": FEATURES, "weights": [round(float(w), 12) for w in deploy_weights],
        "temperature": temperature, "trained_from": races[0]["date"],
        "trained_through": races[-1]["date"], "training_races": len(races),
        "minimum_prediction_date_exclusive": races[-1]["date"],
        "excluded_feature_races": excluded,
        "evaluation": {"train": block(train), "validation": block(validation), "test": block(test),
                       "metrics": result, "temperature_selection": "validation_nll_only",
                       "evaluation_weights": [round(float(w), 12) for w in eval_weights],
                       "deployment_refit": "all_eligible_races_after_test_evaluation",
                       "retrospective_entry_races": sum(races[i]["entries_retrieved_after_race_day"] for i in test),
                       "refunds": "unavailable_assumed_zero"},
        "parity_fixture": {"x": x[-1].tolist(),
                           "top3": "-".join(str(n + 1) for n in ORDERS[int(distributions(x[-1:], deploy_weights, temperature).argmax())]),
                           "probabilities": [round(float(p), 14) for p in distributions(x[-1:], deploy_weights, temperature)[0]]},
    }
    return artifact, test_rows


def write_model(data_dir, artifact):
    output = data_dir / "prediction_model.json"
    if output.exists():
        try:
            old = json.loads(output.read_text(encoding="utf-8"))
            old_time = old.pop("generated_at", None)
            if old_time and old == {k: v for k, v in artifact.items() if k != "generated_at"}:
                artifact["generated_at"] = old_time
        except (ValueError, AttributeError):
            pass
    temp = output.with_suffix(".tmp")
    temp.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temp.replace(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    args = parser.parse_args()
    artifact, _ = build_model(args.data_dir)
    write_model(args.data_dir, artifact)
    print("モデル:", artifact["version"], "学習:", artifact["training_races"], "R")
    print(json.dumps(artifact["evaluation"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
