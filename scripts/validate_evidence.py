#!/usr/bin/env python3
from __future__ import annotations

import csv
import math
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "replay_data"
EVAL = ROOT / "docs" / "evaluation"

EXPECTED_COUNTS = {
    "normal": 72,
    "unbalance": 10,
    "misalignment": 63,
    "looseness": 80,
}
EXPECTED_COLUMNS = [
    "sample_index", "time_ms_raw", "time_ms_zero", "elapsed_ms",
    "ax_g", "ay_g", "az_g", "total_g", "rpm", "target_rpm",
    "rpm_error", "pwm_eq", "duty_10bit", "acs_v", "current_a",
    "control_mode", "state", "fault_type",
]


def fail(msg: str) -> None:
    raise RuntimeError(msg)


def label_from_name(name: str) -> str | None:
    lower = name.lower()
    for label in EXPECTED_COUNTS:
        if lower.startswith(label + "_"):
            return label
    return None


def check_dataset() -> Counter:
    files = sorted(DATA.glob("*.csv"))
    counts: Counter[str] = Counter()
    if len(files) != sum(EXPECTED_COUNTS.values()):
        fail(f"expected 225 replay CSV files, found {len(files)}")

    for path in files:
        label = label_from_name(path.name)
        if label is None:
            fail(f"unrecognized dataset filename: {path.name}")
        counts[label] += 1

        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header != EXPECTED_COLUMNS:
                fail(f"unexpected CSV header in {path.name}")
            rows = sum(1 for _ in reader)
            if rows < 256:
                fail(f"{path.name} has only {rows} rows; at least 256 required")

    if dict(counts) != EXPECTED_COUNTS:
        fail(f"class counts differ: {dict(counts)} != {EXPECTED_COUNTS}")
    return counts



def check_evaluation_filename_alignment() -> None:
    dataset_names = {p.name for p in DATA.glob("*.csv")}

    def read_names(filename: str, columns: list[str]) -> list[dict[str, str]]:
        path = EVAL / filename
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        if not rows:
            fail(f"{filename} is empty")
        for col in columns:
            if col not in rows[0]:
                fail(f"{filename} missing column: {col}")
        return rows

    structure = read_names("csv_structure_check.csv", ["file"] )
    structure_names = {r["file"] for r in structure}
    if structure_names != dataset_names or len(structure) != len(dataset_names):
        fail("csv_structure_check.csv filenames do not match app/replay_data")

    file_rows = read_names("file_validation.csv", ["test_file"] )
    file_names = {r["test_file"] for r in file_rows}
    if file_names != dataset_names or len(file_rows) != len(dataset_names):
        fail("file_validation.csv filenames do not match app/replay_data")

    window_rows = read_names("window_validation.csv", ["test_file", "source_file"] )
    unknown = {r[c] for r in window_rows for c in ("test_file", "source_file") if r[c] not in dataset_names}
    if unknown:
        sample = sorted(unknown)[:5]
        fail(f"window_validation.csv references unknown dataset files: {sample}")

def check_file_confusion() -> tuple[int, int]:
    path = EVAL / "file_confusion_matrix.csv"
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    if len(rows) != 5 or len(rows[0]) != 5:
        fail("unexpected file confusion-matrix shape")
    matrix = []
    for row in rows[1:]:
        matrix.append([int(x) for x in row[1:]])
    total = sum(sum(r) for r in matrix)
    correct = sum(matrix[i][i] for i in range(4))
    if total != 225 or correct != 217:
        fail(f"file confusion matrix expected 217/225, found {correct}/{total}")
    return correct, total


def check_model_summary() -> None:
    path = EVAL / "model_selection_summary.csv"
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        fail("model selection summary is empty")
    rf = next((r for r in rows if r.get("model") == "RandomForest_fast"), None)
    if rf is None:
        fail("RandomForest_fast row missing from model selection summary")
    expected = {
        "file_accuracy": 0.9644444444444444,
        "file_macro_f1": 0.9705209325555351,
        "window_accuracy": 0.9620834929145922,
        "window_macro_f1": 0.9685179602150673,
    }
    for key, value in expected.items():
        actual = float(rf[key])
        if not math.isclose(actual, value, rel_tol=0, abs_tol=1e-12):
            fail(f"{key} changed: {actual} != {value}")


def main() -> int:
    try:
        counts = check_dataset()
        check_evaluation_filename_alignment()
        correct, total = check_file_confusion()
        check_model_summary()
    except Exception as exc:
        print(f"EVIDENCE CHECK: FAILED — {exc}")
        return 1

    print("EVIDENCE CHECK: PASS")
    print(f"  recordings: {sum(counts.values())} ({dict(counts)})")
    print(f"  LOFO file result: {correct}/{total} = {correct/total:.2%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
