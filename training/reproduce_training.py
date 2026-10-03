from pathlib import Path
import copy
import json
import hashlib
import warnings

import numpy as np
import pandas as pd
import joblib

from sklearn.ensemble import ExtraTreesClassifier, RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    classification_report,
    f1_score,
)

warnings.filterwarnings("ignore")


# ============================================================
# 1. Core configuration
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent
DATA_DIR = REPO_ROOT / "app" / "replay_data"
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

WINDOW_SIZE = 256
STEP_SIZE = 64
FS = 100.0

MODEL_PATH = OUTPUT_DIR / "multi_fault_current_csv_model.joblib"

FEATURE_CSV_PATH = OUTPUT_DIR / "training_features_current_csv.csv"
FEATURE_META_PATH = OUTPUT_DIR / "training_features_current_csv_meta.json"

SUMMARY_CSV_PATH = OUTPUT_DIR / "model_selection_summary_current_csv.csv"
FILE_VALIDATION_CSV_PATH = OUTPUT_DIR / "file_validation_current_csv.csv"
WINDOW_VALIDATION_CSV_PATH = OUTPUT_DIR / "window_validation_current_csv.csv"

FILE_CM_CSV_PATH = OUTPUT_DIR / "file_confusion_matrix_current_csv.csv"
WINDOW_CM_CSV_PATH = OUTPUT_DIR / "window_confusion_matrix_current_csv.csv"

FILE_REPORT_CSV_PATH = OUTPUT_DIR / "file_classification_report_current_csv.csv"
WINDOW_REPORT_CSV_PATH = OUTPUT_DIR / "window_classification_report_current_csv.csv"

FEATURE_IMPORTANCE_CSV_PATH = OUTPUT_DIR / "feature_importance_current_csv.csv"
CSV_CHECK_CSV_PATH = OUTPUT_DIR / "csv_structure_check_current_csv.csv"


# ============================================================
# 2. Fixed CSV schema
# ============================================================

EXPECTED_COLUMNS = [
    "sample_index",
    "time_ms_raw",
    "time_ms_zero",
    "elapsed_ms",
    "ax_g",
    "ay_g",
    "az_g",
    "total_g",
    "rpm",
    "target_rpm",
    "rpm_error",
    "pwm_eq",
    "duty_10bit",
    "acs_v",
    "current_a",
    "control_mode",
    "state",
    "fault_type",
]

NUMERIC_COLUMNS = [
    "sample_index",
    "time_ms_raw",
    "time_ms_zero",
    "elapsed_ms",
    "ax_g",
    "ay_g",
    "az_g",
    "total_g",
    "rpm",
    "target_rpm",
    "rpm_error",
    "pwm_eq",
    "duty_10bit",
    "acs_v",
    "current_a",
    "state",
]

LABEL_MAP = {
    0: "normal",
    1: "unbalance",
    2: "misalignment",
    3: "looseness",
}

LABEL_NAME_TO_ID = {
    "normal": 0,
    "unbalance": 1,
    "misalignment": 2,
    "looseness": 3,
}

EXPECTED_STATE_BY_LABEL = {
    "normal": 0,
    "unbalance": 1,
    "misalignment": 2,
    "looseness": 3,
}

EXPECTED_FAULT_BY_LABEL = {
    "normal": "normal",
    "unbalance": "unbalance",
    "misalignment": "misalignment",
    "looseness": "looseness",
}


# ============================================================
# 3. Label validation
# ============================================================

def get_label_from_filename(csv_name: str):
    name = csv_name.lower()

    if name.startswith("realtime"):
        return None, None

    if name.startswith("normal_"):
        return 0, "normal"

    if name.startswith("unbalance_"):
        return 1, "unbalance"

    if name.startswith("misalignment_"):
        return 2, "misalignment"

    if name.startswith("looseness_"):
        return 3, "looseness"

    return None, None


def normalize_fault_type(x):
    return str(x).strip().lower()


