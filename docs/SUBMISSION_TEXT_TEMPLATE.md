# Generic submission text template

Keep the public story consistent across GitHub, Devpost/Unstop, slides, and the demo video: **physical assembly → short spin → synchronized signals → AI diagnosis → inspection decision support**.

## Project title

**NEXis — AI End-of-Line Spin Inspection**

## Tagline

**Spin. Sense. Diagnose. Catch hidden assembly defects before shipment.**

## One-line pitch

**NEXis runs a short controlled spin test on an assembled rotating-drive module and analyzes vibration, motor current, and RPM to detect hidden dynamic assembly faults before shipment.**

## Short description

A motor/shaft/coupling assembly can look correct after assembly and still contain a fault that only appears once it rotates. NEXis captures synchronized vibration, motor current, and RPM during a controlled spin test, then classifies the run as Normal, Unbalance, Misalignment, or Looseness. The supplied evidence contains 225 physical recordings; leave-one-file-out evaluation correctly classifies 217/225 files for **96.44% file-level accuracy**.

The full prototype connects an ESP32 physical node to MQTT/TLS, FastAPI, PostgreSQL/WebSocket, and a browser operations interface so the path from **real machine motion to inspection result** can be demonstrated end to end.

## Problem

Static exterior inspection can miss assembly problems that alter the dynamics of a rotating system. Rotor unbalance, shaft/coupling misalignment, and loosened fastening may become visible only after the product begins rotating. Detecting a suspicious assembly before shipment is more useful than discovering the issue later during troubleshooting or field operation.

## Solution

NEXis turns a short controlled spin into a repeatable inspection signal:

`Assembly → controlled spin → vibration/current/RPM → AI diagnosis → inspection decision support`

It waits for a valid rotating condition, extracts engineered temporal/spectral/control features, runs four-class diagnosis, stores the result, and presents the evidence in a browser. A separate replay workspace lets judges reproduce the software path without access to the physical rig.

## Evidence to surface early

- **225** physical CSV recordings
- **217 / 225** files correct
- **96.44%** file-level accuracy
- leave-one-file-out validation
- 4 conditions: Normal / Unbalance / Misalignment / Looseness
- 3 synchronized signals: vibration / current / RPM

## Technical approach

Put this after the problem, workflow, and measured evidence rather than in the opening paragraph.

- ESP32 physical sensor/control node
- ADXL345 vibration, ACS712 current, Hall RPM
- BTS7960 motor control
- MQTT/TLS device transport
- FastAPI + WebSocket application layer
- PostgreSQL telemetry/prediction/recording history
- RandomForest model using 383 engineered features
- browser operations UI and digital twin
- Docker Compose deployment

## Honest limitation

The current classifier is validated on the supplied reference testbed. It is not presented as a zero-shot universal fault classifier for arbitrary unseen machinery. A complete spin inspection also includes spin-up and stabilization; **2.56 seconds is the model window, not a claimed fixed total cycle time**.

## Roadmap

Keep roadmap after current evidence:

- Vision-assisted measurement-setup verification
- configurable inspection recipes
- normal-baseline anomaly detection for unseen assets
- generalized edge connectors
- event-specific agent / cloud / DevSecOps layers when they are genuinely implemented

## Event-specific section

Add only what you actually built for that event:

`<sponsor model / agent / vision module / DevSecOps automation / cloud deployment / SaaS workflow>`

Explain exactly where it enters the NEXis workflow and what measurable capability it adds. Do not rename an unchanged NEXis core to imitate the sponsor theme.
