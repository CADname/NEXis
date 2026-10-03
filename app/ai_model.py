from __future__ import annotations

from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd


class FaultModel:
    """Inference wrapper that reproduces the feature pipeline used to train the supplied model."""

    def __init__(self, model_path: str | Path):
        self.model_path = Path(model_path)
        bundle = joblib.load(self.model_path)
        if not isinstance(bundle, dict) or "model" not in bundle:
            raise RuntimeError("Unsupported NEXis model bundle")
        self.bundle = bundle
        self.model = bundle["model"]
        self.feature_columns = list(bundle["feature_columns"])
        self.window_size = int(bundle.get("window_size", 256))
        self.step_size = int(bundle.get("step_size", 64))
        self.fs = float(bundle.get("fs", 100.0))
        self.label_map = {int(k): str(v) for k, v in dict(bundle.get("label_map", {})).items()}
        self.expected_csv_columns = list(bundle.get("expected_csv_columns", []))

    @staticmethod
    def _arr(x: Any) -> np.ndarray:
        return np.asarray(x, dtype=float)

    def _rms(self, x: Any) -> float:
        x = self._arr(x)
        return 0.0 if len(x) == 0 else float(np.sqrt(np.mean(x ** 2)))

    def _peak_to_peak(self, x: Any) -> float:
        x = self._arr(x)
        return 0.0 if len(x) == 0 else float(np.max(x) - np.min(x))

    def _mean_abs_diff(self, x: Any) -> float:
        x = self._arr(x)
        return 0.0 if len(x) < 2 else float(np.mean(np.abs(np.diff(x))))

    def _max_abs_diff(self, x: Any) -> float:
        x = self._arr(x)
        return 0.0 if len(x) < 2 else float(np.max(np.abs(np.diff(x))))

    def _crest_factor(self, x: Any) -> float:
        x = self._arr(x)
        d = self._rms(x)
        return 0.0 if d == 0 else float(np.max(np.abs(x)) / d)

    def _zero_crossing_rate(self, x: Any) -> float:
        x = self._arr(x)
        if len(x) < 2:
            return 0.0
        x = x - np.mean(x)
        s = np.sign(x)
        c = np.sum(s[1:] * s[:-1] < 0)
        return float(c / (len(x) - 1))

    def _fft_power(self, x: Any) -> tuple[np.ndarray, np.ndarray]:
        x = self._arr(x)
        if len(x) == 0:
            return np.array([0.0]), np.array([0.0])
        x = x - np.mean(x)
        y = np.fft.rfft(x)
        p = np.abs(y) ** 2
        f = np.fft.rfftfreq(len(x), d=1.0 / self.fs)
        return f, p

    def _fft_total_energy(self, x: Any) -> float:
        _, p = self._fft_power(x)
        return 0.0 if len(p) == 0 else float(np.sum(p) / len(p))

    def _fft_band_energy(self, x: Any, low: float, high: float) -> float:
        f, p = self._fft_power(x)
        m = (f >= low) & (f < high)
        return 0.0 if not np.any(m) else float(np.sum(p[m]) / len(p))

    def _dominant_frequency(self, x: Any) -> float:
        f, p = self._fft_power(x)
        if len(p) <= 1:
            return 0.0
        p = p.copy()
        p[0] = 0.0
        return float(f[int(np.argmax(p))])

    def _spectral_centroid(self, x: Any) -> float:
        f, p = self._fft_power(x)
        mag = np.sqrt(p)
        if np.sum(mag) <= 0:
            return 0.0
        return float(np.sum(f * mag) / np.sum(mag))

    def _spectral_spread(self, x: Any) -> float:
        f, p = self._fft_power(x)
        mag = np.sqrt(p)
        if np.sum(mag) <= 0:
            return 0.0
        c = np.sum(f * mag) / np.sum(mag)
        return float(np.sqrt(np.sum(((f - c) ** 2) * mag) / np.sum(mag)))

    def _add_signal_features(self, features: dict[str, float], prefix: str, x: Any) -> None:
        x = self._arr(x)
        if len(x) == 0:
            return
        centered = x - np.mean(x)
        features[f"{prefix}_mean"] = float(np.mean(x))
        features[f"{prefix}_std"] = float(np.std(x))
        features[f"{prefix}_var"] = float(np.var(x))
        features[f"{prefix}_min"] = float(np.min(x))
        features[f"{prefix}_max"] = float(np.max(x))
        features[f"{prefix}_median"] = float(np.median(x))
        features[f"{prefix}_q05"] = float(np.quantile(x, 0.05))
        features[f"{prefix}_q25"] = float(np.quantile(x, 0.25))
        features[f"{prefix}_q75"] = float(np.quantile(x, 0.75))
        features[f"{prefix}_q95"] = float(np.quantile(x, 0.95))
        features[f"{prefix}_iqr"] = float(np.quantile(x, 0.75) - np.quantile(x, 0.25))
        features[f"{prefix}_rms"] = self._rms(x)
        features[f"{prefix}_centered_rms"] = self._rms(centered)
        features[f"{prefix}_ptp"] = self._peak_to_peak(x)
        features[f"{prefix}_crest_factor"] = self._crest_factor(centered)
        features[f"{prefix}_zcr"] = self._zero_crossing_rate(centered)
        features[f"{prefix}_mean_abs_diff"] = self._mean_abs_diff(x)
        features[f"{prefix}_max_abs_diff"] = self._max_abs_diff(x)
        features[f"{prefix}_fft_total_energy"] = self._fft_total_energy(x)
        features[f"{prefix}_fft_0_5hz"] = self._fft_band_energy(x, 0.0, 5.0)
        features[f"{prefix}_fft_5_15hz"] = self._fft_band_energy(x, 5.0, 15.0)
        features[f"{prefix}_fft_15_30hz"] = self._fft_band_energy(x, 15.0, 30.0)
        features[f"{prefix}_fft_30_50hz"] = self._fft_band_energy(x, 30.0, 50.0)
        features[f"{prefix}_dominant_freq"] = self._dominant_frequency(x)
        features[f"{prefix}_spectral_centroid"] = self._spectral_centroid(x)
        features[f"{prefix}_spectral_spread"] = self._spectral_spread(x)

    def _safe_corr(self, a: Any, b: Any) -> float:
        a = self._arr(a)
        b = self._arr(b)
        if len(a) < 2 or len(b) < 2 or np.std(a) == 0 or np.std(b) == 0:
            return 0.0
        return float(np.corrcoef(a, b)[0, 1])

    def extract_features(self, rows: list[dict[str, Any]]) -> dict[str, float]:
        w = pd.DataFrame(rows)
        required = [
            "ax_g", "ay_g", "az_g", "total_g", "rpm", "target_rpm", "rpm_error",
            "pwm_eq", "duty_10bit", "acs_v", "current_a"
        ]
        missing = [c for c in required if c not in w.columns]
        if missing:
            raise ValueError(f"Missing model inputs: {missing}")
        for c in required:
            w[c] = pd.to_numeric(w[c], errors="coerce")
        if w[required].isna().any().any():
            raise ValueError("Model input contains missing/non-numeric values")

        ax = w["ax_g"].to_numpy(dtype=float)
        ay = w["ay_g"].to_numpy(dtype=float)
        az = w["az_g"].to_numpy(dtype=float)
        total_g = w["total_g"].to_numpy(dtype=float)
        rpm = w["rpm"].to_numpy(dtype=float)
        target_rpm = w["target_rpm"].to_numpy(dtype=float)
        rpm_error = w["rpm_error"].to_numpy(dtype=float)
        pwm_eq = w["pwm_eq"].to_numpy(dtype=float)
        duty_10bit = w["duty_10bit"].to_numpy(dtype=float)
        acs_v = w["acs_v"].to_numpy(dtype=float)
        current_a = w["current_a"].to_numpy(dtype=float)

        vib_ax = ax - np.mean(ax)
        vib_ay = ay - np.mean(ay)
        vib_az = az - np.mean(az)
        vib_total = total_g - np.mean(total_g)

        features: dict[str, float] = {}
        for prefix, arr in [
            ("ax", ax), ("ay", ay), ("az", az), ("total_g", total_g),
            ("vib_ax", vib_ax), ("vib_ay", vib_ay), ("vib_az", vib_az), ("vib_total", vib_total),
            ("rpm", rpm), ("rpm_error", rpm_error), ("pwm_eq", pwm_eq),
            ("duty_10bit", duty_10bit), ("acs_v", acs_v), ("current_a", current_a),
        ]:
            self._add_signal_features(features, prefix, arr)

        features["target_rpm_mean"] = float(np.mean(target_rpm))
        features["target_rpm_std"] = float(np.std(target_rpm))
        features["current_abs_mean"] = float(np.mean(np.abs(current_a)))
        features["current_abs_std"] = float(np.std(np.abs(current_a)))
        features["current_abs_max"] = float(np.max(np.abs(current_a)))
        features["current_abs_rms"] = self._rms(np.abs(current_a))
        features["vib_total_rms_over_current_abs_mean"] = float(self._rms(vib_total) / (np.mean(np.abs(current_a)) + 1e-9))
        features["vib_total_rms_over_rpm_mean"] = float(self._rms(vib_total) / (np.mean(np.abs(rpm)) + 1e-9))
        features["current_abs_mean_over_pwm_mean"] = float(np.mean(np.abs(current_a)) / (np.mean(np.abs(pwm_eq)) + 1e-9))
        features["rpm_mean_over_pwm_mean"] = float(np.mean(rpm) / (np.mean(np.abs(pwm_eq)) + 1e-9))
        features["xy_corr"] = self._safe_corr(vib_ax, vib_ay)
        features["xz_corr"] = self._safe_corr(vib_ax, vib_az)
        features["yz_corr"] = self._safe_corr(vib_ay, vib_az)
        features["ax_current_corr"] = self._safe_corr(vib_ax, current_a)
        features["ay_current_corr"] = self._safe_corr(vib_ay, current_a)
        features["az_current_corr"] = self._safe_corr(vib_az, current_a)
        features["total_current_corr"] = self._safe_corr(vib_total, current_a)
        features["rpm_current_corr"] = self._safe_corr(rpm, current_a)
        features["rpm_vib_total_corr"] = self._safe_corr(rpm, vib_total)
        return features

    def predict(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        if len(rows) != self.window_size:
            raise ValueError(f"Expected {self.window_size} samples, got {len(rows)}")
        features = self.extract_features(rows)
        x = pd.DataFrame([{name: features.get(name, 0.0) for name in self.feature_columns}])
        x = x.replace([np.inf, -np.inf], np.nan).fillna(0.0)
        pred_id = int(self.model.predict(x)[0])
        proba = self.model.predict_proba(x)[0]
        classes = [int(v) for v in self.model.classes_]
        probabilities = {self.label_map.get(cls, str(cls)): float(p) for cls, p in zip(classes, proba)}
        pred_label = self.label_map.get(pred_id, str(pred_id))
        return {
            "pred_label_id": pred_id,
            "pred_label_name": pred_label,
            "top_prob": float(max(proba)),
            "probabilities": probabilities,
            "feature_count": len(self.feature_columns),
        }

    def info(self) -> dict[str, Any]:
        return {
            "model_name": str(self.bundle.get("model_name", type(self.model).__name__)),
            "algorithm": type(self.model).__name__,
            "n_estimators": int(getattr(self.model, "n_estimators", 0) or 0),
            "feature_count": len(self.feature_columns),
            "window_size": self.window_size,
            "step_size": self.step_size,
            "fs": self.fs,
            "classes": [self.label_map[k] for k in sorted(self.label_map)],
            "file_accuracy": float(self.bundle.get("file_accuracy", 0.0)),
            "file_macro_f1": float(self.bundle.get("file_macro_f1", 0.0)),
            "window_accuracy": float(self.bundle.get("window_accuracy", 0.0)),
            "window_macro_f1": float(self.bundle.get("window_macro_f1", 0.0)),
            "decision_type": str(self.bundle.get("decision_type", "")),
            "expected_csv_columns": self.expected_csv_columns,
        }