def validate_csv_label(df: pd.DataFrame, csv_path: Path, filename_label_id: int, filename_label_name: str):
    state_values = pd.to_numeric(df["state"], errors="coerce").dropna().astype(int)
    fault_values = df["fault_type"].astype(str).str.strip().str.lower()

    if len(state_values) == 0:
        raise ValueError(f"{csv_path.name}: state column is empty.")

    if len(fault_values) == 0:
        raise ValueError(f"{csv_path.name}: fault_type column is empty.")

    expected_state = EXPECTED_STATE_BY_LABEL[filename_label_name]
    expected_fault = EXPECTED_FAULT_BY_LABEL[filename_label_name]

    most_state = int(state_values.value_counts().index[0])
    most_fault = str(fault_values.value_counts().index[0])

    if most_state != expected_state:
        raise ValueError(
            f"{csv_path.name}: filename label does not match state. "
            f"filename={filename_label_name}, expected state={expected_state}, observed dominant state={most_state}"
        )

    if most_fault != expected_fault:
        raise ValueError(
            f"{csv_path.name}: filename label does not match fault_type. "
            f"filename={filename_label_name}, expected fault_type={expected_fault}, observed dominant fault_type={most_fault}"
        )


# ============================================================
# 4. CSV loading and schema validation
# ============================================================

def get_usable_csv_files():
    if not DATA_DIR.exists():
        raise RuntimeError(
            f"Dataset directory not found: {DATA_DIR}\n"
            f"Training CSV files must be located under app/replay_data in this repository."
        )

    csv_files = sorted(DATA_DIR.glob("*.csv"))

    usable = []

    for path in csv_files:
        label_id, label_name = get_label_from_filename(path.name)

        if label_id is not None:
            usable.append(path)

    return usable


def read_current_csv(csv_path: Path):
    label_id, label_name = get_label_from_filename(csv_path.name)

    if label_id is None:
        raise ValueError(f"{csv_path.name}: filename does not match a supported training sample.")

    df = pd.read_csv(csv_path, comment="#")
    df.columns = [str(c).strip() for c in df.columns]

    missing = [c for c in EXPECTED_COLUMNS if c not in df.columns]

    if missing:
        raise ValueError(
            f"{csv_path.name}: CSV schema does not match the expected format. Missing columns: {missing}"
        )

    df = df[EXPECTED_COLUMNS].copy()

    for col in NUMERIC_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["fault_type"] = df["fault_type"].astype(str).str.strip().str.lower()
    df["control_mode"] = df["control_mode"].astype(str).str.strip()

    df = df.dropna(subset=[
        "sample_index",
        "time_ms_raw",
        "time_ms_zero",
        "elapsed_ms",
        "ax_g",
        "ay_g",
        "az_g",
        "total_g",
        "rpm",
        "target_rpm",
        "rpm_error",
        "pwm_eq",
        "duty_10bit",
        "acs_v",
        "current_a",
        "state",
    ])

    df = df.reset_index(drop=True)

    validate_csv_label(df, csv_path, label_id, label_name)

    return df, label_id, label_name


def build_csv_check_row(csv_path: Path, df: pd.DataFrame, label_name: str):
    row = {
        "file": csv_path.name,
        "label": label_name,
        "rows": len(df),
        "rpm_mean": float(df["rpm"].mean()),
        "rpm_std": float(df["rpm"].std()) if len(df) > 1 else 0.0,
        "rpm_min": float(df["rpm"].min()),
        "rpm_max": float(df["rpm"].max()),
        "target_rpm_mean": float(df["target_rpm"].mean()),
        "rpm_error_mean": float(df["rpm_error"].mean()),
        "rpm_error_std": float(df["rpm_error"].std()) if len(df) > 1 else 0.0,
        "pwm_eq_mean": float(df["pwm_eq"].mean()),
        "pwm_eq_std": float(df["pwm_eq"].std()) if len(df) > 1 else 0.0,
        "acs_v_mean": float(df["acs_v"].mean()),
        "acs_v_std": float(df["acs_v"].std()) if len(df) > 1 else 0.0,
        "current_a_mean": float(df["current_a"].mean()),
        "current_a_std": float(df["current_a"].std()) if len(df) > 1 else 0.0,
        "ax_std": float(df["ax_g"].std()) if len(df) > 1 else 0.0,
        "ay_std": float(df["ay_g"].std()) if len(df) > 1 else 0.0,
        "az_std": float(df["az_g"].std()) if len(df) > 1 else 0.0,
        "total_g_std": float(df["total_g"].std()) if len(df) > 1 else 0.0,
        "state_mode": int(df["state"].mode().iloc[0]),
        "fault_type_mode": str(df["fault_type"].mode().iloc[0]),
    }

    return row


