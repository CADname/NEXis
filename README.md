<p align="center">
  <img src="app/web/assets/nexis_logo.png" alt="NEXis" width="360">
</p>

# NEXis - AI End-of-Line Inspection for Rotating Assemblies

<p align="center">
  <strong>Spin. Sense. See. Diagnose.</strong><br>
  A short controlled trial run before shipment to catch hidden dynamic faults that static inspection can miss.
</p>

<p align="center">
  <a href="http://nexisai.duckdns.org"><strong>Live Demo</strong></a>
  &nbsp;·&nbsp;
  <a href="https://youtu.be/6Vdj4-uL7Y0"><strong>Demo Video</strong></a>
  &nbsp;·&nbsp;
  <a href="https://github.com/CADname/NEXis/actions/workflows/ci.yml"><strong>CI</strong></a>
</p>

<p align="center">
  <img src="docs/images/nexis_hero.png" alt="NEXis physical inspection platform" width="920">
</p>

## The problem

Final inspection often checks whether a product is assembled correctly while it is stationary. For rotating assemblies, that can miss faults that appear only when the machine actually runs: **unbalance, misalignment, looseness, abnormal vibration, or other dynamic behavior**.

A product can therefore look acceptable at rest and still reveal a problem only after it starts rotating.

## The solution

**NEXis performs a short controlled trial run immediately before shipment.** During that run, it synchronously measures vibration, motor current, and RPM, then uses machine learning to classify the operating condition. A local vision system verifies the inspection area, moving intrusions, rotor motion, Hall-sensor LED activity, and sensor mounting conditions.

The result is one browser-based inspection workflow for:

**setup verification -> controlled spin test -> synchronized sensing -> AI diagnosis -> visual evidence -> pass candidate or inspect/correct/retest**

## Evidence at a glance

| Evidence | Result |
|---|---:|
| Physical recordings | **225** |
| Correct LOFO files | **217 / 225** |
| File-level accuracy | **96.44%** |
| File-level macro-F1 | **97.05%** |
| Conditions | **4** |
| Sampling rate | **100 Hz** |
| Window size | **256 samples / 2.56 s** |
| Classifier | **RandomForest, 220 trees** |

The evaluation uses **leave-one-file-out (LOFO)** validation so windows from the held-out recording never enter training for that fold. Metrics are scoped to the supplied rig, acquisition procedure, and dataset.

## Watch the physical demo

<p align="center">
  <a href="https://youtu.be/6Vdj4-uL7Y0">
    <img src="https://img.youtube.com/vi/6Vdj4-uL7Y0/maxresdefault.jpg" alt="Watch the NEXis demo video" width="900">
  </a>
</p>

<p align="center">
  <a href="https://youtu.be/6Vdj4-uL7Y0"><strong>Watch the demo on YouTube</strong></a>
</p>

## How NEXis works

1. **Verify the setup** — confirm the hazard zone, camera view, rotor ROI, Hall LED ROI, and sensor-mount ROIs.
2. **Run a short controlled spin test** — command and monitor the rotating test rig through the Physical Station workspace.
3. **Capture synchronized signals** — ADXL345 vibration, ACS712 motor current, and Hall-sensor RPM are streamed through ESP32.
4. **Diagnose the operating condition** — the RandomForest model classifies Normal, Unbalance, Misalignment, or Fastener Looseness.
5. **Check visual evidence** — local edge vision evaluates person/hand intrusion, generic moving objects, rotor motion, Hall LED activity, and sensor-mount changes.
6. **Review and act** — the dashboard combines live telemetry, diagnosis, vision status, recording/history, and a synchronized digital twin.

## What makes it different

- **Designed for the final pre-shipment trial run**, not only long-term predictive maintenance.
- **Detects faults under motion**, where static inspection can miss dynamic problems.
- **Combines multiple physical signals** instead of relying on vibration alone.
- **Adds local machine vision** for inspection-area and setup verification.
- **Connects the full physical path** from sensors and motor control to cloud ingestion, AI inference, storage, browser UI, and digital twin.
- **Includes reproducible evidence**: physical CSV recordings, training code, model artifact, raw evaluation outputs, and CI validation.

## Physical inspection stack

| Layer | Implementation |
|---|---|
| Vibration | ADXL345, 3-axis, 100 Hz |
| Motor current | ACS712 |
| Rotational speed | Hall sensor RPM feedback |
| Motor drive | ESP32 + BTS7960 |
| Device transport | MQTT / TLS |
| Backend | FastAPI + WebSocket |
| Storage | PostgreSQL + runtime recordings |
| Diagnosis | RandomForest multi-class classifier |
| Vision | YOLO + MediaPipe + OpenCV |
| Visualization | Browser dashboard + synchronized WebGL digital twin |

