#!/usr/bin/env python3
"""Install/update session-distiller as a personal Claude Code skill.

Run from a clone of https://github.com/D-Tony2020/skill-hub :
    python skills/session-distiller/scripts/install_local.py [--dest ~/.claude/skills]
Copies the runtime files (not tests/evals) and writes a SOURCE provenance file.
User state in ~/.session-distiller (profile, ledger, runs) is never touched.
"""
import argparse, datetime, os, shutil, subprocess, sys
from pathlib import Path

NAME = "session-distiller"
SRC = Path(__file__).resolve().parent.parent
RUNTIME = ["SKILL.md", "VERSION", "CHANGELOG.md", "scripts", "references", "assets"]


def git(*a):
    try:
        return subprocess.run(["git", "-C", str(SRC), *a], capture_output=True, text=True).stdout.strip() or "unknown"
    except OSError:
        return "unknown"


def main():
    ap = argparse.ArgumentParser()
    default = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "skills"
    ap.add_argument("--dest", default=str(default), help="skills directory (default ~/.claude/skills)")
    a = ap.parse_args()
    dest = Path(os.path.expanduser(a.dest)) / NAME
    if dest.resolve() == SRC:
        print("already running from the install location; run this from the source clone"); return 1
    tmp = dest.with_name(NAME + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    for item in RUNTIME:
        s = SRC / item
        if s.is_dir():
            shutil.copytree(s, tmp / item, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        elif s.exists():
            shutil.copy2(s, tmp / item)
    (tmp / "SOURCE").write_text(
        f"repo={git('remote', 'get-url', 'origin')}\npath=skills/{NAME}\n"
        f"branch={git('rev-parse', '--abbrev-ref', 'HEAD')}\ncommit={git('rev-parse', '--short', 'HEAD')}\n"
        f"clone={SRC.parent.parent}\ninstalled_at={datetime.datetime.now().replace(microsecond=0).isoformat()}\n",
        encoding="utf-8")
    try:
        shutil.rmtree(dest, ignore_errors=False) if dest.exists() else None
        tmp.rename(dest)
    except OSError:  # Windows: a file in use blocks rename; copy over instead
        shutil.copytree(tmp, dest, dirs_exist_ok=True)
        shutil.rmtree(tmp, ignore_errors=True)
    ver = (dest / "VERSION").read_text(encoding="utf-8").strip()
    print(f"installed {NAME} {ver} -> {dest}")
    print("start a NEW Claude Code session for the change to take effect")
    return 0


if __name__ == "__main__":
    sys.exit(main())