# ============================================================
# 5. Feature cache
# ============================================================

def build_dataset_signature(usable_files):
    file_infos = []

    for path in usable_files:
        stat = path.stat()
        file_infos.append({
            "name": path.name,
            "path": path.name,
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        })

    meta = {
        "data_dir": "app/replay_data",
        "window_size": WINDOW_SIZE,
        "step_size": STEP_SIZE,
        "fs": FS,
        "expected_columns": EXPECTED_COLUMNS,
        "label_map": LABEL_MAP,
        "files": file_infos,
    }

    text = json.dumps(meta, sort_keys=True, ensure_ascii=False)
    signature = hashlib.sha256(text.encode("utf-8")).hexdigest()

    return signature, meta


def load_feature_cache_if_valid(usable_files):
    if not FEATURE_CSV_PATH.exists():
        return None

    if not FEATURE_META_PATH.exists():
        return None

    current_signature, _ = build_dataset_signature(usable_files)

    try:
        with open(FEATURE_META_PATH, "r", encoding="utf-8") as f:
            saved = json.load(f)
    except Exception:
        return None

    if saved.get("signature") != current_signature:
        return None

    try:
        return pd.read_csv(FEATURE_CSV_PATH)
    except Exception:
        return None


def save_feature_cache(feature_df, usable_files):
    signature, meta = build_dataset_signature(usable_files)

    with open(FEATURE_META_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "signature": signature,
            "meta": meta,
        }, f, ensure_ascii=False, indent=2)

    feature_df.to_csv(FEATURE_CSV_PATH, index=False, encoding="utf-8-sig")


# ============================================================
# 6. Feature functions
# ============================================================

def arr(x):
    return np.asarray(x, dtype=float)


def rms(x):
    x = arr(x)

    if len(x) == 0:
        return 0.0

    return float(np.sqrt(np.mean(x ** 2)))


def peak_to_peak(x):
    x = arr(x)

    if len(x) == 0:
        return 0.0

    return float(np.max(x) - np.min(x))


def mean_abs_diff(x):
    x = arr(x)

    if len(x) < 2:
        return 0.0

    return float(np.mean(np.abs(np.diff(x))))


def max_abs_diff(x):
    x = arr(x)

    if len(x) < 2:
        return 0.0

    return float(np.max(np.abs(np.diff(x))))


def crest_factor(x):
    x = arr(x)
    d = rms(x)

    if d == 0:
        return 0.0

    return float(np.max(np.abs(x)) / d)


def zero_crossing_rate(x):
    x = arr(x)

    if len(x) < 2:
        return 0.0

    x = x - np.mean(x)
    s = np.sign(x)
    c = np.sum(s[1:] * s[:-1] < 0)

    return float(c / (len(x) - 1))


def fft_power(x):
    x = arr(x)

    if len(x) == 0:
        return np.array([0.0]), np.array([0.0])

    x = x - np.mean(x)
    y = np.fft.rfft(x)
    p = np.abs(y) ** 2
    f = np.fft.rfftfreq(len(x), d=1.0 / FS)

    return f, p


def fft_total_energy(x):
    f, p = fft_power(x)

    if len(p) == 0:
        return 0.0

    return float(np.sum(p) / len(p))


def fft_band_energy(x, low, high):
    f, p = fft_power(x)
    m = (f >= low) & (f < high)

    if not np.any(m):
        return 0.0

    return float(np.sum(p[m]) / len(p))


def dominant_frequency(x):
    f, p = fft_power(x)

    if len(p) <= 1:
        return 0.0

    p = p.copy()
    p[0] = 0.0
    idx = int(np.argmax(p))

    return float(f[idx])


def spectral_centroid(x):
    f, p = fft_power(x)
    mag = np.sqrt(p)

    if np.sum(mag) <= 0:
        return 0.0

    return float(np.sum(f * mag) / np.sum(mag))


def spectral_spread(x):
    f, p = fft_power(x)
    mag = np.sqrt(p)

    if np.sum(mag) <= 0:
        return 0.0

    c = np.sum(f * mag) / np.sum(mag)
    s = np.sqrt(np.sum(((f - c) ** 2) * mag) / np.sum(mag))

    return float(s)