## Vision Safety

Camera inference runs locally on the Windows PC connected to the camera. The server receives compact detection status and a low-rate preview frame for operator visibility.

Implemented checks include:

- **Person detection** with YOLO and danger/warning-zone evaluation.
- **Hand detection** with MediaPipe, with a motion/skin fallback when the optional hand detector is unavailable.
- **Generic moving-object intrusion detection** inside configured warning and danger regions.
- **User-defined hazard polygon** and warning margin.
- **Hall sensor LED blink detection** using repeated brightness transitions inside a configured ROI.
- **Rotor motion detection** using visual motion evidence inside a configured ROI.
- **Sensor mount verification** for ADXL345, ACS712, and Hall sensor locations using a captured visual baseline.
- **Camera selection, camera-off control, and manual camera refresh** from the browser.
- **Linked/mobile and virtual camera filtering** before a Windows camera stream is opened.
- **Persistent setup and baseline state** synchronized between the server and the edge process.

The preview overlays person, hand, and generic motion boxes with zone state and confidence/evidence values. Vision detections are supervisory inspection signals and are not safety-rated protective functions.

<p align="center">
  <img src="docs/images/vision_safety_demo.png" alt="NEXis fixed-view digital-twin vision setup with hazard zone and sensor regions" width="1000">
</p>

## Condition diagnosis

NEXis classifies four conditions:

- **Normal**
- **Unbalance**
- **Misalignment**
- **Fastener Looseness**

The repository includes the physical recordings, training code, model artifact, and evaluation outputs used by the application.

<p align="center">
  <img src="docs/images/ml_pipeline.png" alt="NEXis machine-learning pipeline" width="720">
</p>

| Metric | Recorded result |
|---|---:|
| Physical recordings | **225** |
| Correct LOFO files | **217 / 225** |
| File-level accuracy | **96.44%** |
| File-level macro-F1 | **97.05%** |
| Window-level accuracy | **96.21%** |
| Window-level macro-F1 | **96.85%** |
| Sampling frequency | **100 Hz** |
| Window size | **256 samples / 2.56 s** |
| Window step | **64 samples** |
| Engineered features | **383** |
| Classifier | **RandomForest, 220 trees** |

| Condition | Recordings | LOFO file-level recall |
|---|---:|---:|
| Normal | 72 | 95.83% |
| Unbalance | 10 | 100.00% |
| Misalignment | 63 | 92.06% |
| Fastener Looseness | 80 | 100.00% |

<p align="center">
  <img src="docs/images/confusion_matrix.png" alt="NEXis leave-one-file-out confusion matrix" width="610">
</p>


## Physical evidence

The images below document the physical test setup used for the recorded rotating-machine experiments: the sensor layout and representative fault conditions.

<p align="center">
  <img src="docs/images/sensor_layout.png" alt="NEXis sensor layout on the physical rotating-machine rig" width="48%">
  <img src="docs/images/fault_setup_examples.png" alt="Representative NEXis physical fault setups" width="48%">
</p>

The photos show the tested equipment and fault configurations; performance metrics apply to the supplied rig and acquisition procedure.

## Architecture

```mermaid
flowchart TB
    subgraph Machine[Physical rotating machine]
      ACC[ADXL345]
      CUR[ACS712]
      HALL[Hall sensor]
      MOTOR[Motor + shaft + rotor]
      CAM[USB camera]
    end

    ACC --> ESP[ESP32]
    CUR --> ESP
    HALL --> ESP
    ESP <--> DRIVER[BTS7960]
    DRIVER --> MOTOR

    ESP -->|MQTT/TLS| MQTT[Mosquitto]
    MQTT --> API[FastAPI]
    MODEL[RandomForest model] --> API
    CSV[Recorded physical runs] --> API
    API --> DB[(PostgreSQL)]
    API -->|WebSocket / HTTP| WEB[Operations UI]
    API --> TWIN[Digital twin state]
    TWIN --> WEB

    CAM --> EDGE[Windows Vision Edge]
    EDGE -->|Local inference| VISION[YOLO + MediaPipe + OpenCV]
    VISION -->|Status + preview| API
```

