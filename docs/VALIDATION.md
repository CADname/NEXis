# Repository verification

The repository includes automated checks for source integrity, evaluation consistency, credential hygiene, and basic syntax.

## Source checks

The repository guard verifies that:

- no Hangul text is present in text/code files intended for the English repository;
- common private-key, access-token, local-user-path, database, and archive patterns are rejected;
- runtime caches and generated artifacts are not committed;
- required model, evidence, training, and configuration-template files are present;
- placeholder credentials remain placeholders in `.env.example`;
- internal presentation/planning language is not present in Markdown documentation.

Run:

```bash
python scripts/repository_check.py
```

## Evidence checks

The evidence validator confirms that the committed dataset and evaluation outputs agree with the stated reference metrics.

Run:

```bash
python scripts/validate_evidence.py
```

The reference dataset contains **225 recordings**, and the committed file-level validation contains **217 correct predictions out of 225**, corresponding to **96.44% file-level accuracy**.

## Syntax checks

The CI workflow also performs:

```bash
python -m py_compile app/main.py app/ai_model.py scripts/repository_check.py scripts/validate_evidence.py training/reproduce_training.py
node --check app/web/assets/app.js
node --check app/web/assets/digital_twin.js
bash -n prepare.sh
```

## Credential handling

The repository intentionally excludes live `.env` files, `secrets.h`, MQTT password files, TLS private keys, SSH material, database dumps, shell history, and deployment backup archives.

The full application still requires local administrator/database credentials, MQTT credentials, and TLS certificates at deployment time. NEXis is an engineering prototype and not a certified machinery-safety system.
