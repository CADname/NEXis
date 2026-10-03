# Evaluation artifacts

These files are the committed evaluation outputs associated with the training procedure documented in `training/reproduce_training.py`.

Key result for the selected `RandomForest_fast` model:

- file-level accuracy: **217 / 225 = 96.44%**
- file-level macro-F1: **97.05%**
- window-level accuracy: **96.21%**
- window-level macro-F1: **96.85%**

The validation method is **leave-one-file-out**. Each fold holds out one complete CSV recording, trains on all other recordings, and evaluates all windows from the held-out file. This avoids the most direct form of window leakage between train and test for a single recording.

Files:

- `model_selection_summary.csv` — candidate-model comparison
- `file_validation.csv` — one row per held-out recording
- `window_validation.csv` — held-out window predictions
- `file_confusion_matrix.csv` / `window_confusion_matrix.csv`
- `file_classification_report.csv` / `window_classification_report.csv`
- `feature_importance.csv` — final RandomForest feature importances
- `csv_structure_check.csv` — per-recording structure/statistics audit

These results are specific to the supplied prototype dataset and should not be interpreted as factory-wide generalization to unseen machine designs or operating regimes.
