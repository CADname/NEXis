# Windows Vision Edge

This folder runs the camera-side inspection process on the Windows PC connected to the local USB or integrated camera.

## Local processing

- YOLO person detection
- MediaPipe hand detection with motion/skin fallback support
- generic moving-object intrusion detection
- hazard and warning-zone evaluation
- Hall LED blink analysis
- rotor motion analysis
- ADXL345 / ACS712 / Hall-sensor mount baseline comparison
- camera discovery, selection, camera-off control, and manual refresh
- linked/mobile and virtual camera filtering before stream opening

Inference uses local camera frames. The server receives compact status data and a low-rate preview frame for the dashboard.

## Setup

1. Copy `server_url.example.txt` to `server_url.txt`.
2. Replace the placeholder with the NEXis server URL.
3. Double-click `START_NEXIS_VISION.vbs`.
4. Wait for the progress window to complete.
5. Open **Physical Station -> Vision Safety** and select the intended camera.

The launcher reuses the local Python environment under `%LOCALAPPDATA%\NEXis\VisionEdge` when it already exists. It creates the environment only when none is available. Runtime state, logs, and sensor baselines stay outside the repository.

The camera list is enumerated at startup and again only after **Refresh Cameras** is pressed. Windows friendly-name enumeration is required so linked/mobile and virtual cameras can be filtered before any stream is opened.

## Stop and diagnostics

- Run `STOP_NEXIS_VISION.vbs` to stop the local edge process.
- Use the web **Camera Off** control to release only the active camera while leaving the edge process online.
- Run `SHOW_NEXIS_VISION_LOGS.cmd` to display launcher, install, and edge logs.

## Calibration

After the camera is fixed in place:

1. define the hazard polygon;
2. define the Hall LED ROI;
3. define the rotor ROI;
4. define the ADXL345 mount ROI;
5. optionally define ACS712 and Hall-sensor mount ROIs;
6. save the setup;
7. capture the sensor baseline with the sensors correctly installed.

Recalibrate after camera movement, major lighting changes, or sensor-layout changes.
