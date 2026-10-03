# NEXis evidence and claim boundary

This document separates what the repository directly demonstrates from future product directions.

## 1. Demonstrated physical system

The current reference rig is a rotating-drive testbed with:

- ESP32 DevKit-class controller
- ADXL345 accelerometer
- ACS712 current sensor
- Hall-effect RPM sensing
- BTS7960 motor driver
- DC motor, shaft, support/bearing components, and rotating disk/load hardware

The included firmware streams vibration, current, RPM/control information and accepts bounded remote motor commands.

## 2. Supplied dataset

The repository contains 225 labeled physical recordings in `app/replay_data/`.

| Label | Files |
|---|---:|
| normal | 72 |
| unbalance | 10 |
| misalignment | 63 |
| looseness | 80 |
| **total** | **225** |

The dataset is imbalanced, particularly for `unbalance`, and that limitation should be considered when interpreting the metrics.

## 3. Feature and decision pipeline

Reference configuration:

- sampling rate: 100 Hz
- window size: 256 samples
- step: 64 samples
- one window duration: 2.56 s
- engineered features: 383
- candidate estimators: RandomForest and ExtraTrees
- selected estimator: RandomForest (`n_estimators=220`, `random_state=42`, balanced class weights, sqrt feature subsampling)
- file-level decision: majority vote across window predictions; mean class probability breaks a tie

The feature set spans raw and centered vibration statistics, FFT energy/frequency features, RPM/control features, current features, ratios, and cross-signal correlations.

## 4. Validation design

The model-selection program performs **leave-one-file-out (LOFO)** validation.

For every recording:

1. hold out the entire CSV file;
2. train on windows from the remaining files;
3. predict every window in the held-out file;
4. combine those window predictions into one file-level decision;
5. repeat for all 225 files.

This prevents windows from the same held-out recording appearing in both train and test for that fold. It does not prove generalization to different machines, different sensors, different mounting conditions, or a different operating regime.

## 5. Recorded model-selection result

| Model | File accuracy | File macro-F1 | Window accuracy | Window macro-F1 |
|---|---:|---:|---:|---:|
| RandomForest_fast | **96.44%** | **97.05%** | **96.21%** | **96.85%** |
| ExtraTrees_fast | 96.00% | 95.64% | 96.17% | 95.76% |

The selected RandomForest file-level confusion matrix is:

| actual \ predicted | normal | unbalance | misalignment | looseness |
|---|---:|---:|---:|---:|
| normal | 69 | 0 | 2 | 1 |
| unbalance | 0 | 10 | 0 | 0 |
| misalignment | 5 | 0 | 58 | 0 |
| looseness | 0 | 0 | 0 | 80 |

Correct files: **217 / 225**.

Per-class file-level results are committed in `docs/evaluation/file_classification_report.csv`.

## 6. Runtime evidence

The application contains:

- MQTT ingestion for the physical device
- PostgreSQL telemetry/prediction/recording tables
- FastAPI HTTP and WebSocket APIs
- replay of bundled physical recordings
- runtime model inference after a physical-RPM eligibility check
- recording start/stop/download/delete functions
- physical motor arm/start/target/stop endpoints
- browser operations interface
- digital-twin synchronization

## 7. Claim limits

The current repository does not establish that:

- the classifier works unchanged on arbitrary unseen machinery;
- the system is a certified end-of-line quality system;
- a fixed total test cycle always completes in 2.56 seconds;
- computer vision currently validates sensor position in this code path;
- arbitrary industrial sensors are automatically discovered and normalized;
- an unseen machine can immediately receive named fault diagnosis without relevant data.

These limits keep the demonstrated result separate from broader product possibilities.

## 8. Future directions

Potential next steps, provided they are implemented and evaluated, include:

- camera-based measurement-setup verification before spin testing;
- configurable inspection recipes binding physical component, sensor stream, and optional visual ROI;
- normal-baseline anomaly detection for new assets without labeled fault data;
- generalized edge connectors beyond the current ESP32/MQTT node;
- automated workflows that explain a failed inspection or trigger follow-up engineering actions.

These items remain future directions until a corresponding implementation and validation are present.
