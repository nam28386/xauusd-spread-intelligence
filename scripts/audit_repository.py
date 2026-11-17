"""Offline allowlist/secret-pattern audit; complements manual review, not a proof."""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_SUFFIXES = {".py", ".md", ".toml", ".lock", ".json", ".yml", ".html", ".css", ".js", ".ps1"}
ALLOWED_DOTFILES = {".gitignore", ".python-version"}
PATTERNS = [
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(rb"github_pat_[A-Za-z0-9_]{30,}"),
    re.compile(rb"AKIA[A-Z0-9]{16}"),
    re.compile(rb"(?i)(?:password|api_key|access_token)\s*[:=]\s*[\"'][^\"'\s]{8,}[\"']"),
]


def main() -> None:
    result = subprocess.run(  # noqa: S603 -- fixed git command, no shell
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],  # noqa: S607
        check=True,
        capture_output=True,
        cwd=ROOT,
    )
    paths = sorted(set(p.decode() for p in result.stdout.split(b"\0") if p))
    failures = []
    for name in paths:
        path = ROOT / name
        if path.is_symlink() or not path.is_file():
            failures.append(f"non-regular file: {name}")
            continue
        if path.suffix not in ALLOWED_SUFFIXES and path.name not in ALLOWED_DOTFILES:
            failures.append(f"unexpected file type: {name}")
        if any(
            part.lower() in {"data", "datasets", "terminal", "logs", "accounts"}
            for part in path.relative_to(ROOT).parts
        ):
            failures.append(f"local data path: {name}")
        content = path.read_bytes()
        if any(pattern.search(content) for pattern in PATTERNS):
            failures.append(f"possible secret: {name}")
    if failures:
        raise SystemExit("\n".join(failures))
    print(
        f"PASS: {len(paths)} repository files audited; no prohibited artifacts or secret patterns"
    )


if __name__ == "__main__":
    main()
