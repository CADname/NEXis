# Validation checklist

## Repository validation

Run:

```bash
python scripts/validate_repo.py
python scripts/validate_evidence.py
python -m py_compile app/main.py app/ai_model.py edge_vision/vision_edge_agent.py scripts/validate_repo.py scripts/validate_evidence.py training/reproduce_training.py
node --check app/web/assets/app.js
node --check app/web/assets/digital_twin.js
bash -n prepare.sh
```

The repository validator checks for accidental credentials, private keys, local-user paths, generated caches, deployment archives, and non-English source/UI text in project-controlled text files.

## Physical smoke test

1. Start the server stack.
2. Confirm the Physical Station receives live ESP32 telemetry at idle.
3. Confirm edge-online state and remote-control health.
4. Start a controlled run with the physical emergency-stop path available.
5. Confirm RPM, vibration, and current update together.
6. Confirm the AI gate activates only after the operating condition becomes eligible.
7. Confirm a prediction is stored and shown in the browser.
8. Stop the motor and confirm the commanded stop reaches the device.

## Vision smoke test

1. Start `edge_vision/START_NEXIS_VISION.vbs`.
2. Confirm the edge becomes online.
3. Select the intended camera from the web UI.
4. Draw and save a hazard zone.
5. Configure Hall LED, rotor, and ADXL345 ROIs; optionally configure ACS712 and Hall-sensor mount ROIs.
6. Capture a sensor baseline with the camera and sensors stationary.
7. Confirm person and hand states react to zone entry.
8. Confirm Hall LED state reacts to repeated blink transitions.
9. Confirm rotor state changes between motion and stop.
10. Move or remove a configured sensor and confirm a sustained mount change is detected.
11. Turn the camera off from the web UI and confirm the camera releases while the edge remains reachable.

## Recorded Demo smoke test

1. Enter Recorded Demo.
2. Select Normal and verify replay continues across files until Stop.
3. Repeat for Unbalance, Misalignment, and Fastener Looseness.
4. Navigate away and back while replay is active; charts must restore at the correct canvas size.
5. Open Digital Twin and confirm RPM-driven rotation and condition-specific animation.
6. Open Vision Safety Demo and confirm the viewpoint cannot orbit, pan, or zoom.
7. Configure hazard and sensor regions on the fixed view, save, reload, and reset.
8. Confirm rotor/Hall/fault animations continue while the viewpoint remains fixed.
