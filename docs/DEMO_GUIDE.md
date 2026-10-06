# Demo guide

The strongest demonstration combines the real machine, the live inspection UI, Vision Safety, and Recorded Demo without mixing their claims.

## Recommended 3-minute flow

### 0:00–0:20 — Show the physical rig

Start with the actual motor/shaft assembly and sensor placement. State the problem in one sentence:

> A rotating assembly can pass a static check and still contain a dynamic fault that only appears under rotation. NEXis is designed to catch that fault during final inspection before product release.

### 0:20–0:55 — Vision pre-check

Open **Physical Station → Vision Safety**.

Show:

- camera connection;
- hazard-zone setup;
- person and hand status;
- Hall sensor LED blink status;
- rotor motion status;
- ADXL345 / ACS712 / Hall-sensor mount status.

The cloud preview may update slower than the camera itself. Explain that inference runs on the local edge process and only status plus a low-rate preview are synchronized to the server.

### 0:55–1:40 — Controlled spin inspection

Start the physical motor only after the normal physical safety checks are complete.

Show this sequence:

1. target RPM is set;
2. actual RPM rises;
3. vibration/current/RPM update together;
4. the AI operating-condition gate becomes active;
5. class probabilities and diagnosis appear;
6. the digital twin follows actual RPM and diagnosed condition.

### 1:40–2:10 — Validation evidence

Show the concise evidence:

- 225 physical recordings;
- 217 / 225 correct LOFO files;
- 96.44% file-level accuracy;
- confusion matrix and class-level recall.

Explain that LOFO holds out an entire recording per fold.

### 2:10–2:45 — Recorded Demo

Switch to **Recorded Demo** and choose a condition. Playback continues across matching recordings until Stop is pressed.

Open **Vision Safety Demo**. Show the fixed digital-twin inspection viewpoint and saved hazard/sensor regions. The camera view is intentionally locked, while the machine continues to animate from replay state:

- rotor rotates with RPM;
- Hall LED pulses;
- unbalance, misalignment, and looseness have distinct visual behavior.

### 2:45–3:00 — Close

Show the architecture once:

`Sensors / camera → edge → MQTT / FastAPI → AI → database / WebSocket → inspection UI + digital twin`

End on the production decision: pass candidate, or inspect/correct/retest. Do not end on a framework list.

## Presentation accuracy

Use these distinctions consistently:

- **Physical Station** is connected to the real rig and can issue motor-control commands.
- **Recorded Demo** replays physical CSV recordings and cannot command the motor.
- **Physical Vision Safety** performs real camera inference on the local Windows edge.
- **Vision Safety Demo** uses a fixed digital-twin view for deterministic demonstration of the setup workflow.
- The 2.56-second value is one AI analysis window, not the total duration of a complete spin-test cycle.
- NEXis is not a certified machine-safety system.
