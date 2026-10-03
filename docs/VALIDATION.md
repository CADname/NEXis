# Public package validation

This document records the checks used to prepare the general-purpose public GitHub package.

## Source/package checks

- All operator-facing UI text, source comments/messages, documentation, and labeled repository figures are English-only.
- Kept all 225 physical replay CSV files and the sanitized bundled RandomForest model used by the application.
- Included figures that directly document the current system: sensor layout, physical fault examples, ML pipeline, and file-level confusion matrix.
- Added the path-sanitized training/evaluation source and committed evaluation outputs so the reported metric has an inspectable procedure and per-file evidence.
- Dataset filenames use the corrected measurement dates: Normal/Misalignment on 2026-10-02 and Unbalance/Looseness on 2026-10-03. Only filename/date labels were corrected; the CSV sensor payloads were not altered.

## Evaluation consistency

`python scripts/validate_evidence.py` verifies:

- exactly 225 CSV recordings;
- class counts: normal 72, unbalance 10, misalignment 63, looseness 80;
- required CSV schema and at least one 256-sample model window per file;
- file confusion matrix total 225 with 217 correct;
- the committed RandomForest metric row matches the reference values.

The reference model-selection procedure is leave-one-file-out validation. One complete recording is held out in each fold; windows from that file do not enter that fold's training data.

## Privacy/security checks

- Local workstation path metadata was removed from the bundled `.joblib` file and replaced with `app/replay_data`.
- Serial-console disclosure of `WIFI_SETUP_AP_PASSWORD` was removed from the ESP32 firmware.
- Empty/placeholder administrator credentials are rejected and `prepare.sh` rejects placeholder administrator/PostgreSQL passwords.
- `COOKIE_SECURE=true` can be enabled for HTTPS deployments.
- The public package excludes `.env`, `secrets.h`, MQTT password files, TLS private keys, SSH material, database dumps, shell history, and deployment backup archives.
- The pre-push guard checks common credential patterns, private keys, local-user paths, forbidden public artifacts, and near-GitHub-limit files.

## Syntax and smoke checks

The release is validated with:

```text
python scripts/public_repo_check.py
python scripts/validate_evidence.py
python -m py_compile app/main.py app/ai_model.py scripts/public_repo_check.py scripts/validate_evidence.py training/reproduce_training.py
node --check app/web/assets/app.js
node --check app/web/assets/digital_twin.js
bash -n prepare.sh
```

A model-load/inference smoke test is also run against one 256-sample recording window from each of the four classes. The package is then ZIP-tested for archive integrity.

## Deployment boundary

The full Docker application still requires local administrator/database credentials, MQTT credentials, and TLS certificates. Those are intentionally absent from the public package. This repository is an engineering prototype and not a certified machinery-safety system.
