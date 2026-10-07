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
    'id_rsa', 'id_ed25519', 'server.key', 'README_FIRST.txt', 'SHA256SUMS.txt',
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
    'unicode replacement character': chr(0xFFFD),
    'mojibake marker U+00E2': chr(0x00E2),
    'mojibake marker U+00C3': chr(0x00C3),
    'mojibake marker U+00C2': chr(0x00C2),
}
ENCODING_QQ_SUFFIXES = {'.md', '.html', '.txt'}
PROJECT_VERSION_PATH = re.compile(r'(?i)(?:^|[/_-])v?\d+_\d+_\d+(?:[/_.-]|$)')
RELEASE_TEXT = re.compile(r'(?i)(?:\bv\d+\.\d+(?:\.\d+)?\b|[?&]v=\d+\.\d+(?:\.\d+)?)')

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
    'edge_vision/START_NEXIS_VISION.ps1',
    'edge_vision/START_NEXIS_VISION.vbs',
    'edge_vision/INSTALL_VISION_EDGE.bat',
    'edge_vision/requirements_core.txt',
    'edge_vision/requirements_ai_optional.txt',
    'edge_vision/server_url.example.txt',
    'firmware/NEXis_ESP32_Physical/NEXis_ESP32_Physical.ino',
    'firmware/NEXis_ESP32_Physical/secrets.example.h',
    'training/reproduce_training.py',
    'docs/EVIDENCE.md',
    'docs/ARCHITECTURE.md',
    'docs/TECHNICAL_QA.md',
    'docs/VALIDATION.md',
]


def is_text(path: Path) -> bool:
    return path.name in {'.gitignore', '.dockerignore', 'Dockerfile'} or path.suffix.lower() in TEXT_SUFFIXES


def main() -> int:
    failures: list[str] = []

    for rel_s in REQUIRED:
        if not (ROOT / rel_s).exists():
            failures.append(f'missing required file: {rel_s}')

    removed_paths = [
        ROOT / 'docs/DEMO_GUIDE.md',
        ROOT / 'edge_vision/requirements.txt',
        ROOT / 'edge_vision/START_NEXIS_VISION_FALLBACK.cmd',
        ROOT / '.github/workflows/repository-check.yml',
        ROOT / 'scripts/repository_check.py',
    ]
    for p in removed_paths:
        if p.exists():
            failures.append(f'unexpected legacy/release helper: {p.relative_to(ROOT)}')

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

        if any(part in {'__pycache__', '.pytest_cache', '.mypy_cache', '.venv', 'venv', 'vision_edge_state'} for part in rel.parts):
            failures.append(f'generated environment/cache committed: {rel_text}')
            continue
        if path.name in FORBIDDEN_NAMES:
            failures.append(f'forbidden deployment/release filename: {rel_text}')
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
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                if label == 'private key' and path.suffix.lower() == '.md':
                    continue
                failures.append(f'{label} pattern in {rel_text}')
        release_scope = (rel_text == 'README.md' or rel_text == 'app/main.py' or rel_text.startswith('app/web/') or rel_text.startswith('edge_vision/') or rel_text.startswith('firmware/') or (rel_text.startswith('docs/') and path.suffix.lower() == '.md'))
        if release_scope and RELEASE_TEXT.search(text):
            failures.append(f'release/version-specific project text: {rel_text}')

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

    web_js = (ROOT / 'app/web/assets/app.js').read_text(encoding='utf-8', errors='ignore') if (ROOT / 'app/web/assets/app.js').exists() else ''
    for removed in ("/api/logout", "role==='admin'", "Only administrators can control"):
        if removed in web_js:
            failures.append(f'removed authentication residue remains in app/web/assets/app.js: {removed}')
    for implicit_locale in ('toLocaleString()', 'toLocaleTimeString()', 'toLocaleDateString()'):
        if implicit_locale in web_js:
            failures.append(f'implicit browser locale remains in app/web/assets/app.js: {implicit_locale}')
    if '/api/vision/camera/refresh' not in main_py or '/api/vision/camera/refresh' not in web_js:
        failures.append('manual Vision camera refresh is not wired through both server and browser')

    launcher = ROOT / 'edge_vision/START_NEXIS_VISION.ps1'
    if launcher.exists():
        launch_text = launcher.read_text(encoding='utf-8-sig', errors='ignore')
        for match in re.finditer(r'https?://((?:\d{1,3}\.){3}\d{1,3})', launch_text):
            try:
                if ipaddress.ip_address(match.group(1)).is_global:
                    failures.append('hard-coded public server IP in Vision Edge launcher')
            except ValueError:
                failures.append('invalid hard-coded IP in Vision Edge launcher')

    agent = ROOT / 'edge_vision/vision_edge_agent.py'
    if agent.exists():
        agent_text = agent.read_text(encoding='utf-8', errors='ignore')
        if 'return [0, 1, 2, 3, 4, 5]' in agent_text:
            failures.append('Windows anonymous camera probing fallback remains enabled')
        if 'EDGE_VERSION' in agent_text or 'edge_version' in agent_text:
            failures.append('release-specific Vision Edge version field remains')

    if failures:
        print('NEXIS REPOSITORY VALIDATION: FAILED')
        for item in sorted(set(failures)):
            print(f'  - {item}')
        return 1

    print('NEXIS REPOSITORY VALIDATION: PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
