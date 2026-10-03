# MQTT TLS certificates

This directory intentionally contains **no production certificates or private keys**.
Before deployment, place these local-only files here:

- `ca.crt`
- `server.crt`
- `server.key`

Also create `../passwd` with `mosquitto_passwd`. All of these files are ignored by Git.