def add_signal_features(features, prefix, x):
    x = arr(x)

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

    features[f"{prefix}_rms"] = rms(x)
    features[f"{prefix}_centered_rms"] = rms(centered)
    features[f"{prefix}_ptp"] = peak_to_peak(x)
    features[f"{prefix}_crest_factor"] = crest_factor(centered)
    features[f"{prefix}_zcr"] = zero_crossing_rate(centered)
    features[f"{prefix}_mean_abs_diff"] = mean_abs_diff(x)
    features[f"{prefix}_max_abs_diff"] = max_abs_diff(x)

    features[f"{prefix}_fft_total_energy"] = fft_total_energy(x)
    features[f"{prefix}_fft_0_5hz"] = fft_band_energy(x, 0.0, 5.0)
    features[f"{prefix}_fft_5_15hz"] = fft_band_energy(x, 5.0, 15.0)
    features[f"{prefix}_fft_15_30hz"] = fft_band_energy(x, 15.0, 30.0)
    features[f"{prefix}_fft_30_50hz"] = fft_band_energy(x, 30.0, 50.0)
    features[f"{prefix}_dominant_freq"] = dominant_frequency(x)
    features[f"{prefix}_spectral_centroid"] = spectral_centroid(x)
    features[f"{prefix}_spectral_spread"] = spectral_spread(x)


def safe_corr(a, b):
    a = arr(a)
    b = arr(b)

    if len(a) < 2 or len(b) < 2:
        return 0.0

    if np.std(a) == 0 or np.std(b) == 0:
        return 0.0

    return float(np.corrcoef(a, b)[0, 1])


# ============================================================
# 7. Window feature extraction
# ============================================================

def extract_features_from_window(w: pd.DataFrame):
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

    features = {}

    add_signal_features(features, "ax", ax)
    add_signal_features(features, "ay", ay)
    add_signal_features(features, "az", az)
    add_signal_features(features, "total_g", total_g)

    add_signal_features(features, "vib_ax", vib_ax)
    add_signal_features(features, "vib_ay", vib_ay)
    add_signal_features(features, "vib_az", vib_az)
    add_signal_features(features, "vib_total", vib_total)

    add_signal_features(features, "rpm", rpm)
    add_signal_features(features, "rpm_error", rpm_error)
    add_signal_features(features, "pwm_eq", pwm_eq)
    add_signal_features(features, "duty_10bit", duty_10bit)
    add_signal_features(features, "acs_v", acs_v)
    add_signal_features(features, "current_a", current_a)

    features["target_rpm_mean"] = float(np.mean(target_rpm))
    features["target_rpm_std"] = float(np.std(target_rpm))

    features["current_abs_mean"] = float(np.mean(np.abs(current_a)))
    features["current_abs_std"] = float(np.std(np.abs(current_a)))
    features["current_abs_max"] = float(np.max(np.abs(current_a)))
    features["current_abs_rms"] = rms(np.abs(current_a))

    features["vib_total_rms_over_current_abs_mean"] = float(
        rms(vib_total) / (np.mean(np.abs(current_a)) + 1e-9)
    )

    features["vib_total_rms_over_rpm_mean"] = float(
        rms(vib_total) / (np.mean(np.abs(rpm)) + 1e-9)
    )

    features["current_abs_mean_over_pwm_mean"] = float(
        np.mean(np.abs(current_a)) / (np.mean(np.abs(pwm_eq)) + 1e-9)
    )

    features["rpm_mean_over_pwm_mean"] = float(
        np.mean(rpm) / (np.mean(np.abs(pwm_eq)) + 1e-9)
    )

    features["xy_corr"] = safe_corr(vib_ax, vib_ay)
    features["xz_corr"] = safe_corr(vib_ax, vib_az)
    features["yz_corr"] = safe_corr(vib_ay, vib_az)

    features["ax_current_corr"] = safe_corr(vib_ax, current_a)
    features["ay_current_corr"] = safe_corr(vib_ay, current_a)
    features["az_current_corr"] = safe_corr(vib_az, current_a)
    features["total_current_corr"] = safe_corr(vib_total, current_a)

    features["rpm_current_corr"] = safe_corr(rpm, current_a)
    features["rpm_vib_total_corr"] = safe_corr(rpm, vib_total)

    return features


