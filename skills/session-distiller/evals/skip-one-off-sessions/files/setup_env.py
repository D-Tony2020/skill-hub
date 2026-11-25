"""Two sessions with nothing worth distilling: a customer-specific one-off and generic git chatter."""
import json, sys
from pathlib import Path
here = Path(__file__).resolve().parent
sys.path.insert(0, str(here))
from fixtures import Session
cwd = Path.cwd()
root = cwd / "claude" / "projects"
a = Session("dddd4444-0000-4000-8000-000000000004", "/work/line3", start="2026-11-15T09:00:00Z")
a.user("帮我算一下宏达五金产线 3 下周的换型时间表，A 型换 B 型 45 分钟，B 换 C 30 分钟")
a.tool("Bash", {"command": "python3 -c \"print(45+30)\""})
a.assistant_text("下周换型总时长 75 分钟，排在周二和周四夜班。")
a.user("好，把结果发我")
a.assistant_text("已整理：周二 A→B 45 分钟，周四 B→C 30 分钟。")
a.write(root)
b = Session("eeee5555-0000-4000-8000-000000000005", "/work/notes", start="2026-11-16T09:00:00Z")
b.user("git status 看下有啥改动")
b.tool("Bash", {"command": "git status"})
b.assistant_text("有两个文件改动。")
b.user("提交一下，信息写 update notes")
b.tool("Bash", {"command": "git commit -am 'update notes'"})
b.assistant_text("已提交。")
b.write(root)
home = cwd / "sdhome"
home.mkdir(exist_ok=True)
(cwd / "hub" / "skills").mkdir(parents=True, exist_ok=True)
(home / "config.json").write_text(json.dumps({
    "sources": [{"type": "claude-code", "path": str(root)}], "skill_hub": str(cwd / "hub"), "skill_dirs": [],
    "include_sidechains": False, "min_user_turns": 2, "digest_max_chars": 40000, "owner": "dean"}, indent=2), encoding="utf-8")
(home / "profile.md").write_text((here / "profile.md").read_text(encoding="utf-8"), encoding="utf-8")
(home / "redact.txt").write_text("宏达五金\n", encoding="utf-8")
print("env ready")
