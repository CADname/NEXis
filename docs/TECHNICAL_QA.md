# Technical Q&A

## What problem does NEXis solve?

NEXis provides a repeatable end-of-line spin-inspection workflow for rotating assemblies after assembly and before product release. It combines setup verification, synchronized sensor data, controlled machine state, AI diagnosis, and inspection evidence in one interface so a normal result can become a pass candidate and a detected fault can be corrected and retested.

## Which signals are used for condition diagnosis?

The classifier uses features derived from synchronized vibration, motor current, RPM, and related control/cross-signal information. Runtime acquisition is 100 Hz and the model window is 256 samples.

## Which conditions are classified?

Normal, Unbalance, Misalignment, and Fastener Looseness.

## How was the model evaluated?

The supplied evaluation uses leave-one-file-out validation over 225 physical recordings. Each held-out recording remains isolated from training for its fold.

## Does 96.44% mean the model works on every machine?

No. It is the measured file-level accuracy on the supplied rig and dataset under the documented acquisition procedure. Deployment on another machine requires validation and, where needed, retraining or recalibration.

## What does the vision system detect?

The Windows edge performs YOLO person detection, MediaPipe hand tracking, hazard-zone intersection checks, Hall LED blink detection, rotor motion detection, and sensor-mount baseline comparison.

## Is the web preview used as the AI input?

No. Camera inference is performed locally from the camera frames. The cloud preview is an operator-visibility stream and may update at a lower rate without reducing the edge inference frame source to that rate.

## How is Hall sensor activity checked visually?

The configured Hall LED ROI is monitored for repeated brightness transitions. A continuously illuminated LED is not sufficient to report a blink sequence.

## How are sensor positions checked?

The user defines ROIs for sensor mounting areas and captures a baseline while the sensors are correctly installed. The edge compares current ROI appearance against that baseline across multiple frames. A substantial sustained change is reported as changed or missing.

## Why is the Recorded Demo useful?

It provides a deterministic way to demonstrate all recorded conditions without commanding the physical motor. Matching physical recordings are selected continuously until the operator presses Stop.

## What is the fixed-view Vision Safety Demo?

It is a digital-twin-based inspection setup surface. The viewpoint is locked so hazard zones and sensor regions remain spatially stable, while machine motion and fault animation continue to follow replay RPM and condition state.

## Is NEXis a safety-rated system?

No. It is an engineering prototype. Vision and cloud software are supervisory checks and must not replace safety-rated guards, interlocks, emergency stops, or PLC safety logic.