# ============================================================
# 8. Process one CSV file
# ============================================================

def process_one_csv(csv_path: Path):
    df, label_id, label_name = read_current_csv(csv_path)

    check_row = build_csv_check_row(csv_path, df, label_name)

    if len(df) < WINDOW_SIZE:
        print(f"Insufficient data length: {csv_path.name}, rows={len(df)}")
        return [], check_row

    rows = []

    for start in range(0, len(df) - WINDOW_SIZE + 1, STEP_SIZE):
        end = start + WINDOW_SIZE
        w = df.iloc[start:end]

        f = extract_features_from_window(w)

        f["label"] = label_id
        f["label_name"] = label_name
        f["source_file"] = csv_path.name
        f["source_path"] = csv_path.name
        f["window_start"] = start
        f["window_end"] = end

        rows.append(f)

    print(f"Processed: {csv_path.name}, label={label_name}, windows={len(rows)}")

    return rows, check_row


# ============================================================
# 9. Build the full feature table
# ============================================================

usable_files = get_usable_csv_files()

print()
print("Data directory")
print("========================================")
print(DATA_DIR)
print("========================================")

print()
print("CSV files used")
print("========================================")

for p in usable_files:
    _, ln = get_label_from_filename(p.name)
    print(p.name, "->", ln)

print("========================================")
print("Number of files used:", len(usable_files))

if len(usable_files) < 2:
    raise RuntimeError("Too few usable CSV files for training.")

feature_df = load_feature_cache_if_valid(usable_files)

if feature_df is not None:
    print()
    print("Using feature cache:", FEATURE_CSV_PATH)
else:
    print()
    print("Computing features...")

    all_rows = []
    check_rows = []

    for p in usable_files:
        try:
            rows, check_row = process_one_csv(p)
            all_rows.extend(rows)

            if check_row is not None:
                check_rows.append(check_row)

        except Exception as e:
            print()
            print("CSV processing failed:", p.name)
            print("Reason:", e)
            print()

    if len(check_rows) > 0:
        check_df = pd.DataFrame(check_rows)
        check_df.to_csv(CSV_CHECK_CSV_PATH, index=False, encoding="utf-8-sig")
        print("Saved CSV schema report:", CSV_CHECK_CSV_PATH)

    feature_df = pd.DataFrame(all_rows)

    if feature_df.empty:
        raise RuntimeError("No training features were generated.")

    save_feature_cache(feature_df, usable_files)
    print("Saved features:", FEATURE_CSV_PATH)

print()
print("Total windows:", len(feature_df))
print("Windows by class")
print(feature_df["label_name"].value_counts())

present_labels = sorted(feature_df["label"].astype(int).unique().tolist())
present_label_names = [LABEL_MAP[i] for i in present_labels]

print()
print("Training classes:", present_label_names)

if len(present_labels) < 2:
    raise RuntimeError("Fewer than two trainable classes are available.")

file_count_by_label = feature_df[["source_file", "label_name"]].drop_duplicates()["label_name"].value_counts()

print()
print("Files by class")
print(file_count_by_label)


# ============================================================
# 10. Training data
# ============================================================

drop_cols = [
    "label",
    "label_name",
    "source_file",
    "source_path",
    "window_start",
    "window_end",
]

feature_columns = [c for c in feature_df.columns if c not in drop_cols]

X_all = feature_df[feature_columns].replace([np.inf, -np.inf], np.nan).fillna(0.0)
y_all = feature_df["label"].astype(int)
groups_all = feature_df["source_file"]


# ============================================================
# 11. Candidate models
# ============================================================

models = {
    "ExtraTrees_fast": ExtraTreesClassifier(
        n_estimators=260,
        random_state=42,
        class_weight="balanced",
        max_features="sqrt",
        min_samples_leaf=1,
        n_jobs=-1,
    ),
    "RandomForest_fast": RandomForestClassifier(
        n_estimators=220,
        random_state=42,
        class_weight="balanced",
        max_features="sqrt",
        min_samples_leaf=1,
        n_jobs=-1,
    ),
}


# ============================================================
# 12. Prediction and file-level decision
# ============================================================

def clone_model(model):
    return copy.deepcopy(model)