See [Architecture](docs/ARCHITECTURE.md), [Evidence](docs/EVIDENCE.md), and [Validation](docs/VALIDATION.md) for implementation details and claim boundaries.

## Hardware and wiring

The physical rig wiring and ESP32 GPIO assignments are documented in [Hardware Wiring](docs/HARDWARE.md).

| Signal | ESP32 pin |
|---|---:|
| Hall RPM | GPIO 32 |
| ACS712 analog output | GPIO 36 |
| BTS7960 RPWM / LPWM | GPIO 25 / GPIO 26 |
| BTS7960 R_EN / L_EN | GPIO 27 / GPIO 14 |
| ADXL345 SDA / SCL | GPIO 21 / GPIO 22 |

## Recorded Demo

NEXis separates two workspaces:

- **Physical Station** — live ESP32 telemetry, motor control, AI diagnosis, Vision Safety, recording, event history, and synchronized digital twin.
- **Recorded Demo** — repeatable replay of physical CSV recordings with the same diagnosis and visualization path, isolated from physical motor control.

Selecting a condition in Recorded Demo starts continuous playback of matching physical CSV recordings until **Stop** is pressed. The digital twin follows replay RPM and condition state.

The Vision Safety Demo uses a fixed digital-twin viewpoint so hazard and sensor regions stay spatially stable while the machine remains animated from replay data.

## Repository layout

```text
app/
  main.py                   FastAPI, MQTT, WebSocket, replay, vision, recording and control APIs
  ai_model.py               Runtime feature extraction and model inference
  model/                     Trained classifier artifact
  replay_data/               Physical CSV recordings used by Recorded Demo
  web/                       Operations UI and WebGL digital twin
edge_vision/
  vision_edge_agent.py       Local camera inference and server synchronization
  yolo11n.pt                 Person detector weights
  START_NEXIS_VISION.vbs     One-click Windows launcher
firmware/
  NEXis_ESP32_Physical/      ESP32 motor/sensor/MQTT firmware
training/
  reproduce_training.py      Training and LOFO evaluation
scripts/
  validate_repo.py           Repository cleanliness and source checks
  validate_evidence.py       Dataset/evaluation consistency validation
docs/
  ARCHITECTURE.md
  EVIDENCE.md
  HARDWARE.md
  TECHNICAL_QA.md
  VALIDATION.md
  evaluation/
  images/
```

## Server quick start

### 1. Configure environment values

```bash
cp .env.example .env
```

Set a strong PostgreSQL password and a random `VISION_EDGE_TOKEN` before deployment.

### 2. Provide MQTT credentials and certificates

Create `mosquitto/passwd` and provide:

```text
mosquitto/certs/ca.crt
mosquitto/certs/server.crt
mosquitto/certs/server.key
```

These files are intentionally excluded from Git.

### 3. Start the stack

```bash
./prepare.sh
```

The Compose stack starts FastAPI, PostgreSQL, Mosquitto, and Nginx.

## ESP32 setup

Copy `firmware/NEXis_ESP32_Physical/secrets.example.h` to `secrets.h`, then configure Wi-Fi, MQTT credentials, broker address, and the CA certificate. `secrets.h` is excluded from Git.

## Windows vision connector

1. Copy `edge_vision/server_url.example.txt` to `edge_vision/server_url.txt`.
2. Set the NEXis server URL.
3. Run `edge_vision/START_NEXIS_VISION.vbs`.
4. Open **Physical Station -> Vision Safety**.
5. Select the intended camera. Use **Refresh Cameras** only after camera hardware changes.

The launcher reuses the local Vision environment when available. Runtime state, logs, and sensor baselines are stored under `%LOCALAPPDATA%\NEXis\VisionEdge` rather than in the repository.

## Validation

```bash
python scripts/validate_repo.py
python scripts/validate_evidence.py
python -m py_compile app/main.py app/ai_model.py edge_vision/vision_edge_agent.py
node --check app/web/assets/app.js
node --check app/web/assets/digital_twin.js
```

CI runs repository, evidence, Python, JavaScript, and shell checks on pushes and pull requests.

## Safety and deployment boundary

NEXis is an engineering prototype and **not a safety-rated PLC, emergency-stop system, interlock, machine guard, or certified quality station**. Physical safety mechanisms must remain independent of browser, camera, MQTT, cloud, and ESP32 software.

The browser UI uses direct workspace selection instead of a user-login form. Internet-facing deployments should place NEXis behind an appropriate access-control layer or restrict network access to trusted users.

See [SECURITY.md](SECURITY.md) for deployment notes.
