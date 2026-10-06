# Security and safety notes

NEXis is an engineering prototype. Keep deployment credentials and private key material outside the repository.

## Never commit

- `.env` files with live credentials
- ESP32 `secrets.h`
- `mosquitto/passwd`
- TLS private keys or private certificate bundles
- SSH keys
- database dumps
- shell history
- deployment backups or archives
- private runtime recordings
- local Vision Edge state or baselines

The included ignore rules and `scripts/validate_repo.py` cover common accidental exposures, but staged changes should still be reviewed before pushing.

## Browser access

The application intentionally presents a direct **Physical Station / Recorded Demo** workspace selector instead of a user-login form. A public Internet deployment therefore needs an external access-control boundary, such as a trusted network, VPN, firewall allowlist, reverse-proxy authentication, or another appropriate gateway.

## MQTT

Port 1883 is intended for the private Docker network. The physical-device listener on port 8883 is the externally published MQTT endpoint and should use credentials and TLS material managed outside Git.

## Vision Edge

Set a strong `VISION_EDGE_TOKEN`. Local edge state and sensor baselines are stored outside the repository. Camera inference is a supervisory inspection function, not a certified safety function.

## Physical safety

NEXis can issue motor-control commands. It must not be used as the sole emergency-stop, interlock, guard-monitoring, or safety-rated control layer. Physical safety hardware must remain independent of the browser, network, camera, MQTT, and ESP32 application software.
