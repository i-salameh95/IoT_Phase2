#!/usr/bin/env python3
"""
Train and compare ML models using per-cycle DB data, then write report artifacts.

Outputs:
  - doc/ml_reports/ml_comparison.json
  - doc/ml_reports/model_comparison.png
  - doc/ml_reports/best_confusion_matrix.png
  - doc/ml_reports/ml_summary.txt
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# Ensure backend/ is on sys.path so `import app` works.
BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.services.ml_model_service import health_ml_model
from app.core.sensor_config import SENSOR_NORMAL_RANGES
from app.core.mongodb_client import mongodb_service


def _save_comparison_chart(results: list[dict], output_path: Path) -> None:
    names = [r.get("algorithm_name", r.get("algorithm", "unknown")) for r in results]
    scores = [float(r.get("scores", {}).get("test_score") or 0.0) for r in results]

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.bar(range(len(names)), scores, color="#2563eb")
    ax.set_xticks(range(len(names)))
    ax.set_xticklabels(names, rotation=30, ha="right")
    ax.set_ylim(0, 1)
    ax.set_ylabel("Test accuracy")
    ax.set_title("Model Comparison (Test Accuracy)")
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def _save_confusion_matrix(best: dict, output_path: Path) -> None:
    cm = best.get("confusion_matrix", {}).get("matrix", [])
    labels = best.get("confusion_matrix", {}).get("labels", [])
    if not cm:
        return

    arr = np.array(cm)
    fig, ax = plt.subplots(figsize=(6, 5))
    im = ax.imshow(arr, cmap="Blues")

    ax.set_xticks(range(len(labels)))
    ax.set_yticks(range(len(labels)))
    ax.set_xticklabels(labels)
    ax.set_yticklabels(labels)
    ax.set_xlabel("Predicted")
    ax.set_ylabel("Actual")
    ax.set_title(f"Confusion Matrix - {best.get('algorithm_name', best.get('algorithm', ''))}")

    for (i, j), val in np.ndenumerate(arr):
        ax.text(j, i, str(val), ha="center", va="center", color="black")

    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def _choose_extreme_value(measurement: str, values: list[float]) -> float:
    if not values:
        return float("nan")
    if len(values) == 1:
        return float(values[0])

    normal_range = SENSOR_NORMAL_RANGES.get(measurement)
    if not normal_range:
        return float(np.mean(values))

    mid = (normal_range[0] + normal_range[1]) / 2.0
    v_min = float(min(values))
    v_max = float(max(values))
    return v_min if abs(v_min - mid) >= abs(v_max - mid) else v_max


def _normalize_patient_id(device_id: str) -> str:
    if not device_id:
        return "unknown"
    parts = str(device_id).split("_")
    if len(parts) >= 2 and parts[0] == "patient":
        digits = parts[1]
        return f"P{digits}" if digits.isdigit() else parts[1]
    return "unknown"


def _load_actuator_labels() -> dict[tuple[str, int], int]:
    if not mongodb_service.ensure_available() or mongodb_service.actuator_collection is None:
        return {}

    cursor = mongodb_service.actuator_collection.find(
        {"$or": [{"tag_severity": {"$in": ["critical", "warning"]}}, {"tags.severity": {"$in": ["critical", "warning"]}}]},
        {"timestamp": 1, "tags": 1, "tag_severity": 1, "tag_patient_id": 1, "device_id": 1},
    )

    labels = {}
    for doc in cursor:
        ts = doc.get("timestamp")
        if ts is None:
            continue
        tags = doc.get("tags") or {}
        pid = doc.get("tag_patient_id") or tags.get("patient_id") or _normalize_patient_id(doc.get("device_id"))
        severity = doc.get("tag_severity") or tags.get("severity")
        label = 2 if severity == "critical" else 1
        key = (pid, int(ts))
        if label == 2 or key not in labels:
            labels[key] = label
    return labels


def _fetch_per_cycle_training_data(max_docs: int = 200000, min_samples: int = 30):
    if not mongodb_service.ensure_available() or mongodb_service.collection is None:
        return None, {"reason": "mongodb_unavailable"}

    projection = {
        "measurement": 1,
        "value": 1,
        "timestamp": 1,
        "device_id": 1,
        "tags": 1,
    }

    cursor = mongodb_service.collection.find(
        {"measurement": {"$in": health_ml_model.feature_names}},
        projection,
    ).sort("timestamp", -1)

    if max_docs:
        cursor = cursor.limit(max_docs)

    docs = list(cursor)
    if not docs:
        return None, {"reason": "no_docs"}

    docs.reverse()
    grouped = defaultdict(lambda: defaultdict(list))
    for doc in docs:
        ts = doc.get("timestamp")
        if ts is None:
            continue
        pid = (doc.get("tags") or {}).get("patient_id") or health_ml_model._infer_patient_id(doc.get("device_id", ""))
        grouped[(pid, int(ts))][doc.get("measurement")].append(float(doc.get("value", 0.0)))

    actuator_labels = _load_actuator_labels()
    actuator_label_hits = 0
    samples = []
    for (pid, ts), meas_map in grouped.items():
        sample = {}
        for f in health_ml_model.feature_names:
            vals = meas_map.get(f, [])
            sample[f] = _choose_extreme_value(f, vals)

        core = [
            sample.get("heart_rate", np.nan),
            sample.get("blood_pressure_systolic", np.nan),
            sample.get("blood_pressure_diastolic", np.nan),
            sample.get("body_temperature", np.nan),
            sample.get("oxygen_saturation", np.nan),
            sample.get("glucose_level", np.nan),
        ]
        if any(np.isnan(core)):
            continue

        label = actuator_labels.get((pid, ts))
        if label is None:
            label = int(health_ml_model._determine_health_status(*core))
        else:
            actuator_label_hits += 1

        sample["health_status_label"] = label
        samples.append(sample)

    if len(samples) < min_samples:
        return None, {"reason": "insufficient_samples", "samples": len(samples)}

    df = pd.DataFrame(samples)
    df = df[health_ml_model.feature_names + ["health_status_label"]].copy()
    df = df.fillna(0.0)

    label_counts = df["health_status_label"].value_counts().to_dict()
    if len(label_counts) < 2:
        return None, {
            "reason": "single_class",
            "label_counts": label_counts,
            "samples": len(df),
        }

    return df, {
        "docs": len(docs),
        "cycles": len(grouped),
        "samples": len(df),
        "label_counts": label_counts,
        "actuator_label_hits": actuator_label_hits,
    }


def main() -> int:
    training_data, data_meta = _fetch_per_cycle_training_data()
    if training_data is None:
        print(f"Per-cycle data unavailable. Details: {data_meta}")
        return 1

    label_counts = data_meta.get("label_counts", {})
    min_class = min(label_counts.values()) if label_counts else 0
    cv_folds = max(2, min(5, int(min_class))) if min_class else 2
    result = health_ml_model.compare_models(training_data=training_data, cv_folds=cv_folds)
    data_meta = {"source": "per_cycle_mongodb", "cv_folds": cv_folds, **(data_meta or {})}
    if result.get("status") != "success":
        print(f"Compare failed: {result.get('message', 'unknown error')}")
        return 1

    output_dir = REPO_ROOT / "doc" / "ml_reports"
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "ml_comparison.json"
    json_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    comparison = [r for r in result.get("comparison", []) if r.get("status") == "success"]
    if not comparison:
        print("No successful model results to plot.")
        return 1

    comparison.sort(key=lambda r: float(r.get("scores", {}).get("test_score") or 0.0), reverse=True)

    _save_comparison_chart(comparison, output_dir / "model_comparison.png")

    best = comparison[0]
    _save_confusion_matrix(best, output_dir / "best_confusion_matrix.png")

    summary_lines = [
        f"Data source: {data_meta.get('source')}",
        f"Data meta: {data_meta}",
        f"Best algorithm: {best.get('algorithm_name', best.get('algorithm'))}",
        f"Best test score: {best.get('scores', {}).get('test_score')}",
        f"Samples: {best.get('samples', {})}",
        f"Split: {best.get('split', {})}",
        f"Metrics: {best.get('metrics', {})}",
    ]
    (output_dir / "ml_summary.txt").write_text("\n".join(summary_lines), encoding="utf-8")

    print(f"Saved reports to: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
