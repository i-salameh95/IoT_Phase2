"""
ML Training Report Tool
Run from project root (backend container):

  python backend/tools/ml_report.py --cycles 2000 --train

Purpose:
- Provide visibility into how many per-cycle samples exist
- Show class distribution (normal/warning/critical)
- Optionally train models and print evaluation report

Notes:
- This project uses weak supervision: labels are derived from clinical thresholds.
- Outliers are NOT dropped by default; emergencies are preserved and tagged.
"""
import argparse
from collections import Counter

from app.core.mongodb_client import mongodb_service
from app.services.ml_model_service import ml_model_service, LABELS, FEATURES


def main():
    parser = argparse.ArgumentParser(description="ML dataset summary + optional training report")
    parser.add_argument("--patient", type=str, default=None, help="Patient ID (e.g. P001) or omit for all")
    parser.add_argument("--per_measurement_limit", type=int, default=2000, help="Max readings per measurement to pull")
    parser.add_argument("--train", action="store_true", help="Train models and print classification report")
    args = parser.parse_args()

    if not mongodb_service.ensure_available():
        print("MongoDB unavailable. ML report requires MongoDB (CSV fallback does not store tags reliably).")
        return

    x, y = ml_model_service.fetch_training_data(
        patient_id=args.patient,
        per_measurement_limit=args.per_measurement_limit
    )

    print("========================================")
    print("ML DATASET SUMMARY")
    print("========================================")
    print(f"Patient filter: {args.patient or 'ALL'}")
    print(f"Samples (per-cycle): {x.shape[0]}")
    print(f"Features: {x.shape[1]} ({', '.join(FEATURES)})")

    if x.shape[0] == 0:
        print("\nNo per-cycle samples found. Run simulation cycles first.")
        return

    counts = Counter(y.tolist())
    print("\nClass distribution:")
    for idx, label in enumerate(LABELS):
        print(f"  {label:8s}: {counts.get(idx, 0)}")

    if args.train:
        res = ml_model_service.train_models(patient_id=args.patient)
        print("\n========================================")
        print("TRAINING RESULT")
        print("========================================")
        print(f"ok={res.ok} samples={res.samples} algorithm={res.algorithm} accuracy={res.accuracy}")
        if res.message:
            print(res.message)
        if res.report:
            print("\nClassification report:\n")
            print(res.report)
        if res.confusion:
            print("\nConfusion matrix (rows=true, cols=pred):")
            for row in res.confusion:
                print("  ", row)


if __name__ == "__main__":
    main()
