# Evidence and claim boundary

This document states what the repository directly demonstrates and where the evidence stops.

## Sensor-based condition diagnosis

The repository contains 225 physical CSV recordings from the rotating test rig and the model used by the application.

| Condition | Physical recordings | LOFO file-level recall |
|---|---:|---:|
| Normal | 72 | 95.83% |
| Unbalance | 10 | 100.00% |
| Misalignment | 63 | 92.06% |
| Fastener Looseness | 80 | 100.00% |
| **Total** | **225** | — |

Recorded evaluation summary:

| Metric | Result |
|---|---:|
| Correct LOFO files | 217 / 225 |
| File-level accuracy | 96.44% |
| File-level macro-F1 | 97.05% |
| Window-level accuracy | 96.21% |
| Window-level macro-F1 | 96.85% |
| Sampling frequency | 100 Hz |
| Window size | 256 samples |
| Window duration | 2.56 s |
| Window step | 64 samples |
| Engineered features | 383 |
| Selected estimator | RandomForest, 220 trees |

The evaluation is leave-one-file-out: one complete recording is held out for each fold, and windows from that recording are not mixed into training for that fold.

Raw evaluation outputs are stored in `docs/evaluation/`. The reproduction program is `training/reproduce_training.py`.

### Scope of the metric

The result measures the supplied physical rig, acquisition procedure, conditions, and dataset. It does not establish that the same trained classifier transfers unchanged to every rotating machine, RPM range, sensor installation, or fault severity.

## Physical hardware path

The repository implements the complete reference path for:

- ESP32 telemetry and remote-control messages;
- ADXL345 vibration acquisition;
- ACS712 current acquisition;
- Hall-sensor RPM feedback;
- BTS7960 motor-drive commands;
- MQTT/TLS transport;
- FastAPI ingestion and WebSocket broadcast;
- PostgreSQL history;
- browser operations UI;
- recording and replay;
- synchronized WebGL digital twin.

## Vision path

The Windows vision connector implements:

- person detection with YOLO;
- hand detection with MediaPipe;
- user-defined hazard and warning zones;
- Hall LED repeated brightness-transition detection;
- rotor visual-motion detection;
- ADXL345 / ACS712 / Hall-sensor mount baseline comparison;
- camera discovery, switching, and remote camera-off requests;
- persistent server configuration and sensor-baseline workflow;
- low-rate cloud preview frames while inference remains local.

### Vision claim boundary

The sensor-mount check detects visual change relative to a captured baseline. It does not identify every sensor model in arbitrary scenes. Camera movement, occlusion, or major lighting changes can trigger a change result and require recalibration.

Person and hand detection are software pre-checks, not certified safety functions. They must not replace guards, interlocks, emergency stops, or safety-rated controllers.

## Recorded Demo path

Recorded Demo uses the repository's physical CSV recordings. It continuously replays files for the selected condition until Stop is pressed. The fixed-view digital-twin vision screen is a deterministic visualization/configuration surface, not a claim that the rendered scene is a camera measurement.

The twin animates rotor rotation and fault behavior from replay state to make the machine condition visible while preserving a fixed inspection viewpoint.
