# Technical Q&A

## What problem does NEXis solve?

NEXis provides a repeatable end-of-line spin-inspection workflow for rotating assemblies after assembly and before product release. It combines setup verification, synchronized sensor data, controlled machine state, AI diagnosis, and inspection evidence in one interface.

## Which signals are used for condition diagnosis?

The classifier uses features derived from synchronized vibration, motor current, RPM, and related control/cross-signal information. Runtime acquisition is 100 Hz and the model window is 256 samples.

## Which conditions are classified?

Normal, Unbalance, Misalignment, and Fastener Looseness.

## How was the model evaluated?

The supplied evaluation uses leave-one-file-out validation over 225 physical recordings. Each held-out recording remains isolated from training for its fold.

## Does the recorded accuracy imply universal transfer?

No. The metrics apply to the supplied rig and dataset under the documented acquisition procedure. Deployment on another machine requires validation and, where needed, retraining or recalibration.

## What does the vision system detect?

The Windows edge performs person detection, hand detection, generic moving-object intrusion detection, hazard-zone evaluation, Hall LED blink detection, rotor motion detection, and sensor-mount baseline comparison.

## Are person, hand, and object boxes visible in the dashboard?

Yes. The edge sends box coordinates and zone/evidence values. The browser draws synchronized overlays on the preview for person, hand, and generic motion intrusions.

## How are cameras discovered?

Windows camera friendly names are enumerated without opening every stream. Linked/mobile and virtual camera names are filtered before opening. The list is scanned at startup and again only when the operator presses **Refresh Cameras**.

## Is the web preview used as the AI input?

No. Camera inference is performed locally from camera frames. The server preview is an operator-visibility stream and may update at a lower rate.

## How is Hall sensor activity checked visually?

The configured Hall LED ROI is monitored for repeated brightness transitions. A continuously illuminated LED is not sufficient to report a blink sequence.

## How are sensor positions checked?

The user defines ROIs for sensor mounting areas and captures a baseline while the sensors are correctly installed. The edge compares current ROI appearance against that baseline across multiple frames. A sustained change is reported as changed or missing.

## Why is Recorded Demo separated from Physical Station?

Recorded Demo provides repeatable playback of the recorded conditions without exposing physical motor-control operations. The same diagnosis and visualization concepts can be demonstrated without commanding the real rig.

## Is NEXis a safety-rated system?

No. It is an engineering prototype. Vision and cloud software are supervisory checks and must not replace safety-rated guards, interlocks, emergency stops, or PLC safety logic.
