# Generic hackathon demo guide

The strongest general-purpose demo is a **single end-to-end inspection story**. Do not tour every dashboard page. Show one physical unit, one controlled spin, one AI result, and the evidence behind it.

## 3-minute version

### 0:00–0:08 — Hook with the real machine

Open on the **physical rig**, not a title slide or digital twin. If possible, show the motor begin spinning and cut immediately to the result screen.

One sentence is enough:

> “This assembly can look normal from the outside and still contain a fault that only appears when it spins.”

### 0:08–0:25 — The manufacturing problem

State the inspection gap: static exterior inspection may miss dynamic assembly faults such as unbalance, shaft/coupling misalignment, or looseness.

### 0:25–0:45 — What NEXis measures

Show the physical sensor placement and name only the three inputs that matter to the story:

**vibration + motor current + RPM**

### 0:45–1:35 — Live spin inspection

Start a controlled run and keep the physical hardware visible long enough that judges can connect the moving machine to the browser telemetry.

Show this sequence clearly:

1. motor starts;
2. RPM rises;
3. live sensor data moves;
4. stable-data analysis begins;
5. diagnosis appears;
6. the result maps to **PASS candidate** or **investigate / reject**.

Make the final condition label larger and more visually important than the raw graphs.

### 1:35–2:05 — Evidence, immediately after the result

Show the three numbers that establish credibility:

- **225 physical recordings**
- **217 / 225 files correct**
- **96.44% file-level LOFO accuracy**

Then show the confusion matrix. Explain that an entire recording is held out per fold, rather than randomly mixing windows from the same recording across train and test.

### 2:05–2:35 — Engineering depth

Show one architecture view:

`ESP32 → MQTT/TLS → FastAPI → model → PostgreSQL/WebSocket → browser`

Mention the isolated CSV replay workspace only as a reproducibility feature for judges who do not have the physical rig.

### 2:35–3:00 — Expansion

End with the product direction, not an unimplemented feature demo: Vision setup verification, configurable inspection recipes, baseline anomaly detection for new assets, and generalized edge connectors.

## 5-minute version

Use the same sequence. Spend the extra two minutes on only one track-specific strength:

- **AI/ML:** feature pipeline, LOFO validation, error cases, class imbalance.
- **Hardware/Physical AI:** motor control, live sensor path, recovery behavior, actual physical test.
- **Vision:** only if the submitted branch really contains and demonstrates the setup-validation module.
- **Agent:** only if the submitted branch contains a real multi-step agent that consumes NEXis state and takes useful actions.
- **SaaS/startup:** deployment architecture, user workflow, security, pricing/business assumptions.
- **DevSecOps:** event-built CI/CD or agent automation around the NEXis repository.

## Recommended 5–8 second README / Devpost clip

If you record one short looping clip, use this exact visual story:

`rig at rest → START → RPM rises → telemetry moves → diagnosis appears`

Use the **real physical rig**. Do not replace it with a synthetic animation or digital-twin-only sequence.

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

- Do not lead with the digital twin before judges understand the physical problem.
- Do not spend most of the video explaining frameworks, model names, or dashboards.
- Do not let raw graphs visually overpower the inspection result.
- Do not call 2.56 seconds the complete inspection cycle; it is one model window after stable data is available.
- Do not present roadmap Vision/Edge/Agent capabilities as implemented unless they are in the submitted branch and visible in the demo.
- Do not claim the current classifier transfers unchanged to arbitrary unseen machines.
- Do not hide dataset imbalance or failure cases; concise disclosure improves credibility.
- Do not make sponsor technology a decorative API call. When a competition requires sponsor tooling, make it change a meaningful step in the workflow.
