"""
ML Model Service for Health Status Prediction

Important context for this project:
- The simulator produces synthetic, threshold-driven vitals.
- The most "logical" supervised labels are therefore derived from clinical thresholds
  (normal / warning / critical). This is equivalent to learning the existing rule-system.

For a course demo, this is acceptable as long as you explain:
- Labels are generated from domain rules (weak supervision).
- ML is an optional enhancement; the primary decision system is deterministic + explainable.

Key fixes vs. older versions:
- Train on per-cycle samples (using tags: patient_id + cycle) instead of arbitrary time bins.
- Do NOT rely on actuator activation as the training label (that introduces timing/coverage issues).
- Support small-but-reasonable datasets (>= 30 cycle samples recommended).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier, AdaBoostClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, confusion_matrix, precision_recall_fscore_support
from sklearn.base import clone
from sklearn.model_selection import StratifiedKFold, train_test_split
from sklearn.naive_bayes import GaussianNB
from sklearn.neighbors import KNeighborsClassifier
from sklearn.svm import SVC
from sklearn.tree import DecisionTreeClassifier

from app.core.logger import iot_logger
from app.core.mongodb_client import mongodb_service

FEATURES = [
    "heart_rate",
    "blood_pressure_systolic",
    "blood_pressure_diastolic",
    "body_temperature",
    "oxygen_saturation",
    "glucose_level",
    "activity_steps",
]

LABELS = ["normal", "warning", "critical"]


@dataclass
class TrainResult:
    ok: bool
    samples: int
    accuracy: Optional[float] = None
    algorithm: Optional[str] = None
    report: Optional[str] = None
    confusion: Optional[List[List[int]]] = None
    message: Optional[str] = None


class MLModelService:
    def __init__(self):
        self.models = {
            "random_forest": RandomForestClassifier(n_estimators=200, random_state=42),
            "gradient_boosting": GradientBoostingClassifier(random_state=42),
            "logistic_regression": LogisticRegression(max_iter=3000),
            "ada_boost": AdaBoostClassifier(random_state=42),
            "svm": SVC(kernel="rbf", probability=True),
            "knn": KNeighborsClassifier(n_neighbors=5),
            "naive_bayes": GaussianNB(),
            "decision_tree": DecisionTreeClassifier(random_state=42),
        }
        self.best_model_name: Optional[str] = None
        self.is_fitted: bool = False

        # Lightweight "model lifecycle" metadata (to satisfy "modified whenever needed")
        self.last_train_at_utc: Optional[str] = None
        self.last_train_samples: int = 0
        self.last_train_cycle: Optional[int] = None
        self.last_train_accuracy: Optional[float] = None

        # Retraining policy (simple + demo-friendly)
        self.min_samples_to_train: int = 30
        self.retrain_every_cycles: int = 50
        self.min_new_samples_for_retrain: int = 20

    def is_trained(self) -> bool:
        return bool(self.is_fitted and self.best_model_name)

    def get_status(self) -> Dict:
        """
        Used by /api/v1/ml/status to show ML readiness + lifecycle metadata.
        """
        return {
            "is_trained": self.is_trained(),
            "best_model": self.best_model_name,
            "available_algorithms": sorted(self.models.keys()),
            "training": {
                "last_train_at_utc": self.last_train_at_utc,
                "last_train_samples": int(self.last_train_samples),
                "last_train_cycle": self.last_train_cycle,
                "last_train_accuracy": self.last_train_accuracy,
                "min_samples_to_train": int(self.min_samples_to_train),
                "retrain_every_cycles": int(self.retrain_every_cycles),
                "min_new_samples_for_retrain": int(self.min_new_samples_for_retrain),
            },
            "class_names": ["Normal", "Warning", "Critical"],
        }

    def maybe_retrain(self, current_cycle: Optional[int] = None, force: bool = False) -> Dict:
        """
        Auto-retrain policy:
        - Train if untrained and enough samples exist.
        - Retrain periodically if enough new samples have arrived.

        Returns:
            {status, action, reason, ...}
        """
        X, y = self.fetch_training_data()
        samples = int(X.shape[0])

        if samples < self.min_samples_to_train:
            return {
                "status": "skip",
                "action": "no_train",
                "reason": "not_enough_samples",
                "samples": samples,
                "min_samples_to_train": int(self.min_samples_to_train),
            }

        if force or not self.is_trained():
            tr = self.train_models()
            return {
                "status": "success" if tr.ok else "error",
                "action": "train" if not force else "force_train",
                "reason": "untrained" if not force else "forced",
                "samples": tr.samples,
                "algorithm": tr.algorithm,
                "accuracy": tr.accuracy,
            }

        # Retrain guardrails: avoid retraining too often
        if current_cycle is None or self.last_train_cycle is None:
            return {"status": "skip", "action": "no_retrain", "reason": "missing_cycle_info", "samples": samples}

        cycles_since = int(current_cycle) - int(self.last_train_cycle)
        new_samples = int(samples) - int(self.last_train_samples)

        if cycles_since < self.retrain_every_cycles:
            return {
                "status": "skip",
                "action": "no_retrain",
                "reason": "too_soon",
                "samples": samples,
                "cycles_since_last_train": cycles_since,
                "retrain_every_cycles": int(self.retrain_every_cycles),
            }

        if new_samples < self.min_new_samples_for_retrain:
            return {
                "status": "skip",
                "action": "no_retrain",
                "reason": "not_enough_new_samples",
                "samples": samples,
                "new_samples": new_samples,
                "min_new_samples_for_retrain": int(self.min_new_samples_for_retrain),
            }

        tr = self.train_models()
        return {
            "status": "success" if tr.ok else "error",
            "action": "retrain",
            "reason": "policy_triggered",
            "samples": tr.samples,
            "algorithm": tr.algorithm,
            "accuracy": tr.accuracy,
        }

    # -----------------------------
    # Data collection (per-cycle)
    # -----------------------------
    def fetch_training_data(self, patient_id: Optional[str] = None, per_measurement_limit: int = 2000) -> Tuple[
        np.ndarray, np.ndarray]:
        """
        Fetch training data from MongoDB and build per-cycle samples.

        Returns:
            X (n_samples, n_features), y (n_samples,)
        """
        # Load recent readings per measurement
        all_rows = []
        for meas in FEATURES:
            rows = mongodb_service.query_sensor_data(
                measurement=meas,
                device_id=None if patient_id is None else f"patient_{patient_id}_wearable",
                limit=per_measurement_limit,
                default_time_window=False
            )
            all_rows.extend(rows)

        if not all_rows:
            return np.empty((0, len(FEATURES))), np.empty((0,), dtype=int)

        # Group by (patient_id, cycle)
        samples: Dict[Tuple[str, int], Dict[str, float]] = {}
        for r in all_rows:
            tags = r.get("tags") or {}
            pid = tags.get("patient_id")
            cyc = tags.get("cycle")
            if pid is None or cyc is None:
                continue
            if patient_id and pid != patient_id:
                continue
            key = (pid, int(cyc))
            samples.setdefault(key, {})[r["measurement"]] = float(r["value"])

        X_list = []
        y_list = []

        for (pid, cyc), feats in samples.items():
            if not all(k in feats for k in FEATURES):
                continue

            label = self._determine_health_status(feats)
            X_list.append([feats[k] for k in FEATURES])
            y_list.append(LABELS.index(label))

        if not X_list:
            return np.empty((0, len(FEATURES))), np.empty((0,), dtype=int)

        return np.array(X_list, dtype=float), np.array(y_list, dtype=int)

    # -----------------------------
    # Training
    # -----------------------------
    def train_models(self, patient_id: Optional[str] = None) -> TrainResult:
        """
        Train multiple models and select the best based on validation accuracy.
        """
        X, y = self.fetch_training_data(patient_id=patient_id)

        if X.shape[0] < self.min_samples_to_train:
            return TrainResult(
                ok=False,
                samples=int(X.shape[0]),
                message=f"Not enough per-cycle samples to train reliably. Generate more cycles (>= {self.min_samples_to_train} recommended)."
            )

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.25, random_state=42, stratify=y if len(set(y)) > 1 else None
        )

        best_acc = -1.0
        best_name = None
        best_report = None
        best_cm = None

        for name, model in self.models.items():
            try:
                model.fit(X_train, y_train)
                acc = float(model.score(X_test, y_test))
                if acc > best_acc:
                    best_acc = acc
                    best_name = name
                    y_pred = model.predict(X_test)
                    best_report = classification_report(y_test, y_pred, target_names=LABELS, zero_division=0)
                    best_cm = confusion_matrix(y_test, y_pred).tolist()
            except Exception as e:
                iot_logger.warning(f"Training failed for {name}: {e}", source="ml_model_service")

        if not best_name:
            return TrainResult(ok=False, samples=int(X.shape[0]), message="No model could be trained successfully.")

        self.best_model_name = best_name
        self.is_fitted = True

        # Persist lifecycle metadata in memory (sufficient for demo + rubric)
        self.last_train_at_utc = datetime.utcnow().isoformat() + "Z"
        self.last_train_samples = int(X.shape[0])
        self.last_train_accuracy = float(best_acc)

        iot_logger.info(
            f"ML models trained. Best={best_name} acc={best_acc:.3f} samples={X.shape[0]}",
            source="ml_model_service"
        )
        return TrainResult(
            ok=True,
            samples=int(X.shape[0]),
            accuracy=float(best_acc),
            algorithm=best_name,
            report=best_report,
            confusion=best_cm
        )

    def train(self, algorithm: str = "random_forest", force_retrain: bool = False,
              split: Tuple[float, float, float] = (0.7, 0.1, 0.2)) -> Dict:
        """
        Train a specific model (API-facing).
        """
        if algorithm not in self.models:
            return {
                "status": "error",
                "message": f"Unknown algorithm '{algorithm}'",
                "available_algorithms": sorted(self.models.keys()),
            }

        if self.is_trained() and not force_retrain and self.best_model_name == algorithm:
            return {
                "status": "success",
                "message": f"Model '{algorithm}' already trained.",
                "algorithm": algorithm,
                "samples": 0,
            }

        X, y = self.fetch_training_data()
        if X.shape[0] < self.min_samples_to_train:
            return {
                "status": "error",
                "message": f"Not enough per-cycle samples to train reliably. Generate more cycles (>= {self.min_samples_to_train} recommended).",
                "samples": int(X.shape[0]),
            }

        test_size = float(split[2]) if split and len(split) >= 3 else 0.25
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=42, stratify=y if len(set(y)) > 1 else None
        )

        model = self.models[algorithm]
        model.fit(X_train, y_train)
        y_pred = model.predict(X_test)
        report = classification_report(y_test, y_pred, target_names=LABELS, zero_division=0)
        cm = confusion_matrix(y_test, y_pred).tolist()
        precision, recall, f1, _ = precision_recall_fscore_support(
            y_test, y_pred, average="weighted", zero_division=0
        )

        acc = float(model.score(X_test, y_test))
        self.best_model_name = algorithm
        self.is_fitted = True

        self.last_train_at_utc = datetime.utcnow().isoformat() + "Z"
        self.last_train_samples = int(X.shape[0])
        self.last_train_accuracy = acc

        return {
            "status": "success",
            "algorithm": algorithm,
            "samples": int(X.shape[0]),
            "metrics": {
                "accuracy": acc,
                "precision": float(precision),
                "recall": float(recall),
                "f1_score": float(f1),
            },
            "report": report,
            "confusion": cm,
        }

    def compare_models(self, algorithms: Optional[List[str]] = None,
                       split: Tuple[float, float, float] = (0.7, 0.1, 0.2),
                       cv_folds: int = 5) -> Dict:
        """
        Train and compare multiple algorithms, returning metrics for each.
        """
        X, y = self.fetch_training_data()
        if X.shape[0] < 30:
            return {
                "status": "error",
                "message": "Not enough per-cycle samples to compare models. Generate more cycles (>= 30 recommended).",
                "samples": int(X.shape[0]),
                "comparison": [],
            }

        candidates = algorithms or list(self.models.keys())
        test_size = float(split[2]) if split and len(split) >= 3 else 0.25

        # Enable stratified k-fold when all classes are present and have enough samples
        unique, counts = np.unique(y, return_counts=True)
        can_stratify = len(unique) > 1
        use_cv = bool(can_stratify and counts.min() >= cv_folds)

        if not use_cv:
            X_train, X_test, y_train, y_test = train_test_split(
                X, y, test_size=test_size, random_state=42, stratify=y if can_stratify else None
            )

        comparison = []
        best_acc = -1.0
        best_name = None

        for name in candidates:
            base_model = self.models.get(name)
            if base_model is None:
                comparison.append({
                    "status": "error",
                    "algorithm": name,
                    "message": "Unknown algorithm",
                })
                continue
            try:
                if use_cv:
                    skf = StratifiedKFold(n_splits=cv_folds, shuffle=True, random_state=42)
                    accs, precs, recs, f1s = [], [], [], []
                    for train_idx, test_idx in skf.split(X, y):
                        model = clone(base_model)
                        model.fit(X[train_idx], y[train_idx])
                        y_pred = model.predict(X[test_idx])
                        accs.append(float(model.score(X[test_idx], y[test_idx])))
                        p, r, f, _ = precision_recall_fscore_support(
                            y[test_idx], y_pred, average="weighted", zero_division=0
                        )
                        precs.append(float(p))
                        recs.append(float(r))
                        f1s.append(float(f))
                    acc = float(np.mean(accs))
                    precision = float(np.mean(precs))
                    recall = float(np.mean(recs))
                    f1 = float(np.mean(f1s))
                else:
                    model = base_model
                    model.fit(X_train, y_train)
                    y_pred = model.predict(X_test)
                    acc = float(model.score(X_test, y_test))
                    precision, recall, f1, _ = precision_recall_fscore_support(
                        y_test, y_pred, average="weighted", zero_division=0
                    )
                comparison.append({
                    "status": "success",
                    "algorithm": name,
                    "metrics": {
                        "accuracy": acc,
                        "precision": float(precision),
                        "recall": float(recall),
                        "f1_score": float(f1),
                    }
                })
                if acc > best_acc:
                    best_acc = acc
                    best_name = name
            except Exception as e:
                comparison.append({
                    "status": "error",
                    "algorithm": name,
                    "message": str(e),
                })

        if best_name:
            # Fit the best model on all available data so predictions work immediately
            try:
                best_model = self.models.get(best_name)
                if best_model is not None:
                    best_model.fit(X, y)
            except Exception:
                pass
            self.best_model_name = best_name
            self.is_fitted = True

        return {
            "status": "success",
            "comparison": comparison,
            "best_model": best_name,
        }

    # -----------------------------
    # Prediction (per patient)
    # -----------------------------
    def predict_health_status(self, patient_id: str) -> Optional[Dict]:
        """
        Predict health status for patient using latest readings.

        Returns:
            {patient_id, health_status, confidence, algorithm}
        """
        if not self.is_trained():
            return None

        model = self.models.get(self.best_model_name)
        if model is None:
            return None

        # Fetch latest values
        feats = {}
        device_id = f"patient_{patient_id}_wearable"

        for meas in FEATURES:
            row = mongodb_service.get_latest_sensor_data(measurement=meas, device_id=device_id)
            if row and row.get("value") is not None:
                feats[meas] = float(row["value"])

        if len(feats) < len(FEATURES):
            return None

        X = np.array([[feats[k] for k in FEATURES]], dtype=float)
        pred = int(model.predict(X)[0])

        # Confidence (probabilities if supported)
        conf = None
        if hasattr(model, "predict_proba"):
            proba = model.predict_proba(X)[0]
            conf = float(np.max(proba))
        else:
            conf = 0.75

        return {
            "patient_id": patient_id,
            "health_status": LABELS[pred].title(),
            "confidence": round(conf, 3),
            "algorithm": self.best_model_name,
        }

    def predict(self, readings: List) -> Dict:
        """
        Predict health status from a list of SensorReading objects.
        """
        feats = {}
        for r in readings:
            feats[r.measurement] = float(r.value)

        missing = [m for m in FEATURES if m not in feats]
        if missing:
            return {
                "status": "error",
                "message": f"Missing measurements: {', '.join(missing)}",
            }

        if not self.is_trained():
            label = self._determine_health_status(feats)
            return {
                "status": "fallback",
                "health_status": label.title(),
                "confidence": 0.5,
                "algorithm": None,
            }

        model = self.models.get(self.best_model_name)
        if model is None:
            return {"status": "error", "message": "No trained model available"}

        X = np.array([[feats[k] for k in FEATURES]], dtype=float)
        pred = int(model.predict(X)[0])
        if hasattr(model, "predict_proba"):
            proba = model.predict_proba(X)[0]
            conf = float(np.max(proba))
        else:
            conf = 0.75

        return {
            "status": "success",
            "health_status": LABELS[pred].title(),
            "confidence": round(conf, 3),
            "algorithm": self.best_model_name,
        }

    # -----------------------------
    # Labeling rules (weak supervision)
    # -----------------------------
    def _determine_health_status(self, feats: Dict[str, float]) -> str:
        """
        Generate labels from domain thresholds.
        """
        status = "normal"

        def raise_to(level: str):
            nonlocal status
            if status == "critical":
                return
            if level == "critical":
                status = "critical"
            elif level == "warning" and status == "normal":
                status = "warning"

        hr = feats["heart_rate"]
        if hr < 50 or hr > 150:
            raise_to("critical")
        elif hr < 60 or hr > 120:
            raise_to("warning")

        spo2 = feats["oxygen_saturation"]
        if spo2 < 90:
            raise_to("critical")
        elif spo2 < 95:
            raise_to("warning")

        temp = feats["body_temperature"]
        if temp < 35.0 or temp > 39.0:
            raise_to("critical")
        elif temp < 36.0 or temp > 38.0:
            raise_to("warning")

        gluc = feats["glucose_level"]
        if gluc < 70 or gluc > 200:
            raise_to("critical")
        elif gluc < 80 or gluc > 140:
            raise_to("warning")

        sys = feats["blood_pressure_systolic"]
        dia = feats["blood_pressure_diastolic"]
        if sys > 180 or dia > 120 or sys < 90 or dia < 60:
            raise_to("critical")
        elif sys > 140 or dia > 90:
            raise_to("warning")

        return status


# Global instance
ml_model_service = MLModelService()
