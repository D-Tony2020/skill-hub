"""Build a self-contained test environment in the current directory."""
import json, sys
from pathlib import Path
here = Path(__file__).resolve().parent
sys.path.insert(0, str(here))
import fixtures
cwd = Path.cwd()
fixtures.build(cwd / "claude" / "projects")
hub = cwd / "hub" / "skills" / "blacklake-auto-git"
hub.mkdir(parents=True, exist_ok=True)
(hub / "SKILL.md").write_text("---\nname: blacklake-auto-git\ndescription: 经内网 Mac 气闸向公司 GitLab 推代码、建 MR\n---\n", encoding="utf-8")
home = cwd / "sdhome"
home.mkdir(exist_ok=True)
(home / "config.json").write_text(json.dumps({
    "sources": [{"type": "claude-code", "path": str(cwd / "claude" / "projects")}],
    "skill_hub": str(cwd / "hub"), "skill_dirs": [], "include_sidechains": False,
    "min_user_turns": 2, "digest_max_chars": 40000, "owner": "dean"}, ensure_ascii=False, indent=2), encoding="utf-8")
(home / "profile.md").write_text((here / "profile.md").read_text(encoding="utf-8"), encoding="utf-8")
(home / "redact.txt").write_text("大欣精密\n", encoding="utf-8")
print("env ready: export SD_HOME=$PWD/sdhome CLAUDE_CONFIG_DIR=$PWD/claude")