def predict_with_proba(model, X):
    pred = model.predict(X).astype(int)
    proba = model.predict_proba(X)
    classes = list(model.classes_)

    prob_df = pd.DataFrame(index=range(len(X)))

    for label_id in LABEL_MAP.keys():
        col = f"prob_{LABEL_MAP[label_id]}"

        if label_id in classes:
            idx = classes.index(label_id)
            prob_df[col] = proba[:, idx]
        else:
            prob_df[col] = 0.0

    return pred, prob_df


def decide_file_label(window_pred, prob_df):
    window_pred = np.asarray(window_pred, dtype=int)

    labels, counts = np.unique(window_pred, return_counts=True)
    max_count = int(np.max(counts))
    candidates = labels[counts == max_count]

    if len(candidates) == 1:
        final = int(candidates[0])
    else:
        best_label = None
        best_prob = -1.0

        for label_id in candidates:
            col = f"prob_{LABEL_MAP[int(label_id)]}"
            mean_prob = float(prob_df[col].mean())

            if mean_prob > best_prob:
                best_prob = mean_prob
                best_label = int(label_id)

        final = best_label

    ratio = float(np.mean(window_pred == final))
    mean_prob = float(prob_df[f"prob_{LABEL_MAP[final]}"].mean())

    return final, ratio, mean_prob


# ============================================================
# 13. Leave-One-File-Out
# ============================================================

def leave_one_file_out(model_name, base_model):
    file_rows = []
    window_rows = []

    unique_files = sorted(groups_all.unique())

    for i, test_file in enumerate(unique_files, start=1):
        print(f"[{model_name}] LOFO {i}/{len(unique_files)}: {test_file}")

        train_mask = groups_all != test_file
        test_mask = groups_all == test_file

        X_train = X_all.loc[train_mask]
        y_train = y_all.loc[train_mask]

        X_test = X_all.loc[test_mask]
        y_test = y_all.loc[test_mask].astype(int)

        test_meta = feature_df.loc[test_mask].reset_index(drop=True)

        if y_train.nunique() < 2:
            print("Skipped: only one training class available:", test_file)
            continue

        model = clone_model(base_model)
        model.fit(X_train, y_train)

        pred, prob_df = predict_with_proba(model, X_test)

        y_true = y_test.to_numpy(dtype=int)
        true_file_label = int(y_true[0])

        file_pred, file_ratio, file_mean_prob = decide_file_label(pred, prob_df)

        file_rows.append({
            "model": model_name,
            "test_file": test_file,
            "true_label": true_file_label,
            "true_label_name": LABEL_MAP[true_file_label],
            "pred_label": file_pred,
            "pred_label_name": LABEL_MAP[file_pred],
            "file_correct": file_pred == true_file_label,
            "pred_file_ratio": file_ratio,
            "pred_file_mean_prob": file_mean_prob,
            "window_accuracy": accuracy_score(y_true, pred),
        })

        for j in range(len(pred)):
            row = {
                "model": model_name,
                "test_file": test_file,
                "source_file": test_meta.loc[j, "source_file"],
                "window_start": int(test_meta.loc[j, "window_start"]),
                "window_end": int(test_meta.loc[j, "window_end"]),
                "true_label": int(y_true[j]),
                "true_label_name": LABEL_MAP[int(y_true[j])],
                "pred_label": int(pred[j]),
                "pred_label_name": LABEL_MAP[int(pred[j])],
                "window_correct": int(pred[j]) == int(y_true[j]),
            }

            for label_id in LABEL_MAP.keys():
                label_name = LABEL_MAP[label_id]
                row[f"prob_{label_name}"] = float(prob_df.loc[j, f"prob_{label_name}"])

            window_rows.append(row)

    return pd.DataFrame(file_rows), pd.DataFrame(window_rows)


def score_model(file_df, window_df):
    if file_df.empty or window_df.empty:
        return -999.0

    file_acc = float(file_df["file_correct"].mean())
    win_acc = float(window_df["window_correct"].mean())

    file_f1 = f1_score(
        file_df["true_label"].astype(int),
        file_df["pred_label"].astype(int),
        labels=present_labels,
        average="macro",
        zero_division=0,
    )

    win_f1 = f1_score(
        window_df["true_label"].astype(int),
        window_df["pred_label"].astype(int),
        labels=present_labels,
        average="macro",
        zero_division=0,
    )

    return float(
        1.00 * file_acc
        + 0.80 * file_f1
        + 0.20 * win_acc
        + 0.10 * win_f1
    )


