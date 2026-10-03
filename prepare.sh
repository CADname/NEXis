#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
[[ -f .env ]] || { echo "[ERROR] Copy .env.example to .env and configure it first." >&2; exit 2; }
for key in ADMIN_PASSWORD POSTGRES_PASSWORD; do
  value="$(grep -E "^${key}=" .env | tail -n 1 | cut -d= -f2- || true)"
  [[ -n "$value" ]] || { echo "[ERROR] ${key} is missing or empty in .env." >&2; exit 2; }
  [[ "$value" != CHANGE_ME* ]] || { echo "[ERROR] ${key} still contains the CHANGE_ME placeholder." >&2; exit 2; }
done
[[ -f mosquitto/passwd ]] || { echo "[ERROR] Missing mosquitto/passwd." >&2; exit 2; }
for f in mosquitto/certs/ca.crt mosquitto/certs/server.crt mosquitto/certs/server.key; do [[ -f "$f" ]] || { echo "[ERROR] Missing $f" >&2; exit 2; }; done
mkdir -p runtime/recordings
sudo docker compose down --remove-orphans || true
sudo docker compose up -d --build
sudo docker compose ps
