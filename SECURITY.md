# Security notes

This repository is a public, credential-free packaging of the NEXis prototype. It is not a production-hardening guide or a safety certification.

## Never commit

Do not commit any of the following:

- `.env` or other environment files containing live credentials
- `secrets.h`
- `mosquitto/passwd`
- TLS private keys or private certificate bundles
- SSH keys
- database dumps
- shell history
- server backups or deployment archives
- runtime recordings that contain data you do not intend to publish

The included `.gitignore` and `scripts/public_repo_check.py` cover the common cases, but they are not a substitute for reviewing staged changes.

## Internet-facing deployment

The supplied Nginx configuration listens on HTTP port 80. If the service is exposed outside a trusted network, terminate HTTPS in front of Nginx or replace the proxy setup with HTTPS. Set `COOKIE_SECURE=true` for HTTPS access, use strong administrator/database/MQTT credentials, and use a properly managed CA/server certificate pair.

Port 1883 is intended only for the private Docker network. Do not publish that anonymous internal MQTT listener to the Internet. The supplied Compose file publishes only the TLS/authenticated 8883 listener for the physical ESP32.

## Device provisioning

The ESP32 Wi-Fi setup AP password belongs in `secrets.h`. The public firmware does not print that password to the serial console. Saved Wi-Fi SSIDs/passwords are device-local provisioning data and should be erased before transferring or disposing of a device.

## Physical safety

NEXis can issue motor-control commands. Treat it as a prototype supervisory layer, not as an emergency-stop, interlock, machine-guarding, or safety-rated control system. Physical safety mechanisms should remain independent of the web application, MQTT path and ESP32 software.
