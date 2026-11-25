#!/usr/bin/env bash
# Install/update this skill as a personal Claude Code skill so it is invoked as
# "blacklake-auto-git" in every session:  bash scripts/install_local.sh
# Works in Git Bash on Windows, Linux and macOS. Keeps ~/.blacklake-auto-git (state) untouched.
set -euo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}/blacklake-auto-git"
[ "$SRC" = "$DEST" ] && { echo "already running from $DEST"; exit 0; }
mkdir -p "$DEST"
rm -rf "$DEST.tmp" && mkdir -p "$DEST.tmp"
cp -R "$SRC/.gitattributes" "$SRC/SKILL.md" "$SRC/VERSION" "$SRC/CHANGELOG.md" "$SRC/scripts" "$SRC/references" "$SRC/evals" "$SRC/tests" "$DEST.tmp/"
rm -rf "$DEST" && mv "$DEST.tmp" "$DEST"
chmod +x "$DEST/scripts/"*.sh "$DEST/scripts/mac/"* 2>/dev/null || true
echo "installed blacklake-auto-git $(cat "$DEST/VERSION") -> $DEST"
echo "start a NEW Claude Code session and say: 用 blacklake-auto-git ..."