# ============================================================
# 14. Model selection
# ============================================================

print()
print("========================================")
print("Starting fault-detection training for the repository CSV schema")
print("========================================")
print("Required columns:", EXPECTED_COLUMNS)
print("Training data directory:", DATA_DIR)
print("Training classes:", present_label_names)
print("Current features: acs_v, current_a")
print("Label validation: filename plus state/fault_type fields inside each CSV")
print("========================================")

summary_rows = []

best_score = -999.0
best_info = None
best_file_df = None
best_window_df = None

for model_name, model in models.items():
    print()
    print("Evaluating model:", model_name)

    file_df, window_df = leave_one_file_out(model_name, model)

    if file_df.empty or window_df.empty:
        print("No validation result:", model_name)
        continue

    file_acc = float(file_df["file_correct"].mean())
    win_acc = float(window_df["window_correct"].mean())

    file_f1 = f1_score(
        file_df["true_label"].astype(int),
        file_df["pred_label"].astype(int),
        labels=present_labels,
        average="macro",
        zero_division=0,
    )

    win_f1 = f1_score(
        window_df["true_label"].astype(int),
        window_df["pred_label"].astype(int),
        labels=present_labels,
        average="macro",
        zero_division=0,
    )

    score = score_model(file_df, window_df)

    row = {
        "model": model_name,
        "file_accuracy": file_acc,
        "file_macro_f1": file_f1,
        "window_accuracy": win_acc,
        "window_macro_f1": win_f1,
        "score": score,
    }

    for label_id in present_labels:
        label_name = LABEL_MAP[label_id]
        sub = file_df[file_df["true_label"] == label_id]

        if len(sub) > 0:
            row[f"file_acc_{label_name}"] = float(sub["file_correct"].mean())
        else:
            row[f"file_acc_{label_name}"] = np.nan

    summary_rows.append(row)

    print("file_accuracy:", file_acc)
    print("file_macro_f1:", file_f1)
    print("window_accuracy:", win_acc)
    print("window_macro_f1:", win_f1)
    print("score:", score)

    if score > best_score:
        best_score = score
        best_info = {
            "model_name": model_name,
            "base_model": model,
            "file_accuracy": file_acc,
            "file_macro_f1": file_f1,
            "window_accuracy": win_acc,
            "window_macro_f1": win_f1,
            "score": score,
        }
        best_file_df = file_df.copy()
        best_window_df = window_df.copy()


if best_info is None:
    raise RuntimeError("Failed to select a best model")


# ============================================================
# 15. Save validation results
# ============================================================

summary_df = pd.DataFrame(summary_rows).sort_values("score", ascending=False)
summary_df.to_csv(SUMMARY_CSV_PATH, index=False, encoding="utf-8-sig")

best_file_df.to_csv(FILE_VALIDATION_CSV_PATH, index=False, encoding="utf-8-sig")
best_window_df.to_csv(WINDOW_VALIDATION_CSV_PATH, index=False, encoding="utf-8-sig")

file_cm = confusion_matrix(
    best_file_df["true_label"].astype(int),
    best_file_df["pred_label"].astype(int),
    labels=present_labels,
)

window_cm = confusion_matrix(
    best_window_df["true_label"].astype(int),
    best_window_df["pred_label"].astype(int),
    labels=present_labels,
)

file_cm_df = pd.DataFrame(
    file_cm,
    index=[f"actual_{LABEL_MAP[i]}" for i in present_labels],
    columns=[f"pred_{LABEL_MAP[i]}" for i in present_labels],
)

window_cm_df = pd.DataFrame(
    window_cm,
    index=[f"actual_{LABEL_MAP[i]}" for i in present_labels],
    columns=[f"pred_{LABEL_MAP[i]}" for i in present_labels],
)

file_cm_df.to_csv(FILE_CM_CSV_PATH, encoding="utf-8-sig")
window_cm_df.to_csv(WINDOW_CM_CSV_PATH, encoding="utf-8-sig")

