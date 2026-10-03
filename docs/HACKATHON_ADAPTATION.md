# Adapting NEXis to different hackathon tracks

Keep the **core project identity** stable:

> NEXis is a physical end-of-line spin-inspection prototype that uses vibration, current, and RPM to identify four conditions on a validated rotating-drive testbed.

Then add only the event-specific work required by the track. This prevents the project from turning into a collection of unrelated features.

## Profile A — General AI / real-world impact

Lead with:

- clear manufacturing problem;
- real hardware and real data;
- 225 physical recordings;
- LOFO evaluation and failure cases;
- complete physical-to-browser workflow;
- target user: production/process/equipment/quality engineer.

Best new work: better test automation, clearer PASS/REJECT workflow, inspection reports, repeatability tests, or model robustness evaluation.

## Profile B — Physical AI / IoT / robotics

Lead with the physical loop:

`real sensors → edge device → live decision → controlled physical system`

Best new work: automatic test sequencing, hardware-state reasoning, sensor-health checks, robust offline/edge behavior, or a sponsor model that reasons from live machine state and produces a real action.

Avoid a “scripted hardware video only” submission. Make the live input visibly affect the system.

## Profile C — Agent / LLM

Do **not** replace the proven sensor classifier with an LLM. Put an agent above the deterministic inspection core.

A meaningful agent can:

1. read the latest diagnosis and supporting sensor evidence;
2. inspect test history;
3. decide whether a retest or engineering review is required;
4. generate a concise traceable explanation;
5. invoke permitted actions such as creating a report, selecting a replay, or proposing the next diagnostic step.

The agent should perform a real multi-step workflow. A chatbot that simply restates the class label is weak.

## Profile D — Computer vision

Vision should protect measurement validity or automate a visual inspection step, not compete with the sensor diagnosis for the same role.

High-value direction:

`Vision pre-check → confirm sensor/fixture/setup validity → allow spin test → sensor AI diagnosis`

For a vision-focused event, provide:

- a perception-to-decision-to-action diagram;
- reproducible test inputs;
- success/failure cases;
- evidence that the vision output actually changes a later decision or test action;
- an explicit human-control/safety boundary.

Only claim this after the submitted branch contains the implementation.

## Profile E — DevSecOps / software-engineering automation

Keep NEXis as the real application under test and make the event-built contribution the software-delivery automation around it.

Useful additions:

- agentic test generation;
- secret/security scanning;
- container build and deployment verification;
- simulated telemetry regression tests;
- automated recovery or issue creation after failed validation;
- traceable release evidence.

Clearly separate the base NEXis application from the event-built DevSecOps layer.

## Profile F — SaaS / startup / enterprise

Lead with one concrete wedge: **end-of-line rotating-module inspection**. Then explain how the architecture can become a configurable multi-station product.

Add evidence around:

- onboarding and station setup;
- tenant/site/device model;
- role-based access;
- audit/history/reporting;
- deployment reliability;
- data retention and privacy;
- pricing or cost model;
- path from one station to multiple assets.

Do not lead with “works with any machine.” Start with the validated station and show the expansion path.

## Profile G — Automation / productivity

Frame NEXis as reducing a manual inspection/diagnostic workflow:

`assemble → run → capture → diagnose → record result`

Strong additions include automatic report generation, serial-number traceability, repeatable recipes, operator guidance, or integration into a quality workflow.

## Universal rules for adapting the project

- This general repository intentionally does not add a project-wide open-source license. If a specific event explicitly requires one, decide that separately for the event-specific submission branch/repository after reviewing the event rules and the permissions you want to grant.
- Keep the validated spin-test core visible.
- Add one event-specific layer with a measurable purpose.
- Make sponsor/tool usage technically meaningful when required.
- Show an end-to-end working flow, not disconnected features.
- Include reproducible evidence and failure handling.
- Separate implemented features from roadmap features.
- If the event asks for contribution boundaries, disclose the base repository and event-period additions precisely.
- If rules require all submitted work to be created during the event, follow that requirement exactly.
