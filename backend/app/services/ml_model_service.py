"""
ML Model Service for Health Status Prediction
Trains and uses ML models to predict patient health status

"""
import os
import json
import warnings
from typing import Dict, List, Optional, Tuple
from datetime import datetime

import numpy as np
import pandas as pd
import joblib

from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier, AdaBoostClassifier
from sklearn.svm import SVC
from sklearn.linear_model import LogisticRegression
from sklearn.neighbors import KNeighborsClassifier
from sklearn.naive_bayes import GaussianNB
from sklearn.tree import DecisionTreeClassifier

from sklearn.model_selection import train_test_split, StratifiedKFold, cross_val_score
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)

from app.core.mongodb_client import mongodb_service
from app.core.logger import iot_logger
from app.models.sensor import SensorReading


class HealthStatusMLModel:
    """
    ML Model for predicting patient health status
    Predicts: Normal, Warning, Critical
    """

    MODEL_DIR = os.path.join(os.path.dirname(__file__), "../../models")
    MODEL_FILE = os.path.join(MODEL_DIR, "health_status_model.pkl")
    SCALER_FILE = os.path.join(MODEL_DIR, "scaler.pkl")
    META_FILE = os.path.join(MODEL_DIR, "model_meta.json")
    MODELS_DIR = os.path.join(MODEL_DIR, "trained_models")

    AVAILABLE_ALGORITHMS = {
        "random_forest": {
            "name": "Random Forest",
            "class": RandomForestClassifier,
            "params": {"n_estimators": 200, "max_depth": 12, "random_state": 42, "class_weight": "balanced"},
        },
        "gradient_boosting": {
            "name": "Gradient Boosting",
            "class": GradientBoostingClassifier,
            "params": {"n_estimators": 150, "max_depth": 5, "random_state": 42, "learning_rate": 0.08},
        },
        "ada_boost": {
            "name": "AdaBoost",
            "class": AdaBoostClassifier,
            "params": {"n_estimators": 100, "random_state": 42},
        },
        "svm": {
            "name": "Support Vector Machine",
            "class": SVC,
            "params": {"kernel": "rbf", "probability": True, "random_state": 42, "class_weight": "balanced"},
        },
        "logistic_regression": {
            "name": "Logistic Regression",
            "class": LogisticRegression,
            "params": {"max_iter": 2000, "random_state": 42, "class_weight": "balanced", "multi_class": "multinomial"},
        },
        "knn": {
            "name": "K-Nearest Neighbors",
            "class": KNeighborsClassifier,
            "params": {"n_neighbors": 7, "weights": "distance"},
        },
        "naive_bayes": {
            "name": "Naive Bayes",
            "class": GaussianNB,
            "params": {},
        },
        "decision_tree": {
            "name": "Decision Tree",
            "class": DecisionTreeClassifier,
            "params": {"max_depth": 12, "random_state": 42, "class_weight": "balanced"},
        },
    }

    def __init__(self):
        self.model = None
        self.current_algorithm = "random_forest"
        self.scaler = StandardScaler()
        self.is_trained = False

        self.model_metrics: Dict[str, Dict] = {}
        self.feature_names = [
            "heart_rate",
            "blood_pressure_systolic",
            "blood_pressure_diastolic",
            "body_temperature",
            "oxygen_saturation",
            "glucose_level",
            "activity_steps",
            "ambient_temperature",
            "co2_level",
        ]
        # Labels are integers: 0,1,2
        self.class_names = ["Normal", "Warning", "Critical"]

        # For prediction-time imputation
        self.feature_medians_: Optional[List[float]] = None

        os.makedirs(self.MODELS_DIR, exist_ok=True)
        os.makedirs(self.MODEL_DIR, exist_ok=True)

        self.load_model()

    # ----------------------------
    # Feature preparation
    # ----------------------------

    def prepare_features(self, readings: List[SensorReading]) -> Optional[np.ndarray]:
        """
        Prepare feature vector from sensor readings.
        Uses mean per measurement across the batch, which is stable for a cycle.

        Returns:
            np.ndarray shape (1, n_features) or None if insufficient data
        """
        if not readings:
            return None

        sensor_dict: Dict[str, List[float]] = {}
        for r in readings:
            sensor_dict.setdefault(r.measurement, []).append(r.value)

        features: List[float] = []
        for name in self.feature_names:
            vals = sensor_dict.get(name, [])
            features.append(float(np.mean(vals)) if vals else np.nan)

        # Require at least half of features present
        if np.sum(np.isnan(features)) > (len(features) / 2):
            return None

        return np.array(features, dtype=float).reshape(1, -1)

    def _impute_features(self, features: np.ndarray) -> np.ndarray:
        """
        Impute missing values using training medians (preferred) else zeros.
        """
        if features is None:
            return features
        if self.feature_medians_ and len(self.feature_medians_) == features.shape[1]:
            med = np.array(self.feature_medians_, dtype=float).reshape(1, -1)
            out = features.copy()
            mask = np.isnan(out)
            out[mask] = np.take(med, np.where(mask)[1])
            return out
        return np.nan_to_num(features, nan=0.0)

    # ----------------------------
    # Prediction
    # ----------------------------

    def predict(self, readings: List[SensorReading]) -> Dict:
        """
        Predict health status from sensor readings.

        Returns:
            {
              'health_status': 'Normal'|'Warning'|'Critical'|None,
              'confidence': float,
              'probabilities': {class: prob},
              'features_used': list,
              'feature_values': {feature: value}
            }
        """
        if not self.is_trained or self.model is None:
            return {"health_status": None, "confidence": 0.0, "probabilities": {}, "error": "Model not trained"}

        features = self.prepare_features(readings)
        if features is None:
            return {"health_status": None, "confidence": 0.0, "probabilities": {}, "error": "Insufficient sensor data"}

        features = self._impute_features(features)

        try:
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=UserWarning, module="sklearn")
                features_scaled = self.scaler.transform(features)
        except Exception:
            features_scaled = features

        pred_label = int(self.model.predict(features_scaled)[0])

        # probability support
        prob_dict = {}
        confidence = 0.0
        if hasattr(self.model, "predict_proba"):
            probs = self.model.predict_proba(features_scaled)[0]
            confidence = float(np.max(probs))
            prob_dict = {self.class_names[i]: float(probs[i]) for i in range(len(self.class_names))}
        else:
            # No probas: provide minimal confidence
            confidence = 0.5

        feature_values = {self.feature_names[i]: float(features[0, i]) for i in range(len(self.feature_names))}
        return {
            "health_status": self.class_names[pred_label],
            "confidence": confidence,
            "probabilities": prob_dict,
            "features_used": self.feature_names,
            "feature_values": feature_values,
            "algorithm": self.current_algorithm,
        }

    # ----------------------------
    # Training / Evaluation
    # ----------------------------

    def train(
        self,
        training_data: Optional[pd.DataFrame] = None,
        split: Tuple[float, float, float] = (0.7, 0.1, 0.2),
        algorithm: str = "random_forest",
        force_retrain: bool = False,
        cv_folds: int = 5,
        random_state: int = 42,
    ) -> Dict:
        """
        Train the ML model with explicit Train/Val/Test split.

        Args:
            training_data: DataFrame containing features + health_status_label (int 0/1/2)
            split: (train_ratio, val_ratio, test_ratio) must sum to 1.0
            algorithm: algorithm key from AVAILABLE_ALGORITHMS
            cv_folds: StratifiedKFold folds
        """
        try:
            if (
                self.is_trained
                and not force_retrain
                and algorithm == self.current_algorithm
                and training_data is None
            ):
                return {
                    "status": "skipped",
                    "message": "Model already trained. Set force_retrain=true to retrain.",
                    "algorithm": self.current_algorithm,
                    "algorithm_name": self.AVAILABLE_ALGORITHMS.get(self.current_algorithm, {}).get("name", "Unknown"),
                    "metrics": self.model_metrics.get(self.current_algorithm, {}),
                }
            if algorithm not in self.AVAILABLE_ALGORITHMS:
                return {"status": "error", "message": f"Unknown algorithm: {algorithm}"}

            train_r, val_r, test_r = split
            if not np.isclose(train_r + val_r + test_r, 1.0):
                return {"status": "error", "message": "split ratios must sum to 1.0 (train,val,test)"}
            if train_r <= 0 or test_r <= 0:
                return {"status": "error", "message": "train and test ratios must be > 0"}

            if training_data is None:
                training_data = self._fetch_training_data()

            if training_data is None or len(training_data) < 30:
                return {"status": "error", "message": "Insufficient training data (need at least 30 samples)"}

            # Features + labels
            df = training_data.copy()
            for col in self.feature_names:
                if col not in df.columns:
                    df[col] = 0
            if "health_status_label" not in df.columns:
                return {"status": "error", "message": "training_data must contain health_status_label"}

            X = df[self.feature_names].astype(float)
            y = df["health_status_label"].astype(int)

            # Split into train and temp (val+test)
            temp_size = val_r + test_r
            X_train, X_temp, y_train, y_temp = train_test_split(
                X,
                y,
                test_size=temp_size,
                random_state=random_state,
                stratify=y,
            )

            # Split temp into val and test
            # val proportion relative to temp
            if temp_size > 0:
                val_prop = val_r / temp_size if temp_size else 0.0
                if val_r > 0:
                    X_val, X_test, y_val, y_test = train_test_split(
                        X_temp,
                        y_temp,
                        test_size=(1.0 - val_prop),
                        random_state=random_state,
                        stratify=y_temp,
                    )
                else:
                    X_val, y_val = X_temp.iloc[:0], y_temp.iloc[:0]
                    X_test, y_test = X_temp, y_temp
            else:
                X_val, y_val = X_train.iloc[:0], y_train.iloc[:0]
                X_test, y_test = X_train.iloc[:0], y_train.iloc[:0]

            # Imputation medians from TRAIN only
            train_medians = X_train.median(numeric_only=True).values.tolist()
            self.feature_medians_ = [float(m) if np.isfinite(m) else 0.0 for m in train_medians]

            def impute_df(dfx: pd.DataFrame) -> np.ndarray:
                arr = dfx.values.astype(float)
                med = np.array(self.feature_medians_, dtype=float).reshape(1, -1)
                mask = np.isnan(arr)
                if mask.any():
                    arr[mask] = np.take(med, np.where(mask)[1])
                return arr

            X_train_arr = impute_df(X_train)
            X_val_arr = impute_df(X_val) if len(X_val) else None
            X_test_arr = impute_df(X_test) if len(X_test) else None

            # Scale using TRAIN only
            X_train_scaled = self.scaler.fit_transform(X_train_arr)
            X_val_scaled = self.scaler.transform(X_val_arr) if X_val_arr is not None else None
            X_test_scaled = self.scaler.transform(X_test_arr) if X_test_arr is not None else None

            # Train model
            algo_cfg = self.AVAILABLE_ALGORITHMS[algorithm]
            model = algo_cfg["class"](**algo_cfg["params"])
            model.fit(X_train_scaled, y_train)

            # Scores
            train_score = float(model.score(X_train_scaled, y_train))
            val_score = float(model.score(X_val_scaled, y_val)) if X_val_scaled is not None and len(y_val) else None
            test_score = float(model.score(X_test_scaled, y_test)) if X_test_scaled is not None and len(y_test) else None

            # Test metrics
            y_pred = model.predict(X_test_scaled) if X_test_scaled is not None and len(y_test) else np.array([])
            if len(y_pred):
                acc = float(accuracy_score(y_test, y_pred))
                f1 = float(f1_score(y_test, y_pred, average="weighted"))
                prec = float(precision_score(y_test, y_pred, average="weighted"))
                rec = float(recall_score(y_test, y_pred, average="weighted"))
                cm = confusion_matrix(y_test, y_pred, labels=[0, 1, 2]).tolist()
                report = classification_report(
                    y_test,
                    y_pred,
                    target_names=self.class_names,
                    output_dict=True,
                    zero_division=0,
                )
            else:
                acc, f1, prec, rec, cm, report = 0.0, 0.0, 0.0, 0.0, [[0, 0, 0]] * 3, {}

            # CV on TRAIN only (scaled train)
            skf = StratifiedKFold(n_splits=max(2, int(cv_folds)), shuffle=True, random_state=random_state)
            cv_scores = cross_val_score(model, X_train_scaled, y_train, cv=skf, scoring="accuracy")
            cv_scores_list = [float(x) for x in cv_scores]
            cv_mean = float(np.mean(cv_scores)) if len(cv_scores) else 0.0
            cv_std = float(np.std(cv_scores)) if len(cv_scores) else 0.0

            metrics = {
                "status": "success",
                "algorithm": algorithm,
                "algorithm_name": algo_cfg["name"],

                "split": {"train": train_r, "val": val_r, "test": test_r},
                "samples": {
                    "total": int(len(df)),
                    "train": int(len(X_train)),
                    "val": int(len(X_val)) if X_val is not None else 0,
                    "test": int(len(X_test)) if X_test is not None else 0,
                },

                "scores": {
                    "train_score": train_score,
                    "val_score": val_score,
                    "test_score": test_score,
                },

                "metrics": {
                    "accuracy": acc,
                    "f1_score": f1,
                    "precision": prec,
                    "recall": rec,
                },

                "confusion_matrix": {
                    "labels": self.class_names,     # row/col order: Normal, Warning, Critical
                    "matrix": cm,
                },

                "classification_report": report,

                "cross_validation": {
                    "folds": int(cv_folds),
                    "scores": cv_scores_list,
                    "mean": cv_mean,
                    "std": cv_std,
                },
            }

            # Set current/best model
            self.model = model
            self.current_algorithm = algorithm
            self.is_trained = True
            self.model_metrics[algorithm] = metrics

            self.save_model()
            return metrics

        except Exception as e:
            iot_logger.error(f"ML Model training error: {str(e)}", source="ml_service")
            return {"status": "error", "message": str(e)}

    def compare_models(
        self,
        training_data: Optional[pd.DataFrame] = None,
        split: Tuple[float, float, float] = (0.7, 0.1, 0.2),
        algorithms: Optional[List[str]] = None,
        cv_folds: int = 5,
        random_state: int = 42,
    ) -> Dict:
        """
        Train and compare multiple ML algorithms under the same split/scaler rules.
        Saves the best (by test_score) as the default model.
        """
        try:
            if training_data is None:
                training_data = self._fetch_training_data()

            if training_data is None or len(training_data) < 30:
                return {"status": "error", "message": "Insufficient training data (need at least 30 samples)"}

            if algorithms is None:
                algorithms = list(self.AVAILABLE_ALGORITHMS.keys())

            invalid = [a for a in algorithms if a not in self.AVAILABLE_ALGORITHMS]
            if invalid:
                return {"status": "error", "message": f"Invalid algorithms: {invalid}"}

            results = []
            best = None

            for algo in algorithms:
                res = self.train(
                    training_data=training_data,
                    split=split,
                    algorithm=algo,
                    force_retrain=True,
                    cv_folds=cv_folds,
                    random_state=random_state,
                )
                results.append(res)

                if res.get("status") == "success":
                    ts = res.get("scores", {}).get("test_score")
                    if ts is not None and (best is None or ts > best.get("scores", {}).get("test_score", -1)):
                        best = res

                # Save each trained model artifact for comparison (optional)
                if res.get("status") == "success":
                    model_file = os.path.join(self.MODELS_DIR, f"{algo}_model.pkl")
                    scaler_file = os.path.join(self.MODELS_DIR, f"{algo}_scaler.pkl")
                    meta_file = os.path.join(self.MODELS_DIR, f"{algo}_meta.json")
                    joblib.dump(self.model, model_file)
                    joblib.dump(self.scaler, scaler_file)
                    with open(meta_file, "w") as f:
                        json.dump(res, f, indent=2)

            if not best:
                return {"status": "error", "message": "All algorithms failed", "comparison": results}

            # Load best artifacts back into default model files--save
            best_algo = best["algorithm"]
            best_model_file = os.path.join(self.MODELS_DIR, f"{best_algo}_model.pkl")
            best_scaler_file = os.path.join(self.MODELS_DIR, f"{best_algo}_scaler.pkl")
            best_meta_file = os.path.join(self.MODELS_DIR, f"{best_algo}_meta.json")

            self.model = joblib.load(best_model_file)
            self.scaler = joblib.load(best_scaler_file)
            self.current_algorithm = best_algo
            self.is_trained = True

            # restore medians if present
            # (best meta contains no medians; keep current medians from last train)
            self.save_model()

            return {
                "status": "success",
                "best_algorithm": best_algo,
                "best_algorithm_name": best["algorithm_name"],
                "best_test_score": best["scores"]["test_score"],
                "best_metrics": best["metrics"],
                "comparison": results,
                "summary": {
                    "total_algorithms": len(algorithms),
                    "successful": len([r for r in results if r.get("status") == "success"]),
                    "failed": len([r for r in results if r.get("status") != "success"]),
                },
            }

        except Exception as e:
            iot_logger.error(f"Model comparison error: {str(e)}", source="ml_service")
            return {"status": "error", "message": str(e)}

    # ----------------------------
    # Training data fetch
    # ----------------------------

    def _infer_patient_id(self, device_id: str) -> str:
        """
        Infer patient_id from device_id strings like:
          - patient_P001_wearable
          - patient_P002_wearable
        """
        if not device_id:
            return "unknown"
        parts = device_id.split("_")
        if len(parts) >= 2 and parts[0] == "patient":
            return parts[1]
        return "unknown"

    def _parse_time_bucket(self, iso_time: str) -> str:
        """
        Convert iso string to an hour-bucket key: YYYY-MM-DDTHH
        """
        if not iso_time:
            return "unknown"
        try:
            # datetime.fromisoformat handles "YYYY-MM-DDTHH:MM:SS" (and with timezone)
            dt = datetime.fromisoformat(iso_time.replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%dT%H")
        except Exception:
            # fallback: keep prefix
            return iso_time[:13] if len(iso_time) >= 13 else iso_time

    def _fetch_training_data(self) -> Optional[pd.DataFrame]:
        """
        Fetch training data from MongoDB warehouse.
        Falls back to synthetic data if insufficient.

        NOTE:
        mongodb_service.query_sensor_data() currently returns:
          [{time, measurement, device_id, sensor_id, value}, ...]
        It does NOT return tags.
        """
        try:
            # Collect raw flat rows from MongoDB
            flat_rows = []
            for measurement in self.feature_names:
                # You may include activity_steps if stored; do not skip it silently
                readings = mongodb_service.query_sensor_data(measurement=measurement, limit=2000, default_time_window=False)

                for r in readings:
                    device_id = r.get("device_id", "")
                    flat_rows.append({
                        "patient_id": self._infer_patient_id(device_id),
                        "time_bucket": self._parse_time_bucket(r.get("time", "")),
                        "measurement": measurement,
                        "value": float(r.get("value", 0.0)),
                        "device_id": device_id,
                    })

            # Pivot into samples (patient_id, hour) -> feature vector
            if len(flat_rows) >= 300:
                from collections import defaultdict

                grouped = defaultdict(lambda: defaultdict(list))
                for item in flat_rows:
                    key = (item["patient_id"], item["time_bucket"])
                    grouped[key][item["measurement"]].append(item["value"])

                samples = []
                for (pid, bucket), meas_map in grouped.items():
                    # Require at least 5 measurements for a valid sample
                    present = sum(1 for m in self.feature_names if m in meas_map and len(meas_map[m]) > 0)
                    if present < 5:
                        continue

                    sample = {"patient_id": pid, "time_bucket": bucket}

                    for f in self.feature_names:
                        vals = meas_map.get(f, [])
                        sample[f] = float(np.mean(vals)) if vals else np.nan

                    # Need core vitals to label
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

                    sample["health_status_label"] = int(self._determine_health_status(
                        sample["heart_rate"],
                        sample["blood_pressure_systolic"],
                        sample["blood_pressure_diastolic"],
                        sample["body_temperature"],
                        sample["oxygen_saturation"],
                        sample["glucose_level"],
                    ))
                    samples.append(sample)

                if len(samples) >= 80:
                    df = pd.DataFrame(samples)
                    df = df[self.feature_names + ["health_status_label"]].copy()
                    df = df.fillna(0.0)
                    iot_logger.info(f"Using {len(df)} real training samples from MongoDB", source="ml_service")
                    return df

            # Fallback: synthetic
            iot_logger.info("Generating synthetic training data", source="ml_service")
            return self._generate_synthetic_training_data(n_samples=1500)

        except Exception as e:
            iot_logger.error(f"Error fetching training data: {str(e)}", source="ml_service")
            return self._generate_synthetic_training_data(n_samples=1500)

    def _generate_synthetic_training_data(self, n_samples: int = 1000) -> pd.DataFrame:
        data = []
        for _ in range(int(n_samples)):
            hr = np.random.normal(75, 15)
            bp_sys = np.random.normal(120, 20)
            bp_dia = np.random.normal(80, 10)
            temp = np.random.normal(36.5, 0.5)
            spo2 = np.random.normal(98, 3)
            glucose = np.random.normal(95, 20)
            activity = np.random.normal(5000, 2000)
            ambient = np.random.normal(22, 2)
            co2 = np.random.normal(700, 150)

            label = int(self._determine_health_status(hr, bp_sys, bp_dia, temp, spo2, glucose))

            data.append({
                "heart_rate": float(max(40, min(200, hr))),
                "blood_pressure_systolic": float(max(70, min(220, bp_sys))),
                "blood_pressure_diastolic": float(max(40, min(140, bp_dia))),
                "body_temperature": float(max(35, min(42, temp))),
                "oxygen_saturation": float(max(70, min(100, spo2))),
                "glucose_level": float(max(40, min(400, glucose))),
                "activity_steps": float(max(0, activity)),
                "ambient_temperature": float(max(15, min(30, ambient))),
                "co2_level": float(max(350, min(2000, co2))),
                "health_status_label": label,
            })

        return pd.DataFrame(data)

    def _determine_health_status(self, hr, bp_sys, bp_dia, temp, spo2, glucose) -> int:
        """
        Determine health status label (0=Normal, 1=Warning, 2=Critical)

        Design rule:
        - If ANY critical condition occurs => Critical
        - Else if >=2 warnings => Warning
        - Else => Normal
        """
        critical = 0
        warning = 0

        # Heart rate
        if hr < 50 or hr > 150:
            critical += 1
        elif hr < 60 or hr > 120:
            warning += 1

        # Blood pressure
        if bp_sys < 80 or bp_sys > 180 or bp_dia < 50 or bp_dia > 120:
            critical += 1
        elif bp_sys < 90 or bp_sys > 140 or bp_dia < 60 or bp_dia > 90:
            warning += 1

        # Temperature
        if temp < 35 or temp > 39.5:
            critical += 1
        elif temp < 36 or temp > 38:
            warning += 1

        # SpO2
        if spo2 < 85:
            critical += 1
        elif spo2 < 90:
            warning += 1

        # Glucose
        if glucose < 50 or glucose > 250:
            critical += 1
        elif glucose < 70 or glucose > 180:
            warning += 1

        if critical >= 1:
            return 2
        if warning >= 2:
            return 1
        return 0

    # ----------------------------
    # Persistence
    # ----------------------------

    def save_model(self):
        """Save model + scaler + metadata."""
        try:
            os.makedirs(self.MODEL_DIR, exist_ok=True)
            joblib.dump(self.model, self.MODEL_FILE)
            joblib.dump(self.scaler, self.SCALER_FILE)

            meta = {
                "algorithm": self.current_algorithm,
                "algorithm_name": self.AVAILABLE_ALGORITHMS[self.current_algorithm]["name"],
                "feature_names": self.feature_names,
                "class_names": self.class_names,
                "feature_medians": self.feature_medians_,
                "metrics": self.model_metrics.get(self.current_algorithm, {}),
                "saved_at": datetime.utcnow().isoformat() + "Z",
            }
            with open(self.META_FILE, "w") as f:
                json.dump(meta, f, indent=2)

            iot_logger.info(
                f"ML model saved ({self.AVAILABLE_ALGORITHMS[self.current_algorithm]['name']})",
                source="ml_service",
            )
        except Exception as e:
            iot_logger.error(f"Error saving model: {str(e)}", source="ml_service")

    def load_model(self):
        """Load model + scaler + metadata."""
        try:
            if os.path.exists(self.MODEL_FILE) and os.path.exists(self.SCALER_FILE):
                self.model = joblib.load(self.MODEL_FILE)
                self.scaler = joblib.load(self.SCALER_FILE)

                if os.path.exists(self.META_FILE):
                    with open(self.META_FILE, "r") as f:
                        meta = json.load(f)
                    meta_features = meta.get("feature_names")
                    if meta_features and meta_features != self.feature_names:
                        iot_logger.warning(
                            "Loaded ML model feature set does not match current feature_names; retrain required.",
                            source="ml_service",
                        )
                        self.model = None
                        self.scaler = StandardScaler()
                        self.is_trained = False
                        return
                    self.current_algorithm = meta.get("algorithm", "random_forest")
                    self.feature_medians_ = meta.get("feature_medians")
                    if "metrics" in meta:
                        self.model_metrics[self.current_algorithm] = meta["metrics"]

                self.is_trained = True
                iot_logger.info(
                    f"ML model loaded ({self.AVAILABLE_ALGORITHMS.get(self.current_algorithm, {}).get('name', 'Unknown')})",
                    source="ml_service",
                )
        except Exception as e:
            iot_logger.warning(f"Could not load model: {str(e)}", source="ml_service")
            self.is_trained = False

    def get_available_algorithms(self) -> Dict:
        """Get list of available algorithms."""
        return {
            algo: {"name": cfg["name"], "description": f"{cfg['name']} classifier"}
            for algo, cfg in self.AVAILABLE_ALGORITHMS.items()
        }


# Global instance
health_ml_model = HealthStatusMLModel()