file_report = classification_report(
    best_file_df["true_label"].astype(int),
    best_file_df["pred_label"].astype(int),
    labels=present_labels,
    target_names=[LABEL_MAP[i] for i in present_labels],
    zero_division=0,
    output_dict=True,
)

window_report = classification_report(
    best_window_df["true_label"].astype(int),
    best_window_df["pred_label"].astype(int),
    labels=present_labels,
    target_names=[LABEL_MAP[i] for i in present_labels],
    zero_division=0,
    output_dict=True,
)

file_report_df = pd.DataFrame(file_report).transpose()
window_report_df = pd.DataFrame(window_report).transpose()

file_report_df.to_csv(FILE_REPORT_CSV_PATH, encoding="utf-8-sig")
window_report_df.to_csv(WINDOW_REPORT_CSV_PATH, encoding="utf-8-sig")


# ============================================================
# 16. Retrain the selected model on all data
# ============================================================

print()
print("========================================")
print("Retraining the selected model on the full dataset")
print("========================================")
print("Selected model:", best_info["model_name"])

final_model = clone_model(best_info["base_model"])
final_model.fit(X_all, y_all)


# ============================================================
# 17. Feature importance
# ============================================================

if hasattr(final_model, "feature_importances_"):
    importance_df = pd.DataFrame({
        "feature": feature_columns,
        "importance": final_model.feature_importances_,
    }).sort_values("importance", ascending=False)

    importance_df.to_csv(FEATURE_IMPORTANCE_CSV_PATH, index=False, encoding="utf-8-sig")

    print()
    print("Top 30 features by importance")
    print(importance_df.head(30))
else:
    importance_df = pd.DataFrame(columns=["feature", "importance"])
    importance_df.to_csv(FEATURE_IMPORTANCE_CSV_PATH, index=False, encoding="utf-8-sig")


# ============================================================
# 18. Save model
# ============================================================

save_data = {
    "model": final_model,
    "model_name": best_info["model_name"],
    "feature_columns": feature_columns,
    "window_size": WINDOW_SIZE,
    "step_size": STEP_SIZE,
    "fs": FS,
    "label_map": LABEL_MAP,
    "present_labels": present_labels,
    "present_label_names": present_label_names,
    "expected_csv_columns": EXPECTED_COLUMNS,
    "decision_type": "window_majority_vote_file_decision",
    "file_accuracy": best_info["file_accuracy"],
    "file_macro_f1": best_info["file_macro_f1"],
    "window_accuracy": best_info["window_accuracy"],
    "window_macro_f1": best_info["window_macro_f1"],
    "score": best_info["score"],
    "data_dir": "app/replay_data",
    "file_confusion_matrix": file_cm,
    "window_confusion_matrix": window_cm,
}

joblib.dump(save_data, MODEL_PATH)


# ============================================================
# 19. Final output
# ============================================================

print()
print("========================================")
print("Best model selection result")
print("========================================")
print("model:", best_info["model_name"])
print("file_accuracy:", best_info["file_accuracy"])
print("file_macro_f1:", best_info["file_macro_f1"])
print("window_accuracy:", best_info["window_accuracy"])
print("window_macro_f1:", best_info["window_macro_f1"])
print("score:", best_info["score"])

print()
print("File-level Confusion Matrix")
print(file_cm_df)

print()
print("Window-level Confusion Matrix")
print(window_cm_df)

print()
print("Model comparison summary")
print(summary_df)

print()
print("========================================")
print("Artifacts saved")
print("========================================")
print("Training data directory:", DATA_DIR)
print("Model:", MODEL_PATH)
print("feature:", FEATURE_CSV_PATH)
print("feature meta:", FEATURE_META_PATH)
print("CSV schema report:", CSV_CHECK_CSV_PATH)
print("Model comparison:", SUMMARY_CSV_PATH)
print("File-level validation:", FILE_VALIDATION_CSV_PATH)
print("Window-level validation:", WINDOW_VALIDATION_CSV_PATH)
print("File confusion matrix:", FILE_CM_CSV_PATH)
print("window confusion matrix:", WINDOW_CM_CSV_PATH)
print("File classification report:", FILE_REPORT_CSV_PATH)
print("window classification report:", WINDOW_REPORT_CSV_PATH)
print("Feature importance:", FEATURE_IMPORTANCE_CSV_PATH)
print("========================================")