# Windows Vision Edge

This folder runs the camera-side inspection process on the Windows PC connected to the USB or integrated camera.

## What runs locally

- YOLO person detection
- MediaPipe hand detection
- hazard/warning-zone checks
- Hall LED blink analysis
- rotor motion analysis
- ADXL345 / ACS712 / Hall-sensor mount baseline comparison
- camera discovery and switching

AI inference uses the local camera frames. The server receives compact status data and a low-rate preview frame for the dashboard.

## Setup

1. Copy `server_url.example.txt` to `server_url.txt`.
2. Replace the example URL with the NEXis server URL, for example `http://192.0.2.10` or your HTTPS endpoint.
3. Double-click `START_NEXIS_VISION.vbs`.
4. Wait for the progress window to complete.
5. Open **Physical Station → Vision Safety** and select the intended camera.

The launcher creates or reuses the Python environment under `%LOCALAPPDATA%\NEXis\VisionEdge` and keeps runtime state outside the repository.

## Stop

Double-click `STOP_NEXIS_VISION.vbs`, or use the camera-off control in the web UI when only the camera stream needs to be released while the edge process remains available.

## Calibration

After the camera is fixed in place:

1. define the hazard polygon;
2. define the Hall LED ROI;
3. define the rotor ROI;
4. define the ADXL345 mount ROI;
5. optionally define ACS712 and Hall-sensor mount ROIs;
6. save the setup;
7. capture the sensor baseline with the sensors correctly installed.

Recalibrate if the camera position, major lighting conditions, or sensor mounting layout changes.
