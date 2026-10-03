#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_EXACT = {
    '.env', 'secrets.h', 'passwd', '.bash_history', '.zsh_history',
    'id_rsa', 'id_ed25519', 'server.key',
}
FORBIDDEN_SUFFIXES = {
    '.tar', '.tgz', '.p12', '.pfx', '.jks', '.sqlite', '.sqlite3', '.db',
}
ARCHIVE_DOUBLE_SUFFIXES = {'.tar.gz', '.tar.bz2', '.tar.xz'}

HANGUL_PATTERN = re.compile(r'[\u3131-\u318E\uAC00-\uD7A3]')
STALE_DOC_TERMS = (
    'leg' + 'acy', 'deprec' + 'ated', 'obs' + 'olete', 'out' + 'dated',
    'old' + ' version', 'previous' + ' version', 'older' + ' source-material',
)
INTERNAL_DOC_TERMS = (
    'hack' + 'athon', 'jud' + 'ge', 'sub' + 'mission', 'spon' + 'sor',
    'compe' + 'tition', 'event-' + 'built', 'base ' + 'repository', 'reus' + 'ing',
)
FORBIDDEN_IDENTITY = 'anc' + 'manner'

PATTERNS = {
    'private key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----'),
    'AWS access key': re.compile(r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b'),
    'GitHub token': re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b'),
    'Slack token': re.compile(r'\bxox[baprs]-[A-Za-z0-9-]{20,}\b'),
    'OpenAI-style key': re.compile(r'\bsk-[A-Za-z0-9_-]{20,}\b'),
    'Linux home path': re.compile(r'/(?:home|Users)/[^/\s]+/'),
    'Windows user path': re.compile(r'(?i)\b[A-Z]:\\Users\\[^\\\r\n]+\\'),
}

TEXT_SUFFIXES = {
    '.py', '.js', '.css', '.html', '.md', '.txt', '.yml', '.yaml', '.json',
    '.conf', '.sh', '.ps1', '.ino', '.h', '.hpp', '.c', '.cpp', '.csv',
    '.example', '.gitignore', '.dockerignore',
}


def is_text_candidate(path: Path) -> bool:
    if path.name in {'.gitignore', '.dockerignore', 'Dockerfile'}:
        return True
    return path.suffix.lower() in TEXT_SUFFIXES


def main() -> int:
    failures: list[str] = []

    for path in ROOT.rglob('*'):
        if not path.is_file() or '.git' in path.parts:
            continue
        rel = path.relative_to(ROOT)
        name = path.name
        lower = name.lower()

        if any(part in {'__pycache__', '.pytest_cache', '.mypy_cache'} for part in rel.parts):
            failures.append(f'generated cache committed: {rel}')
            continue
        if FORBIDDEN_IDENTITY in str(rel).lower():
            failures.append(f'forbidden identity in path: {rel}')
        if name in FORBIDDEN_EXACT:
            failures.append(f'forbidden filename: {rel}')
        if path.suffix.lower() in FORBIDDEN_SUFFIXES or any(lower.endswith(x) for x in ARCHIVE_DOUBLE_SUFFIXES):
            failures.append(f'forbidden repository artifact type: {rel}')
        if lower.endswith(('.key', '.pem')):
            failures.append(f'private-key/certificate material must not be committed: {rel}')
        if path.stat().st_size >= 95 * 1024 * 1024:
            failures.append(f'file is close to/exceeds GitHub 100 MB limit: {rel} ({path.stat().st_size} bytes)')

        if is_text_candidate(path):
            try:
                text = path.read_text(encoding='utf-8', errors='ignore')
            except OSError as exc:
                failures.append(f'cannot read {rel}: {exc}')
                continue
            lower_text = text.lower()
            if FORBIDDEN_IDENTITY in lower_text:
                failures.append(f'forbidden identity in {rel}')
            if HANGUL_PATTERN.search(text):
                failures.append(f'non-English Hangul text in {rel}')
            if path.suffix.lower() == '.md':
                for term in STALE_DOC_TERMS:
                    if term in lower_text:
                        failures.append(f'stale-version wording in {rel}: {term}')
                for term in INTERNAL_DOC_TERMS:
                    if term in lower_text:
                        failures.append(f'internal presentation wording in {rel}: {term}')
            for label, pattern in PATTERNS.items():
                if pattern.search(text):
                    if label == 'private key' and path.suffix.lower() == '.md':
                        continue
                    failures.append(f'{label} pattern in {rel}')

    required = [
        ROOT / '.env.example',
        ROOT / 'firmware/NEXis_ESP32_AWS_Physical_v1_4_0/secrets.example.h',
        ROOT / 'app/model/multi_fault_current_csv_model.joblib',
        ROOT / 'app/web/assets/nexis_logo.png',
        ROOT / 'docs/EVIDENCE.md',
        ROOT / 'docs/DEMO_GUIDE.md',
        ROOT / 'docs/TECHNICAL_QA.md',
        ROOT / 'training/reproduce_training.py',
        ROOT / 'docs/evaluation/model_selection_summary.csv',
    ]
    for path in required:
        if not path.exists():
            failures.append(f'missing required repository file: {path.relative_to(ROOT)}')

    env_example = (ROOT / '.env.example').read_text(encoding='utf-8')
    for key in ('ADMIN_PASSWORD', 'POSTGRES_PASSWORD'):
        if f'{key}=CHANGE_ME_' not in env_example:
            failures.append(f'{key} in .env.example must remain an explicit CHANGE_ME placeholder')

    if failures:
        print('REPOSITORY CHECK: FAILED')
        for item in failures:
            print(f'  - {item}')
        return 1

    print('REPOSITORY CHECK: PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
