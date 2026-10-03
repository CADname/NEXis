# NEXis demo guide

The clearest demonstration is a **single end-to-end inspection story**. Show one physical unit, one controlled spin, one AI result, and the evidence behind it.

## 3-minute version

### 0:00–0:08 — Start with the real machine

Open on the **physical rig**, not a title slide or digital twin. If possible, show the motor begin spinning and cut immediately to the result screen.

One sentence is enough:

> “This assembly can look normal from the outside and still contain a fault that only appears when it spins.”

### 0:08–0:25 — The manufacturing problem

State the inspection gap: static exterior inspection may miss dynamic assembly faults such as unbalance, shaft/coupling misalignment, or looseness.

### 0:25–0:45 — What NEXis measures

Show the physical sensor placement and name the three synchronized inputs:

**vibration + motor current + RPM**

### 0:45–1:35 — Live spin inspection

Start a controlled run and keep the physical hardware visible long enough to connect the moving machine to the browser telemetry.

Show this sequence clearly:

1. motor starts;
2. RPM rises;
3. live sensor data moves;
4. stable-data analysis begins;
5. diagnosis appears;
6. the result maps to **PASS candidate** or **investigate / reject**.

Make the final condition label larger and more visually important than the raw graphs.

### 1:35–2:05 — Evidence

Show the three key validation numbers:

- **225 physical recordings**
- **217 / 225 files correct**
- **96.44% file-level LOFO accuracy**

Then show the confusion matrix. Explain that one complete recording is held out per fold, rather than randomly mixing windows from the same recording across train and test.

### 2:05–2:35 — Engineering depth

Show one architecture view:

`ESP32 → MQTT/TLS → FastAPI → model → PostgreSQL/WebSocket → browser`

Mention the isolated CSV replay workspace as a reproducibility feature for environments without access to the physical rig.

### 2:35–3:00 — Future expansion

Close with the product direction: vision-based setup verification, configurable inspection recipes, baseline anomaly detection for new assets, and generalized edge connectors. Keep these clearly separated from the implemented spin-inspection core.

## 5-minute version

Use the same sequence. Spend the extra time on engineering depth that is already implemented: feature extraction, LOFO validation, physical motor control, live sensor transport, replay isolation, storage, security boundaries, and failure handling.

## Recommended short clip

A useful 5–8 second loop is:

`rig at rest → START → RPM rises → telemetry moves → diagnosis appears`

Use the **real physical rig**. Do not replace the physical evidence with a synthetic animation or digital-twin-only sequence.

## Recommended live sequence

1. show the rig at rest;
2. show connected sensor/edge status;
3. arm/start a controlled run;
4. show RPM rise and stable telemetry;
5. show diagnosis probabilities;
6. show the final condition prominently;
7. stop the motor;
8. use Demo replay only if additional classes must be shown quickly.

## Avoid these demo mistakes

- Do not lead with the digital twin before the physical problem is clear.
- Do not spend most of the demo explaining frameworks, model names, or dashboards.
- Do not let raw graphs visually overpower the inspection result.
- Do not call 2.56 seconds the complete inspection cycle; it is one model window after stable data is available.
- Do not present future extensions as implemented features.
- Do not claim the current classifier transfers unchanged to arbitrary unseen machines.
- Do not hide dataset imbalance or failure cases; concise disclosure improves credibility.
