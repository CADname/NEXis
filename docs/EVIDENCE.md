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

The evaluation is leave-one-file-out: one complete recording is held out for each fold, and windows from that recording are not mixed into training for that fold. Raw evaluation outputs are stored in `docs/evaluation/` and the reproduction program is `training/reproduce_training.py`.

These metrics describe the supplied rig, acquisition procedure, conditions, and dataset. They do not establish unchanged transfer to arbitrary machines, RPM ranges, sensor installations, or fault severities.

## Physical hardware path

The repository implements the reference path for ESP32 telemetry and control, ADXL345 vibration, ACS712 current, Hall-sensor RPM, BTS7960 drive commands, MQTT/TLS transport, FastAPI ingestion, WebSocket updates, PostgreSQL history, recording/replay, and the synchronized WebGL digital twin.

## Vision path

The Windows vision connector implements:

- person detection with YOLO;
- hand detection with MediaPipe and a motion/skin fallback;
- generic moving-object intrusion detection;
- user-defined hazard and warning zones;
- Hall LED repeated brightness-transition detection;
- rotor visual-motion detection;
- ADXL345 / ACS712 / Hall-sensor mount baseline comparison;
- camera discovery, selection, camera-off requests, and manual refresh;
- linked/mobile and virtual camera filtering before stream opening;
- persistent server configuration and sensor-baseline synchronization;
- low-rate cloud preview frames while inference remains local.

The browser receives detection boxes and status fields for person, hand, and generic motion intrusion so the operator can see which region caused a warning or danger result.

### Vision claim boundary

Sensor-mount verification detects visual change relative to a captured baseline. It is not generic sensor-object recognition. Camera movement, occlusion, or major lighting changes can trigger a change result and require recalibration.

Generic object/motion intrusion is motion-based. It is intended to flag moving intrusions in configured zones, not to classify every object category in the scene.

Person, hand, and motion detection are software pre-checks, not certified safety functions. They must not replace guards, interlocks, emergency stops, or safety-rated controllers.

## Recorded Demo path

Recorded Demo uses the repository's physical CSV recordings. It continuously replays files for the selected condition until Stop is pressed. The fixed-view digital-twin vision screen is a deterministic visualization/configuration surface rather than a camera measurement.
