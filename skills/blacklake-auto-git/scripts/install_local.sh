#!/usr/bin/env bash
# Install/update this skill as a personal Claude Code skill so it is invoked as
# "blacklake-auto-git" in every session:  bash scripts/install_local.sh
# Run it from a clone of the source repo (https://github.com/D-Tony2020/skill-hub,
# path skills/blacklake-auto-git). Works in Git Bash on Windows, Linux and macOS.
# Keeps ~/.blacklake-auto-git (state, keys, learnings) untouched.
set -euo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}/blacklake-auto-git"
[ "$SRC" = "$DEST" ] && { echo "already running from $DEST; run this from the source clone instead"; exit 1; }
mkdir -p "$(dirname "$DEST")"
rm -rf "$DEST.tmp" && mkdir -p "$DEST.tmp"
# development files (.gitattributes, evals, tests) are copied when present; release
# packages (claude.ai zip, SkillHub) do not ship them
for f in .gitattributes SKILL.md VERSION CHANGELOG.md scripts references evals tests; do
  [ -e "$SRC/$f" ] && cp -R "$SRC/$f" "$DEST.tmp/"
done
# provenance: where this copy came from, so `bag.sh update` / `bag.sh version` know the source
{
  echo "repo=$(git -C "$SRC" remote get-url origin 2>/dev/null || echo unknown)"
  echo "path=skills/blacklake-auto-git"
  echo "branch=$(git -C "$SRC" rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
  echo "commit=$(git -C "$SRC" rev-parse --short HEAD 2>/dev/null || echo unknown)"
  echo "clone=$(cd "$SRC/../.." 2>/dev/null && pwd)"
  echo "installed_at=$(date '+%Y-%m-%dT%H:%M:%S')"
} > "$DEST.tmp/SOURCE"
# replace atomically when possible; on Windows a file in use may block rm, then copy over
if ! { rm -rf "$DEST" 2>/dev/null && mv "$DEST.tmp" "$DEST"; }; then
  mkdir -p "$DEST" && cp -R "$DEST.tmp/." "$DEST/" && rm -rf "$DEST.tmp"
fi
chmod +x "$DEST/scripts/"*.sh "$DEST/scripts/mac/"* 2>/dev/null || true
echo "installed blacklake-auto-git $(cat "$DEST/VERSION" 2>/dev/null || echo "?") ($(sed -n 's/^commit=//p' "$DEST/SOURCE")) -> $DEST"
echo "start a NEW Claude Code session for the change to take effect"
