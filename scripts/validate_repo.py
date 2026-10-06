#!/usr/bin/env python3
from __future__ import annotations

import ipaddress
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TEXT_SUFFIXES = {
    '.py', '.js', '.css', '.html', '.md', '.txt', '.yml', '.yaml', '.json',
    '.conf', '.sh', '.ps1', '.vbs', '.bat', '.cmd', '.ino', '.h', '.hpp', '.c', '.cpp', '.example',
}

FORBIDDEN_NAMES = {
    '.env', 'secrets.h', 'passwd', '.bash_history', '.zsh_history',
    'id_rsa', 'id_ed25519', 'server.key',
}
FORBIDDEN_SUFFIXES = {'.p12', '.pfx', '.jks', '.sqlite', '.sqlite3', '.db', '.tar', '.tgz', '.zip', '.7z', '.rar'}

SECRET_PATTERNS = {
    'private key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----'),
    'AWS access key': re.compile(r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b'),
    'GitHub token': re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b'),
    'API key': re.compile(r'\bsk-[A-Za-z0-9_-]{20,}\b'),
    'Windows user path': re.compile(r'(?i)\b[A-Z]:\\Users\\[^\\\r\n]+\\'),
    'Unix user path': re.compile(r'/(?:home|Users)/[^/\s]+/'),
}

HANGUL = re.compile(r'[\u3131-\u318e\uac00-\ud7a3]')
ENCODING_ARTIFACTS = {
    'unicode replacement character': '\ufffd',
    'mojibake marker â': 'â',
    'mojibake marker Ã': 'Ã',
    'mojibake marker Â': 'Â',
}
ENCODING_QQ_SUFFIXES = {'.md', '.html', '.txt'}

PROJECT_VERSION_PATH = re.compile(r'(?i)(?:^|[/_-])v?\d+_\d+_\d+(?:[/_.-]|$)')
REQUIRED = [
    'README.md',
    'SECURITY.md',
    'app/main.py',
    'app/ai_model.py',
    'app/model/multi_fault_current_csv_model.joblib',
    'app/web/index.html',
    'app/web/assets/app.js',
    'app/web/assets/digital_twin.js',
    'edge_vision/vision_edge_agent.py',
    'edge_vision/yolo11n.pt',
    'edge_vision/README.md',
    'firmware/NEXis_ESP32_Physical/NEXis_ESP32_Physical.ino',
    'firmware/NEXis_ESP32_Physical/secrets.example.h',
    'training/reproduce_training.py',
    'docs/EVIDENCE.md',
    'docs/ARCHITECTURE.md',
    'docs/DEMO_GUIDE.md',
    'docs/TECHNICAL_QA.md',
    'docs/VALIDATION.md',
    'docs/images/vision_safety_demo.png',
]


def is_text(path: Path) -> bool:
    return path.name in {'.gitignore', '.dockerignore', 'Dockerfile'} or path.suffix.lower() in TEXT_SUFFIXES


def main() -> int:
    failures: list[str] = []

    for rel_s in REQUIRED:
        if not (ROOT / rel_s).exists():
            failures.append(f'missing required file: {rel_s}')

    forbidden_old_paths = [
        ROOT / '.github/workflows/repository-check.yml',
        ROOT / 'scripts/repository_check.py',
    ]
    for p in forbidden_old_paths:
        if p.exists():
            failures.append(f'unexpected repository helper: {p.relative_to(ROOT)}')
    firmware_root = ROOT / 'firmware'
    if firmware_root.exists():
        for p in firmware_root.iterdir():
            if p.is_dir() and re.search(r'(?i)(?:^|[_-])v?\d+[_-]\d+(?:[_-]\d+)?(?:$|[_-])', p.name):
                failures.append(f'versioned firmware path: {p.relative_to(ROOT)}')

    for path in ROOT.rglob('*'):
        if not path.is_file() or '.git' in path.parts:
            continue
        rel = path.relative_to(ROOT)
        rel_text = rel.as_posix()
        lower_name = path.name.lower()

        if any(part in {'__pycache__', '.pytest_cache', '.mypy_cache', '.venv', 'venv'} for part in rel.parts):
            failures.append(f'generated environment/cache committed: {rel_text}')
            continue
        if path.name in FORBIDDEN_NAMES:
            failures.append(f'forbidden credential filename: {rel_text}')
        if path.suffix.lower() in FORBIDDEN_SUFFIXES or lower_name.endswith(('.tar.gz', '.tar.bz2', '.tar.xz')):
            failures.append(f'archive/database artifact committed: {rel_text}')
        if lower_name.endswith(('.key', '.pem')):
            failures.append(f'private credential material committed: {rel_text}')
        if path.stat().st_size >= 95 * 1024 * 1024:
            failures.append(f'file approaches GitHub 100 MB limit: {rel_text}')
        if PROJECT_VERSION_PATH.search(rel_text) and 'docs/evaluation' not in rel_text:
            failures.append(f'versioned project path: {rel_text}')

        if not is_text(path):
            continue
        try:
            text = path.read_text(encoding='utf-8-sig', errors='ignore')
        except OSError as exc:
            failures.append(f'cannot read {rel_text}: {exc}')
            continue

        if HANGUL.search(text):
            failures.append(f'non-English Hangul text: {rel_text}')
        for label, marker in ENCODING_ARTIFACTS.items():
            if marker in text:
                failures.append(f'possible encoding artifact ({label}) in {rel_text}')
        if path.suffix.lower() in ENCODING_QQ_SUFFIXES and '??' in text:
            failures.append(f'possible encoding artifact (double question mark) in {rel_text}')
        lower = text.lower()
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                if label == 'private key' and path.suffix.lower() == '.md':
                    continue
                failures.append(f'{label} pattern in {rel_text}')

    env_path = ROOT / '.env.example'
    if env_path.exists():
        env = env_path.read_text(encoding='utf-8')
        for key in ('POSTGRES_PASSWORD', 'VISION_EDGE_TOKEN'):
            if f'{key}=CHANGE_ME_' not in env:
                failures.append(f'{key} must remain an explicit placeholder in .env.example')

    main_py = (ROOT / 'app/main.py').read_text(encoding='utf-8', errors='ignore') if (ROOT / 'app/main.py').exists() else ''
    for removed in ('/api/login', '/api/guest', 'ADMIN_PASSWORD', 'ADMIN_USER'):
        if removed in main_py:
            failures.append(f'removed authentication residue remains in app/main.py: {removed}')

    launcher = ROOT / 'edge_vision/START_NEXIS_VISION.ps1'
    if launcher.exists():
        launch_text = launcher.read_text(encoding='utf-8-sig', errors='ignore')
        for match in re.finditer(r'https?://((?:\d{1,3}\.){3}\d{1,3})', launch_text):
            try:
                if ipaddress.ip_address(match.group(1)).is_global:
                    failures.append('hard-coded public server IP in Vision Edge launcher')
            except ValueError:
                failures.append('invalid hard-coded IP in Vision Edge launcher')

    if failures:
        print('NEXIS REPOSITORY VALIDATION: FAILED')
        for item in sorted(set(failures)):
            print(f'  - {item}')
        return 1

    print('NEXIS REPOSITORY VALIDATION: PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
