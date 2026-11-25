#!/usr/bin/env python3
"""session-distiller (sd): mine past agent sessions for reusable assets.

Deterministic half of the skill. The agent does the judging (which patterns are
worth keeping); this script does everything that must be exact and repeatable:
finding sessions, condensing and redacting transcripts into digests with stable
turn ids, cataloguing existing skills, validating and ranking candidates,
keeping the ledger, and scaffolding accepted candidates into skill-hub layout.

Python 3.8+, standard library only. Every command ends with one line:
    RESULT ok <summary>          or          RESULT fail code=<E_...> <reason>
Source: https://github.com/D-Tony2020/skill-hub  (skills/session-distiller)
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
SOURCE_REPO = os.environ.get("SD_SRC_URL", "https://github.com/D-Tony2020/skill-hub")
SOURCE_PATH = "skills/session-distiller"
SOURCE_BRANCH = os.environ.get("SD_SRC_BRANCH", "main")

for _s in (sys.stdout, sys.stderr):  # Windows consoles default to cp936/cp1252
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# ----------------------------------------------------------------- basics ---
class Fail(Exception):
    def __init__(self, code: str, msg: str):
        super().__init__(msg)
        self.code, self.msg = code, msg


def version() -> str:
    """VERSION file; falls back to the top CHANGELOG heading because some registries
    (SkillHub) drop extension-less files when packaging."""
    try:
        return (SKILL_DIR / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        pass
    try:
        m = re.search(r"^## (\d+\.\d+\.\d+\S*)", (SKILL_DIR / "CHANGELOG.md").read_text(encoding="utf-8"), re.M)
        return m.group(1) if m else "0.0.0"
    except OSError:
        return "0.0.0"


def home() -> Path:
    return Path(os.environ.get("SD_HOME") or Path.home() / ".session-distiller")


def claude_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def now_iso() -> str:
    return dt.datetime.now().replace(microsecond=0).isoformat()


def read_json(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as e:
        raise Fail("E_BAD_JSON", f"{p}: {e}")


def write_json(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, p)


def info(msg: str) -> None:
    print(msg)


def load_config() -> dict:
    cfg = read_json(home() / "config.json", None)
    if cfg is None:
        cfg = default_config()
    return cfg


def default_config() -> dict:
    return {
        "sources": [{"type": "claude-code", "path": str(claude_dir() / "projects")}],
        "skill_hub": os.environ.get("SD_HUB") or str(Path.home() / "skill-hub"),
        "skill_dirs": [str(claude_dir() / "skills")],
        "include_sidechains": False,
        "min_user_turns": 2,
        "digest_max_chars": 40000,
        "owner": "dean",
    }


def load_ledger() -> dict:
    led = read_json(home() / "ledger.json", None) or {}
    led.setdefault("schema", 1)
    led.setdefault("sessions", {})
    led.setdefault("candidates", {})
    return led


def save_ledger(led: dict) -> None:
    write_json(home() / "ledger.json", led)


# -------------------------------------------------------------- redaction ---
REDACTIONS = [
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----")),
    ("anthropic_key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{10,}")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}")),
    ("github_token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}")),
    ("gitlab_token", re.compile(r"\bglpat-[A-Za-z0-9_\-]{16,}")),
    ("slack_token", re.compile(r"\bxox[abposr]-[A-Za-z0-9\-]{10,}")),
    ("aws_key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("feishu_secret", re.compile(r"\b(?:cli_[a-z0-9]{16}|t-g[0-9a-z]{30,}|u-[A-Za-z0-9_\-]{30,})\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}")),
    ("bearer", re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{16,}")),
    ("url_credentials", re.compile(r"(?<=://)[^/\s:@]+:[^/\s@]+(?=@)")),
    ("assignment_secret", re.compile(
        r"(?i)\b([A-Za-z0-9_]*(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key)[A-Za-z0-9_]*)"
        r"(\s*[:=]\s*)(['\"]?)[^\s'\"]{6,}\3")),
    ("cn_id_card", re.compile(r"(?<!\d)[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)")),
    ("cn_mobile", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    ("email", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")),
]


CREDENTIAL_KINDS = {"private_key", "anthropic_key", "openai_key", "github_token", "gitlab_token", "slack_token", "aws_key",
                    "feishu_secret", "jwt", "bearer", "url_credentials", "assignment_secret"}


def load_custom_terms() -> list:
    """User-maintained sensitive terms (customer names, internal hosts), one per line."""
    p = home() / "redact.txt"
    terms = []
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                terms.append(line)
    return sorted(set(terms), key=len, reverse=True)


class Redactor:
    def __init__(self, terms=None):
        self.terms = terms if terms is not None else load_custom_terms()
        self.hits = Counter()

    def __call__(self, text: str) -> str:
        if not text:
            return text
        for name, rx in REDACTIONS:
            def sub(m, name=name):
                self.hits[name] += 1
                if name == "assignment_secret":
                    return f"{m.group(1)}{m.group(2)}[REDACTED:secret]"
                if name == "bearer":
                    return f"{m.group(1)}[REDACTED:token]"
                return f"[REDACTED:{name}]"
            text = rx.sub(sub, text)
        for i, t in enumerate(self.terms):
            if t in text:
                self.hits["custom_term"] += text.count(t)
                text = text.replace(t, f"[TERM{i + 1}]")
        return text


# ------------------------------------------------------ transcript parsing ---
NOISE_TAGS = re.compile(
    r"<(system-reminder|local-command-stdout|local-command-stderr|command-message|"
    r"session-context|user-prompt-submit-hook)[^>]*>[\s\S]*?</\1>")
CMD_NAME = re.compile(r"<command-name>([\s\S]*?)</command-name>")
CMD_ARGS = re.compile(r"<command-args>([\s\S]*?)</command-args>")
CAVEAT = "Caveat: The messages below were generated by the user while running local commands"
CORRECTION = re.compile(
    r"(不对|不是这样|错了|重新|重来|应该是|应该用|别再|不要再|不要用|你漏了|还是不行|没生效|搞错|"
    r"\bwrong\b|\bnot what i\b|\binstead\b|\bactually\b|\bthat's not\b|\bdon't\b|\bstop\b)", re.I)
CODE_EXT = {".py", ".sh", ".ps1", ".js", ".mjs", ".ts", ".tsx", ".go", ".java", ".sql", ".rb", ".rs", ".kt"}


def _ts(s):
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _clip(s: str, n: int) -> str:
    s = s.strip()
    return s if len(s) <= n else s[: n - 20].rstrip() + f" …[+{len(s) - n + 20} chars]"


def _one_line(s: str, n: int) -> str:
    return _clip(re.sub(r"\s+", " ", s or ""), n)


def human_text(content) -> str | None:
    """Return the human-typed text of a user record, or None if it is not a human turn."""
    if isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return None
        parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        if any(isinstance(b, dict) and b.get("type") == "image" for b in content):
            parts.append("[image]")
        text = "\n".join(parts)
    elif isinstance(content, str):
        text = content
    else:
        return None
    if text.startswith(CAVEAT) or "<local-command-stdout>" in text and not CMD_NAME.search(text):
        return None
    text = unwrap_envelope(text)
    m = CMD_NAME.search(text)
    if m:
        a = CMD_ARGS.search(text)
        return (m.group(1).strip() + " " + (a.group(1).strip() if a else "")).strip()
    text = NOISE_TAGS.sub("", text).strip()
    if text.startswith("[Request interrupted"):
        return None
    return text or None


WAKE_MSG = re.compile(r'<message\b([^>]*)>([\s\S]*?)</message>')
CITED = re.compile(r'<cited\b[^>]*>([\s\S]*?)</cited>')
NOTE = re.compile(r'<note>([\s\S]*?)</note>')


def unwrap_envelope(text: str) -> str:
    """Claude project threads / remote sessions wrap the human prompt in XML envelopes.
    Keep only what humans wrote (and peer notes, labelled)."""
    t = text.lstrip()
    if t.startswith("<wake") or t.startswith("<coordinator-relay") or t.startswith("<relay"):
        parts = []
        for attrs, body in WAKE_MSG.findall(t):
            if 'from="human"' in attrs or "from='human'" in attrs:
                parts.append(body.strip())
        parts += [c.strip() for c in CITED.findall(t)]
        parts += ["[peer note] " + n.strip() for n in NOTE.findall(t)]
        return "\n\n".join(p for p in parts if p)
    return text


def summarize_tool(name: str, inp: dict) -> str:
    inp = inp or {}
    g = inp.get
    if name == "Bash":
        return "Bash: " + _one_line(g("command", ""), 220)
    if name in ("Write", "Edit", "MultiEdit", "NotebookEdit", "Read"):
        p = g("file_path") or g("notebook_path") or ""
        extra = ""
        if name == "Write" and isinstance(g("content"), str):
            extra = f" ({g('content').count(chr(10)) + 1} lines)"
        return f"{name}: {p}{extra}"
    if name in ("Grep", "Glob"):
        return f"{name}: {_one_line(str(g('pattern', '')), 120)} {g('path') or ''}".rstrip()
    if name in ("Skill",):
        return f"Skill: {g('skill') or g('command') or ''}"
    if name in ("Task", "Agent"):
        return f"{name}: {_one_line(g('description') or g('prompt') or '', 160)}"
    if name in ("WebFetch", "WebSearch"):
        return f"{name}: {_one_line(g('url') or g('query') or '', 160)}"
    if name in ("TodoWrite",):
        todos = g("todos") or []
        return "TodoWrite: " + "; ".join(_one_line(t.get("content", ""), 60) for t in todos[:6] if isinstance(t, dict))
    keys = ",".join(list(inp.keys())[:4])
    return f"{name}({keys})"


HEREDOC = re.compile(r"<<-?\s*['\"]?(\w+)['\"]?[^\n]*\n[\s\S]*?\n\s*\1\b")
SUBCMD_TOOLS = {"git", "npm", "pnpm", "yarn", "npx", "docker", "kubectl", "gh", "glab", "pip", "pip3", "uv", "cargo",
                "go", "make", "brew", "winget", "claude", "lark-cli", "az", "aws", "gcloud", "terraform", "helm", "mvn", "gradle"}
INTERPRETERS = {"python", "python3", "py", "node", "bash", "sh", "pwsh", "powershell", "deno", "bun"}
SKIP_HEADS = {"cd", "echo", "ls", "cat", "pwd", "true", "set", "export", "sleep", "head", "tail", "grep", "wc", "sed", "awk", "mkdir", "rm", "cp", "mv", "find", "chmod", "test", "["}


def command_heads(cmd: str) -> list:
    """First two tokens of each pipeline segment, skipping shell plumbing (cd, ls, cat…)."""
    heads = []
    cmd = HEREDOC.sub("", cmd)
    for seg in re.split(r"&&|\|\||;|\||\n", cmd):
        tok = seg.strip().split()
        while tok and re.match(r"^[A-Z_][A-Z0-9_]*=", tok[0]):  # env assignments
            tok = tok[1:]
        if not tok or tok[0] in SKIP_HEADS or tok[0].startswith("#"):
            continue
        prog = Path(tok[0]).name
        h = prog
        if prog in SUBCMD_TOOLS and len(tok) > 1 and not tok[1].startswith("-"):
            h = f"{prog} {tok[1]}"
        elif prog in INTERPRETERS:
            script = next((t for t in tok[1:] if not t.startswith("-")), None)
            if script and re.search(r"\.(py|js|mjs|ts|sh|ps1)$", script):
                h = f"{prog} {Path(script.replace(chr(92), '/')).name}"
            elif "-m" in tok and tok.index("-m") + 1 < len(tok):
                h = f"{prog} -m {tok[tok.index('-m') + 1]}"
        if h not in heads:
            heads.append(h)
    return heads


def iter_records(path: Path):
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def parse_session(path: Path, include_sidechains=False) -> dict:
    """Parse a Claude Code JSONL transcript into turns. Unknown records are skipped."""
    s = {"path": str(path), "id": path.stem, "cwd": None, "branch": None, "title": None,
         "models": Counter(), "first": None, "last": None, "turns": [], "tool_counts": Counter(),
         "errors": 0, "files_written": [], "skills": Counter(), "mcp": Counter(), "bash_heads": Counter(),
         "corrections": 0, "compactions": 0, "version": None}
    cur = None
    tool_names = {}
    seen_files = set()
    for r in iter_records(path):
        t = r.get("type")
        if t == "summary" and r.get("summary"):
            s["title"] = s["title"] or r["summary"]
            continue
        if t not in ("user", "assistant"):
            continue
        if r.get("isSidechain") and not include_sidechains:
            continue
        s["id"] = r.get("sessionId") or s["id"]
        s["cwd"] = s["cwd"] or r.get("cwd")
        s["branch"] = s["branch"] or r.get("gitBranch")
        s["version"] = s["version"] or r.get("version")
        ts = _ts(r.get("timestamp"))
        if ts:
            s["first"] = s["first"] or ts
            s["last"] = ts
        msg = r.get("message") or {}
        content = msg.get("content")
        if t == "user":
            if r.get("isCompactSummary"):
                s["compactions"] += 1
                continue
            if isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("is_error"):
                        s["errors"] += 1
                        if cur is not None:
                            txt = b.get("content")
                            if isinstance(txt, list):
                                txt = " ".join(x.get("text", "") for x in txt if isinstance(x, dict))
                            cur["errors"].append(_one_line(str(txt or ""), 200))
            if r.get("isMeta"):
                continue
            text = human_text(content)
            if text is None:
                continue
            corr = bool(CORRECTION.search(text)) and len(s["turns"]) > 0
            s["corrections"] += int(corr)
            cur = {"n": len(s["turns"]) + 1, "ts": r.get("timestamp"), "user": text, "assistant": [],
                   "tools": [], "errors": [], "correction": corr}
            s["turns"].append(cur)
            continue
        # assistant
        if msg.get("model"):
            s["models"][msg["model"]] += 1
        if not isinstance(content, list):
            continue
        for b in content:
            if not isinstance(b, dict):
                continue
            bt = b.get("type")
            if bt == "text" and b.get("text", "").strip():
                if cur is not None:
                    cur["assistant"].append(b["text"])
            elif bt == "tool_use":
                name = b.get("name", "?")
                inp = b.get("input") or {}
                tool_names[b.get("id")] = name
                s["tool_counts"][name] += 1
                if name.startswith("mcp__"):
                    s["mcp"][name.split("__")[1] if name.count("__") >= 2 else name] += 1
                if name == "Skill":
                    s["skills"][str(inp.get("skill") or inp.get("command") or "?")] += 1
                if name == "Bash":
                    for head in command_heads(str(inp.get("command", ""))):
                        s["bash_heads"][head] += 1
                if name in ("Write", "NotebookEdit") or (name == "Edit" and inp.get("file_path")):
                    fp = inp.get("file_path") or inp.get("notebook_path")
                    if fp and fp not in seen_files and name == "Write":
                        seen_files.add(fp)
                        s["files_written"].append(fp)
                if cur is not None:
                    cur["tools"].append(summarize_tool(name, inp))
    return s


def session_meta(path: Path, include_sidechains=False) -> dict:
    s = parse_session(path, include_sidechains)
    st = path.stat()
    return {
        "id": s["id"], "path": str(path), "cwd": s["cwd"] or decode_project_dir(path.parent.name),
        "branch": s["branch"], "title": s["title"] or (_one_line(s["turns"][0]["user"], 80) if s["turns"] else ""),
        "first": s["first"].isoformat() if s["first"] else None,
        "last": s["last"].isoformat() if s["last"] else None,
        "user_turns": len(s["turns"]), "tool_calls": sum(s["tool_counts"].values()),
        "size": st.st_size, "mtime": int(st.st_mtime), "corrections": s["corrections"],
    }


def decode_project_dir(name: str) -> str:
    # Claude Code stores ~/.claude/projects/<cwd with / \ : . replaced by ->
    return name


# ---------------------------------------------------------------- sources ---
def discover(cfg: dict) -> list:
    files = []
    for src in cfg.get("sources", []):
        p = Path(os.path.expanduser(src.get("path", "")))
        if not p.exists():
            continue
        if p.is_file() and p.suffix == ".jsonl":
            files.append(p)
            continue
        for f in p.rglob("*.jsonl"):
            # Claude Code keeps subagent transcripts under <session>/subagents/; they are sidechains
            if "subagents" in f.parts and not cfg.get("include_sidechains"):
                continue
            files.append(f)
    uniq = {}
    for f in files:
        uniq[str(f.resolve())] = f
    return sorted(uniq.values(), key=lambda f: f.stat().st_mtime, reverse=True)


def session_state(led: dict, meta: dict) -> str:
    rec = led["sessions"].get(meta["id"])
    if not rec:
        return "new"
    if rec.get("size") != meta["size"]:
        return "changed"
    return "done"


def parse_date(s: str | None):
    if not s:
        return None
    if re.fullmatch(r"\d+d", s):
        return dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=int(s[:-1]))
    d = dt.datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def select_sessions(args, cfg, led) -> list:
    since, until = parse_date(args.since), parse_date(args.until)
    want = set(args.session or [])
    out = []
    for f in discover(cfg):
        if want and not any(w in f.stem for w in want):
            continue
        try:
            m = session_meta(f, cfg.get("include_sidechains", False))
        except OSError:
            continue
        m["state"] = session_state(led, m)
        if not want:
            if m["user_turns"] < (args.min_turns if args.min_turns is not None else cfg.get("min_user_turns", 2)):
                continue
            if m["state"] == "done" and not args.all:
                continue
            last = _ts(m["last"]) if m["last"] else None
            if since and (not last or last < since):
                continue
            if until and last and last > until:
                continue
            if args.project and args.project.lower() not in (m["cwd"] or "").lower():
                continue
        out.append(m)
    if args.limit:
        out = out[: args.limit]
    return out


# ----------------------------------------------------------------- digest ---
def render_digest(s: dict, red: Redactor, max_chars: int) -> str:
    def build(user_n, asst_n, tools_n):
        L = []
        span = ""
        if s["first"] and s["last"]:
            mins = int((s["last"] - s["first"]).total_seconds() // 60)
            span = f"{s['first'].isoformat(timespec='minutes')} → {s['last'].isoformat(timespec='minutes')} ({mins} min)"
        L.append(f"# Session {s['id']}")
        L.append("")
        L.append(f"- project: `{red(s['cwd'] or '?')}`  branch: `{s['branch'] or '-'}`")
        L.append(f"- time: {span or '?'}")
        title = s["title"] or (_one_line(s["turns"][0]["user"], 80) if s["turns"] else "")
        L.append(f"- title: {red(title)}")
        L.append(f"- user turns: {len(s['turns'])}, tool calls: {sum(s['tool_counts'].values())}, "
                 f"tool errors: {s['errors']}, user corrections: {s['corrections']}, compactions: {s['compactions']}")
        if s["models"]:
            L.append(f"- models: {', '.join(m for m, _ in s['models'].most_common(3))}")
        L.append("")
        L.append("## Signals")
        L.append("")
        if s["tool_counts"]:
            L.append("- tools: " + ", ".join(f"{k}×{v}" for k, v in s["tool_counts"].most_common(12)))
        if s["skills"]:
            L.append("- skills used: " + ", ".join(f"{k}×{v}" for k, v in s["skills"].most_common()))
        if s["mcp"]:
            L.append("- MCP servers: " + ", ".join(f"{k}×{v}" for k, v in s["mcp"].most_common(8)))
        if s["bash_heads"]:
            L.append("- frequent commands: " + ", ".join(f"`{red(k)}`×{v}" for k, v in s["bash_heads"].most_common(10)))
        code = [f for f in s["files_written"] if Path(f).suffix.lower() in CODE_EXT]
        docs = [f for f in s["files_written"] if Path(f).suffix.lower() not in CODE_EXT]
        if code:
            L.append(f"- code files written ({len(code)}): " + ", ".join(f"`{red(c)}`" for c in code[:15]))
        if docs:
            L.append(f"- other files written ({len(docs)}): " + ", ".join(f"`{red(c)}`" for c in docs[:15]))
        corr = [t["n"] for t in s["turns"] if t["correction"]]
        if corr:
            L.append("- turns where the user corrected the agent: " + ", ".join(f"T{n}" for n in corr))
        L.append("")
        L.append("## Turns")
        L.append("")
        for t in s["turns"]:
            flag = "  ⚑correction" if t["correction"] else ""
            L.append(f"### T{t['n']} · {(t['ts'] or '')[:16]}{flag}")
            L.append("")
            L.append("**User:** " + red(_clip(t["user"], user_n)).replace("\n", "\n> ").strip())
            if t["tools"]:
                shown = t["tools"][:tools_n]
                L.append("")
                L.append(f"**Actions ({len(t['tools'])}):**")
                for a in shown:
                    L.append(f"- {red(a)}")
                if len(t["tools"]) > tools_n:
                    L.append(f"- … {len(t['tools']) - tools_n} more")
            if t["errors"]:
                L.append("")
                L.append(f"**Tool errors ({len(t['errors'])}):** " + " | ".join(red(e) for e in t["errors"][:3]))
            if t["assistant"]:
                final = t["assistant"][-1]
                L.append("")
                L.append("**Agent (last reply):** " + red(_clip(final, asst_n)))
            L.append("")
        return "\n".join(L)

    # progressively tighten until it fits the budget
    for user_n, asst_n, tools_n in ((2000, 1500, 25), (1200, 800, 15), (800, 400, 10), (500, 200, 6), (300, 120, 4)):
        out = build(user_n, asst_n, tools_n)
        if len(out) <= max_chars:
            return out
    return out[: max_chars - 60] + "\n\n…[digest truncated to budget; read the raw transcript for the rest]\n"


def new_run_id() -> str:
    return dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def run_dir(run: str) -> Path:
    if run == "latest":
        runs = sorted((home() / "runs").glob("*")) if (home() / "runs").exists() else []
        runs = [r for r in runs if r.is_dir()]
        if not runs:
            raise Fail("E_NO_RUN", "no runs yet; run `sd digest` first")
        return runs[-1]
    p = home() / "runs" / run
    if not p.is_dir():
        raise Fail("E_NO_RUN", f"run {run} not found under {home() / 'runs'}")
    return p


# --------------------------------------------------------------- commands ---
def cmd_init(args):
    h = home()
    h.mkdir(parents=True, exist_ok=True)
    created = []
    if not (h / "config.json").exists() or args.force:
        write_json(h / "config.json", default_config())
        created.append("config.json")
    if not (h / "profile.md").exists():
        shutil.copy(SKILL_DIR / "assets" / "profile.template.md", h / "profile.md")
        created.append("profile.md")
    if not (h / "redact.txt").exists():
        (h / "redact.txt").write_text(
            "# 每行一个需要脱敏的词：客户名、内部域名、人名等。出现在摘要和草稿里时替换成 [TERMn]。\n",
            encoding="utf-8")
        created.append("redact.txt")
    save_ledger(load_ledger())
    info(f"home: {h}")
    return f"init home={h} created={','.join(created) or 'none'}"


def cmd_doctor(args):
    cfg = load_config()
    problems = []
    info(f"session-distiller {version()}  python {sys.version.split()[0]}  home={home()}")
    if sys.version_info < (3, 8):
        problems.append("python<3.8")
    if not (home() / "config.json").exists():
        problems.append("not_initialized(run: sd init)")
    prof = home() / "profile.md"
    if prof.exists() and "TODO" in prof.read_text(encoding="utf-8"):
        info("profile: has TODO markers; ask the user to finish it")
    for src in cfg.get("sources", []):
        p = Path(os.path.expanduser(src["path"]))
        n = len(list(p.rglob("*.jsonl"))) if p.is_dir() else 0
        info(f"source {src['type']}: {p}  exists={p.exists()}  jsonl={n}")
        if not p.exists():
            problems.append(f"missing_source:{p}")
    hub = Path(os.path.expanduser(cfg.get("skill_hub", "")))
    info(f"skill_hub: {hub}  exists={hub.exists()}  git={(hub / '.git').exists()}")
    led = load_ledger()
    info(f"ledger: {len(led['sessions'])} sessions processed, {len(led['candidates'])} candidates recorded")
    src_rec = SKILL_DIR / "SOURCE"
    if src_rec.exists():
        info("installed from: " + src_rec.read_text(encoding="utf-8").replace("\n", "  "))
    if problems:
        raise Fail("E_DOCTOR", " ".join(problems))
    return "doctor"


def cmd_scan(args):
    cfg, led = load_config(), load_ledger()
    sel = select_sessions(args, cfg, led)
    red = Redactor()
    if args.json:
        print(json.dumps([{**m, "title": red(m.get("title") or ""), "cwd": red(m.get("cwd") or "")} for m in sel],
                         ensure_ascii=False, indent=2))
    else:
        for m in sel:
            print(f"{m['id'][:8]}  {m['state']:<7} {(m['last'] or '')[:10]}  turns={m['user_turns']:<3} "
                  f"tools={m['tool_calls']:<4} corr={m['corrections']:<2} {red(m['cwd'] or '')}  | {red(m['title'] or '')[:60]}")
    return f"scan sessions={len(sel)} new={sum(m['state'] == 'new' for m in sel)} changed={sum(m['state'] == 'changed' for m in sel)}"


def cmd_digest(args):
    cfg, led = load_config(), load_ledger()
    sel = select_sessions(args, cfg, led)
    if not sel:
        raise Fail("E_NO_SESSIONS", "no matching unprocessed sessions (use --all, --since, --session, or check sources with `sd doctor`)")
    rid = args.run or new_run_id()
    rd = home() / "runs" / rid
    (rd / "digests").mkdir(parents=True, exist_ok=True)
    red = Redactor()
    max_chars = args.max_chars or cfg.get("digest_max_chars", 40000)
    index, agg = [], {"tools": Counter(), "skills": Counter(), "mcp": Counter(), "bash": Counter(), "projects": Counter()}
    leaks = []
    for m in sel:
        s = parse_session(Path(m["path"]), cfg.get("include_sidechains", False))
        before = Counter(red.hits)
        text = render_digest(s, red, max_chars)
        cred = {k: v for k, v in (red.hits - before).items() if k in CREDENTIAL_KINDS}
        if cred:
            leaks.append((m, cred))
        fname = f"{m['id']}.md"
        (rd / "digests" / fname).write_text(text, encoding="utf-8")
        m = {**m, "title": red(m.get("title") or ""), "cwd": red(m.get("cwd") or "")}
        index.append({**m, "digest": f"digests/{fname}", "digest_chars": len(text),
                      "turn_ids": [f"T{t['n']}" for t in s["turns"]]})
        agg["tools"].update(s["tool_counts"]); agg["skills"].update(s["skills"]); agg["mcp"].update(s["mcp"])
        agg["bash"].update({k: 1 for k in s["bash_heads"]})  # count sessions, not calls
        agg["projects"][red(m["cwd"] or "?")] += 1
    write_json(rd / "index.json", {"run": rid, "created": now_iso(), "sessions": index,
                                   "redactions": dict(red.hits), "sd_version": version()})
    ov = [f"# Run {rid} overview", "", f"{len(index)} sessions, {sum(i['user_turns'] for i in index)} user turns.", "",
          "## Sessions", "", "| id | last | turns | corrections | project | title |", "|---|---|---|---|---|---|"]
    for i in index:
        ov.append(f"| {i['id'][:8]} | {(i['last'] or '')[:10]} | {i['user_turns']} | {i['corrections']} | "
                  f"{red(i['cwd'] or '')} | {red(i['title'] or '')[:50].replace('|', '/')} |")
    ov += ["", "## Cross-session signals (recurrence = strongest reuse evidence)", ""]
    ov.append("- projects: " + ", ".join(f"{k}×{v}" for k, v in agg["projects"].most_common(10)))
    rec = [(k, v) for k, v in agg["bash"].most_common(20) if v > 1]
    if rec:
        ov.append("- commands recurring across sessions: " + ", ".join(f"`{red(k)}` in {v}" for k, v in rec))
    if agg["skills"]:
        ov.append("- skills used: " + ", ".join(f"{k}×{v}" for k, v in agg["skills"].most_common()))
    if agg["mcp"]:
        ov.append("- MCP servers: " + ", ".join(f"{k}×{v}" for k, v in agg["mcp"].most_common(10)))
    ov.append("- tools: " + ", ".join(f"{k}×{v}" for k, v in agg["tools"].most_common(15)))
    if leaks:
        ov += ["", "## Security: credentials found in raw transcripts", "",
               "These were masked in the digests, but the raw session files still contain them. Tell the user so they can rotate them.", ""]
        for m, cred in leaks:
            ov.append(f"- {m['id'][:8]} ({red(m['cwd'] or '')}): " + ", ".join(f"{k}×{v}" for k, v in cred.items()))
    if red.hits:
        ov += ["", "Redactions applied: " + ", ".join(f"{k}×{v}" for k, v in red.hits.most_common())]
    (rd / "overview.md").write_text("\n".join(ov) + "\n", encoding="utf-8")
    write_catalog(rd, cfg, led)
    info(f"run dir: {rd}")
    return (f"digest run={rid} sessions={len(index)} chars={sum(i['digest_chars'] for i in index)} "
            f"redactions={sum(red.hits.values())} credential_leaks={len(leaks)}")


def read_frontmatter(p: Path) -> dict:
    try:
        txt = p.read_text(encoding="utf-8")
    except OSError:
        return {}
    m = re.match(r"^---\s*\n([\s\S]*?)\n---", txt)
    out = {}
    if not m:
        return out
    key = None
    for line in m.group(1).splitlines():
        km = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if km:
            key = km.group(1)
            out[key] = km.group(2).strip().strip("'\"")
        elif key and line.startswith((" ", "\t")):
            out[key] = (out[key] + " " + line.strip()).strip()
    return out


def existing_skills(cfg: dict) -> list:
    found = {}
    roots = []
    hub = Path(os.path.expanduser(cfg.get("skill_hub", "")))
    if (hub / "skills").is_dir():
        roots.append(("skill-hub", hub / "skills"))
    for d in cfg.get("skill_dirs", []):
        roots.append(("installed", Path(os.path.expanduser(d))))
    plug = claude_dir() / "plugins"
    if plug.is_dir():
        roots.append(("plugin", plug))
    for origin, root in roots:
        if not root.is_dir():
            continue
        for sk in root.rglob("SKILL.md"):
            fm = read_frontmatter(sk)
            name = fm.get("name") or sk.parent.name
            if name in found and found[name]["origin"] == "skill-hub":
                continue
            found[name] = {"name": name, "origin": origin, "path": str(sk.parent),
                           "description": fm.get("description", "")}
    return sorted(found.values(), key=lambda x: (x["origin"] != "skill-hub", x["name"]))


def write_catalog(rd: Path, cfg: dict, led: dict) -> None:
    sk = existing_skills(cfg)
    L = ["# Existing assets (for dedupe)", "", "## The user's own skills (skill-hub and installed)", ""]
    own = [s for s in sk if s["origin"] != "plugin"]
    for s in own:
        L.append(f"- **{s['name']}** ({s['origin']}): {_one_line(s['description'], 300)}")
    if not own:
        L.append("- (none found)")
    plug = [s["name"] for s in sk if s["origin"] == "plugin"]
    if plug:
        L += ["", f"## Plugin skills ({len(plug)}, names only; read one with `sd catalog` if a candidate looks close)", "",
              ", ".join(plug)]
    L += ["", "## Earlier candidates in the ledger", ""]
    for cid, c in sorted(led["candidates"].items()):
        L.append(f"- `{cid}` [{c.get('decision', 'pending')}] {c.get('title', '')}"
                 + (f" — reason: {c['reason']}" if c.get("reason") else ""))
    if not led["candidates"]:
        L.append("- (none)")
    (rd / "catalog.md").write_text("\n".join(L) + "\n", encoding="utf-8")


def cmd_catalog(args):
    cfg, led = load_config(), load_ledger()
    sk = existing_skills(cfg)
    for s in sk:
        print(f"{s['name']:<32} {s['origin']:<10} {_one_line(s['description'], 90)}")
    return f"catalog skills={len(sk)} ledger_candidates={len(led['candidates'])}"


# ------------------------------------------------------------- candidates ---
KINDS = {"rule", "rule+code", "methodology", "workflow", "component"}
SCORE_KEYS = ("fit", "reuse", "leverage", "maturity")
WEIGHTS = {"fit": 0.35, "reuse": 0.25, "leverage": 0.20, "maturity": 0.20}
SLUG = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")


def priority(sc: dict) -> float:
    return round(sum(WEIGHTS[k] * float(sc.get(k, 0)) for k in SCORE_KEYS), 2)


def tier(sc: dict) -> str:
    p = priority(sc)
    if sc.get("fit", 0) < 3:
        return "C"
    if p >= 3.6 and (sc.get("reuse", 0) >= 3 or sc.get("leverage", 0) >= 4):
        return "A"
    if p >= 2.8:
        return "B"
    return "C"


def validate_candidates(rd: Path, led: dict):
    data = read_json(rd / "candidates.json", None)
    if data is None:
        raise Fail("E_NO_CANDIDATES", f"{rd / 'candidates.json'} missing; write it per references/candidate-schema.md")
    idx = read_json(rd / "index.json", {"sessions": []})
    turns = {s["id"]: set(s.get("turn_ids", [])) for s in idx["sessions"]}
    errs, warns = [], []
    cands = data.get("candidates")
    if not isinstance(cands, list):
        raise Fail("E_SCHEMA", "candidates.json needs a `candidates` list (empty is fine when nothing is worth keeping)")
    if not cands and not str(data.get("none_reason", "")).strip():
        errs.append("empty `candidates` needs a `none_reason` explaining why nothing was worth keeping")
    ids = set()
    for i, c in enumerate(cands):
        where = f"candidates[{i}]({c.get('id', '?')})"
        for k in ("id", "title", "kind", "summary", "problem", "evidence", "scores", "fit_rationale", "dedupe", "packaging"):
            if k not in c:
                errs.append(f"{where}: missing `{k}`")
        cid = c.get("id", "")
        if not SLUG.match(cid or "") or len(cid) > 64 or re.search(r"claude|anthropic", cid):
            errs.append(f"{where}: id must be kebab-case ≤64 chars without 'claude'/'anthropic'")
        if cid in ids:
            errs.append(f"{where}: duplicate id")
        ids.add(cid)
        if c.get("kind") not in KINDS:
            errs.append(f"{where}: kind must be one of {sorted(KINDS)}")
        sc = c.get("scores") or {}
        for k in SCORE_KEYS:
            v = sc.get(k)
            if not isinstance(v, int) or not 0 <= v <= 5:
                errs.append(f"{where}: scores.{k} must be an integer 0-5")
        ev = c.get("evidence") or []
        if not ev:
            errs.append(f"{where}: needs at least one evidence item")
        sessions = set()
        for e in ev:
            sid = e.get("session", "")
            match = [k for k in turns if k == sid or k.startswith(sid)] if sid else []
            if not match:
                errs.append(f"{where}: evidence session `{sid}` is not in this run")
                continue
            sessions.add(match[0])
            bad = [t for t in e.get("turns", []) if t not in turns[match[0]]]
            if bad:
                errs.append(f"{where}: evidence turns {bad} not in session {sid[:8]}")
        if isinstance(sc.get("reuse"), int) and sc["reuse"] >= 4 and len(sessions) < 2:
            warns.append(f"{where}: reuse≥4 claimed but evidence spans {len(sessions)} session(s)")
        d = c.get("dedupe") or {}
        if d.get("action") not in ("new", "merge", "duplicate"):
            errs.append(f"{where}: dedupe.action must be new|merge|duplicate")
        if d.get("action") in ("merge", "duplicate") and not d.get("target"):
            errs.append(f"{where}: dedupe.target required for {d.get('action')}")
        prev = led["candidates"].get(cid)
        if prev and prev.get("decision") == "reject":
            warns.append(f"{where}: was rejected before ({prev.get('reason', 'no reason')}); drop it unless there is new evidence")
        pk = c.get("packaging") or {}
        if pk.get("form") not in ("skill", "rule-snippet", "reference"):
            errs.append(f"{where}: packaging.form must be skill|rule-snippet|reference")
        if c.get("kind") == "rule+code" and not pk.get("scripts"):
            warns.append(f"{where}: kind rule+code but packaging.scripts is empty")
    return data, errs, warns


def cmd_validate(args):
    rd = run_dir(args.run)
    _, errs, warns = validate_candidates(rd, load_ledger())
    for w in warns:
        print("WARN  " + w)
    for e in errs:
        print("ERROR " + e)
    if errs:
        raise Fail("E_SCHEMA", f"{len(errs)} error(s) in candidates.json")
    return f"validate run={rd.name} warnings={len(warns)}"


def cmd_report(args):
    rd = run_dir(args.run)
    led = load_ledger()
    data, errs, warns = validate_candidates(rd, led)
    if errs:
        for e in errs:
            print("ERROR " + e)
        raise Fail("E_SCHEMA", "fix candidates.json first (sd validate)")
    idx = read_json(rd / "index.json", {"sessions": []})
    titles = {s["id"]: s.get("title", "") for s in idx["sessions"]}
    cands = sorted(data["candidates"], key=lambda c: ("ABC".index(tier(c["scores"])), -priority(c["scores"])))
    L = [f"# 候选资产清单 · run {rd.name}", "",
         f"来自 {len(idx['sessions'])} 个会话，共 {len(cands)} 个候选。"
         f"A 档 {sum(tier(c['scores']) == 'A' for c in cands)} 个，B 档 {sum(tier(c['scores']) == 'B' for c in cands)} 个，"
         f"C 档 {sum(tier(c['scores']) == 'C' for c in cands)} 个。", "",
         "评分：契合度 fit ×0.35 + 复用度 reuse ×0.25 + 杠杆 leverage ×0.20 + 成熟度 maturity ×0.20（各 0–5）。"
         "A 档建议采纳，C 档默认不做。", "",
         "| # | 档 | 优先级 | 候选 | 形态 | 去重 | fit/reuse/lev/mat |", "|---|---|---|---|---|---|---|"]
    for n, c in enumerate(cands, 1):
        sc, d = c["scores"], c["dedupe"]
        dd = d["action"] + (f"→{d['target']}" if d.get("target") else "")
        L.append(f"| {n} | {tier(sc)} | {priority(sc)} | `{c['id']}` {c['title']} | {c['kind']} | {dd} | "
                 f"{sc['fit']}/{sc['reuse']}/{sc['leverage']}/{sc['maturity']} |")
    L.append("")
    if not cands:
        L += ["本次没有值得固化的资产。", "", f"原因：{data.get('none_reason', '')}", ""]
    for n, c in enumerate(cands, 1):
        sc = c["scores"]
        L += [f"## {n}. [{tier(sc)}] {c['title']}  (`{c['id']}`)", "",
              f"**形态**：{c['kind']} → {c['packaging'].get('form')}"
              + (f"，脚本：{', '.join(c['packaging'].get('scripts') or [])}" if c['packaging'].get('scripts') else ""), "",
              f"**解决什么**：{c['problem']}", "", f"**内容**：{c['summary']}", "",
              f"**为什么契合长期目标**：{c['fit_rationale']}", ""]
        if c["packaging"].get("triggers"):
            L += ["**触发场景**：" + "；".join(c["packaging"]["triggers"]), ""]
        L.append("**证据**：")
        for e in c["evidence"]:
            sid = next((k for k in titles if k.startswith(e["session"])), e["session"])
            q = f" — “{e['quote']}”" if e.get("quote") else ""
            L.append(f"- `{sid[:8]}` {titles.get(sid, '')[:40]} · {', '.join(e.get('turns', []))}{q}")
        if c.get("risks"):
            L += ["", f"**风险/注意**：{c['risks']}"]
        d = c["dedupe"]
        if d["action"] != "new":
            L += ["", f"**去重**：{d['action']} → `{d.get('target')}`" + (f"（{d['note']}）" if d.get("note") else "")]
        L += ["", f"决定：`sd decide {rd.name} {c['id']} accept|merge|reject --reason \"...\"`", ""]
    if warns:
        L += ["## 校验提醒", ""] + [f"- {w}" for w in warns]
    (rd / "report.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    for c in cands:
        led["candidates"].setdefault(c["id"], {}).update(
            {"title": c["title"], "kind": c["kind"], "run": rd.name, "tier": tier(c["scores"]),
             "priority": priority(c["scores"])})
        led["candidates"][c["id"]].setdefault("decision", "pending")
    save_ledger(led)
    info(f"report: {rd / 'report.md'}")
    return f"report run={rd.name} candidates={len(cands)} A={sum(tier(c['scores']) == 'A' for c in cands)}"


def cmd_decide(args):
    led = load_ledger()
    rd = run_dir(args.run)
    data = read_json(rd / "candidates.json", {"candidates": []})
    ids = {c["id"] for c in data.get("candidates", [])}
    if args.id not in ids:
        raise Fail("E_NO_CANDIDATE", f"{args.id} not in run {rd.name}")
    if args.decision == "merge" and not args.target:
        raise Fail("E_ARGS", "merge needs --target <existing-skill>")
    rec = led["candidates"].setdefault(args.id, {"run": rd.name})
    rec.update({"decision": args.decision, "reason": args.reason or "", "decided_at": now_iso()})
    if args.target:
        rec["target"] = args.target
    save_ledger(led)
    return f"decide {args.id}={args.decision}"


def cmd_close(args):
    rd = run_dir(args.run)
    led = load_ledger()
    idx = read_json(rd / "index.json", {"sessions": []})
    for s in idx["sessions"]:
        led["sessions"][s["id"]] = {"size": s["size"], "mtime": s["mtime"], "run": rd.name,
                                    "closed_at": now_iso(), "title": s.get("title", "")[:80]}
    pending = [cid for cid, c in led["candidates"].items() if c.get("run") == rd.name and c.get("decision") == "pending"]
    save_ledger(led)
    return f"close run={rd.name} sessions_marked={len(idx['sessions'])} pending_candidates={len(pending)}"


def cmd_status(args):
    led = load_ledger()
    by = Counter(c.get("decision", "pending") for c in led["candidates"].values())
    runs = sorted(p.name for p in (home() / "runs").glob("*") if p.is_dir()) if (home() / "runs").exists() else []
    print(f"sessions processed: {len(led['sessions'])}")
    print(f"runs: {', '.join(runs[-5:]) or '-'}")
    for cid, c in sorted(led["candidates"].items(), key=lambda x: (x[1].get("decision") != "pending", x[0])):
        print(f"  [{c.get('decision', 'pending'):<7}] {c.get('tier', '?')} {cid:<36} {c.get('title', '')}")
    return "status " + " ".join(f"{k}={v}" for k, v in sorted(by.items()))


# ------------------------------------------------------- code extraction ---
def find_session_file(cfg: dict, sid: str) -> Path:
    hits = [f for f in discover({**cfg, "include_sidechains": True}) if f.stem.startswith(sid)]
    if not hits:
        raise Fail("E_NO_SESSION", f"session {sid} not found in configured sources")
    if len({f.stem for f in hits}) > 1:
        raise Fail("E_AMBIGUOUS", f"{sid} matches several sessions; give more of the id")
    return hits[0]


def file_history(path: Path) -> dict:
    """Per file path: last full Write content, and edits applied after it (in order)."""
    hist = {}
    for r in iter_records(path):
        if r.get("type") != "assistant":
            continue
        for b in (r.get("message") or {}).get("content") or []:
            if not isinstance(b, dict) or b.get("type") != "tool_use":
                continue
            inp, name = b.get("input") or {}, b.get("name")
            fp = inp.get("file_path")
            if not fp:
                continue
            h = hist.setdefault(fp, {"content": None, "edits": [], "writes": 0})
            if name == "Write" and isinstance(inp.get("content"), str):
                h["content"], h["edits"], h["writes"] = inp["content"], [], h["writes"] + 1
            elif name == "Edit":
                h["edits"].append((inp.get("old_string", ""), inp.get("new_string", ""), bool(inp.get("replace_all"))))
            elif name == "MultiEdit":
                for e in inp.get("edits") or []:
                    h["edits"].append((e.get("old_string", ""), e.get("new_string", ""), bool(e.get("replace_all"))))
    return hist


def replay(h: dict):
    """Apply recorded edits to the last Write. Returns (text or None, edits_applied, edits_failed)."""
    if h["content"] is None:
        return None, 0, len(h["edits"])
    text, ok, bad = h["content"], 0, 0
    for old, new, all_ in h["edits"]:
        if old and old in text:
            text = text.replace(old, new) if all_ else text.replace(old, new, 1)
            ok += 1
        else:
            bad += 1
    return text, ok, bad


def cmd_files(args):
    cfg = load_config()
    f = find_session_file(cfg, args.session)
    hist = file_history(f)
    for fp, h in sorted(hist.items()):
        on_disk = Path(fp).exists()
        state = "full" if h["content"] is not None else "edits-only"
        print(f"{state:<10} writes={h['writes']} edits={len(h['edits']):<3} on_disk={'yes' if on_disk else 'no ':<3} {fp}")
    return f"files session={f.stem[:8]} count={len(hist)}"


def cmd_extract(args):
    cfg = load_config()
    f = find_session_file(cfg, args.session)
    hist = file_history(f)
    match = {fp: h for fp, h in hist.items() if args.path in fp}
    if not match:
        raise Fail("E_NO_FILE", f"no file matching '{args.path}' was written in {f.stem[:8]} (see `sd files`)")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    red = Redactor()
    done = []
    for fp, h in match.items():
        text, ok, bad = replay(h)
        src = "transcript"
        if Path(fp).exists() and args.prefer_disk:
            text, src = Path(fp).read_text(encoding="utf-8", errors="replace"), "disk"
        if text is None:
            print(f"SKIP {fp}: only edits were recorded (file created outside this session); read it from disk if it still exists")
            continue
        name = Path(fp.replace("\\", "/")).name
        target = out / name
        if target.exists():
            target = out / (hashlib.sha1(fp.encode()).hexdigest()[:6] + "-" + name)
        target.write_text(red(text), encoding="utf-8")
        note = f" edits_applied={ok} edits_failed={bad}" if src == "transcript" and (ok or bad) else ""
        print(f"{target}  <- {fp} ({src}{note})")
        done.append(target)
    return f"extract files={len(done)} redactions={sum(red.hits.values())}"


# --------------------------------------------------------------- scaffold ---
def cmd_scaffold(args):
    rd = run_dir(args.run)
    cfg, led = load_config(), load_ledger()
    data = read_json(rd / "candidates.json", {"candidates": []})
    c = next((x for x in data.get("candidates", []) if x["id"] == args.id), None)
    if not c:
        raise Fail("E_NO_CANDIDATE", f"{args.id} not in run {rd.name}")
    dec = led["candidates"].get(args.id, {}).get("decision")
    if dec != "accept" and not args.force:
        raise Fail("E_NOT_ACCEPTED", f"{args.id} decision is {dec or 'pending'}; record `sd decide ... accept` first")
    hub = Path(os.path.expanduser(args.hub or cfg.get("skill_hub", "")))
    base = hub / "skills" if (hub / "skills").is_dir() else home() / "drafts"
    dest = base / args.id
    if dest.exists():
        raise Fail("E_EXISTS", f"{dest} already exists")
    red = Redactor()
    tpl = (SKILL_DIR / "assets" / "SKILL.template.md").read_text(encoding="utf-8")
    desc = _one_line(c["summary"], 600)
    if c["packaging"].get("triggers"):
        desc += " 在以下场景使用：" + "、".join(c["packaging"]["triggers"]) + "。"
    desc = desc.replace("<", "(").replace(">", ")")[:1000]
    body = (tpl.replace("{{name}}", c["id"]).replace("{{description}}", red(desc))
            .replace("{{title}}", red(c["title"])).replace("{{problem}}", red(c["problem"]))
            .replace("{{summary}}", red(c["summary"])).replace("{{kind}}", c["kind"])
            .replace("{{run}}", rd.name))
    dest.mkdir(parents=True)
    (dest / "SKILL.md").write_text(body, encoding="utf-8")
    tags = c["packaging"].get("tags") or [c["kind"].replace("+", "-")]
    (dest / "hub.yaml").write_text(
        f"status: draft\nversion: 0.1.0\nowner: {cfg.get('owner', 'dean')}\n"
        f"tags: [{', '.join(tags)}]\nnotes: distilled by session-distiller run {rd.name}\n", encoding="utf-8")
    (dest / "CHANGELOG.md").write_text(
        f"# Changelog\n\n## 0.1.0 — {dt.date.today().isoformat()}\n\n- 由 session-distiller 从历史会话提炼的初稿（run {rd.name}）。\n",
        encoding="utf-8")
    (dest / "references").mkdir()
    ev = ["# 提炼证据（已脱敏）", "", f"来源 run：{rd.name}。以下为候选引用的会话片段，用于还原上下文、写测试用例。", ""]
    for e in c["evidence"]:
        dg = next(iter(sorted((rd / "digests").glob(f"{e['session']}*.md"))), None)
        ev.append(f"## 会话 {e['session'][:8]} · {', '.join(e.get('turns', []))}")
        ev.append("")
        if e.get("quote"):
            ev += [f"> {red(e['quote'])}", ""]
        if dg:
            txt = dg.read_text(encoding="utf-8")
            for t in e.get("turns", []):
                m = re.search(rf"^### {re.escape(t)} ·[\s\S]*?(?=^### T\d+ ·|\Z)", txt, re.M)
                if m:
                    ev += [m.group(0).strip(), ""]
    (dest / "references" / "evidence.md").write_text("\n".join(ev) + "\n", encoding="utf-8")
    for d in ("scripts", "evals"):
        (dest / d).mkdir()
    if c["packaging"].get("scripts"):
        (dest / "scripts" / "README.md").write_text(
            "待实现的脚本：\n\n" + "\n".join(f"- `{s}`" for s in c["packaging"]["scripts"]) + "\n", encoding="utf-8")
    case = dest / "evals" / "basic-usage"
    (case / "graders").mkdir(parents=True)
    (case / "prompt.md").write_text(
        "---\ntags: [skill-creator]\nmax_turns: 20\ntimeout_seconds: 600\nallowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash]\n---\n\n"
        "TODO：从 references/evidence.md 里挑一个真实请求，改写成用户会说的话。\n", encoding="utf-8")
    (case / "case.yaml").write_text(
        f'schema_version: "1.1"\nname: basic-usage\nexpected_outcome: |\n  TODO：描述 {c["id"]} 正确工作时的结果。\n',
        encoding="utf-8")
    (case / "graders" / "01-expected-output.md").write_text(
        "---\ntype: llm\nfocus: trace\nweight: 1\n---\n\nThe response completes the task the prompt asks for.\n", encoding="utf-8")
    led["candidates"][args.id].update({"scaffolded_to": str(dest), "scaffolded_at": now_iso()})
    save_ledger(led)
    info(f"scaffold: {dest}")
    return f"scaffold {args.id} -> {dest}"


# ----------------------------------------------------------- self-update ---
def cmd_version(args):
    info(f"session-distiller {version()}  skill_dir={SKILL_DIR}")
    rec = SKILL_DIR / "SOURCE"
    if rec.exists():
        for line in rec.read_text(encoding="utf-8").splitlines():
            info("source." + line)
    else:
        info(f"source.repo={SOURCE_REPO} (path {SOURCE_PATH}, branch {SOURCE_BRANCH}; this copy has no SOURCE record)")
    return f"version {version()}"


def _git(*a, cwd=None):
    r = subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()


def _semver(v):
    try:
        return tuple(int(x) for x in v.split("-")[0].split("."))
    except ValueError:
        return (0,)


def cmd_update(args):
    if "plugins" in SKILL_DIR.parts:
        raise Fail("E_SRC_PLUGIN", "installed as a plugin: run `/plugin marketplace update blacklake-skill-hub` then `/plugin update session-distiller`")
    src = Path(os.environ.get("SD_SRC") or Path.home() / "skill-hub")
    if not (src / ".git").exists():
        rc, out = _git("clone", "-q", "-b", SOURCE_BRANCH, SOURCE_REPO, str(src))
        if rc:
            raise Fail("E_SRC_CLONE", f"cannot clone {SOURCE_REPO} (private repo: needs the user's GitHub login): {out[-200:]}")
    else:
        rc, out = _git("status", "--porcelain", "--", SOURCE_PATH, cwd=src)
        if out:
            raise Fail("E_SRC_DIRTY", f"local edits in {src / SOURCE_PATH}; commit them on a branch or discard first")
        for cmd, code in ((("fetch", "-q", "origin", SOURCE_BRANCH), "E_SRC_FETCH"),
                          (("checkout", "-q", SOURCE_BRANCH), "E_SRC_FETCH"),
                          (("merge", "-q", "--ff-only", f"origin/{SOURCE_BRANCH}"), "E_SRC_DIVERGED")):
            rc, out = _git(*cmd, cwd=src)
            if rc:
                raise Fail(code, f"git {' '.join(cmd)}: {out[-200:]}")
    new_dir = src / SOURCE_PATH
    if not (new_dir / "scripts" / "install_local.py").exists():
        raise Fail("E_SRC_LAYOUT", f"{new_dir} not found in the source repo")
    new_ver = (new_dir / "VERSION").read_text(encoding="utf-8").strip()
    _, new_commit = _git("rev-parse", "--short", "HEAD", cwd=src)
    old_commit = ""
    if (SKILL_DIR / "SOURCE").exists():
        m = re.search(r"^commit=(.*)$", (SKILL_DIR / "SOURCE").read_text(encoding="utf-8"), re.M)
        old_commit = m.group(1).strip() if m else ""
    if old_commit and old_commit == new_commit:
        return f"update already_latest version={new_ver} commit={new_commit}"
    if _semver(new_ver) < _semver(version()) and not args.allow_downgrade:
        raise Fail("E_SRC_DOWNGRADE", f"{SOURCE_BRANCH} has {new_ver} but {version()} is installed; keeping it (--allow-downgrade to force)")
    r = subprocess.run([sys.executable, str(new_dir / "scripts" / "install_local.py"), "--dest", str(SKILL_DIR.parent)],
                       capture_output=True, text=True)
    if r.returncode:
        raise Fail("E_SRC_INSTALL", (r.stdout + r.stderr)[-300:])
    return f"update version={version()}->{new_ver} commit={old_commit or '?'}->{new_commit} restart_session=yes"


# ------------------------------------------------------------------- main ---
def build_parser():
    p = argparse.ArgumentParser(prog="sd", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    def sel(sp):
        sp.add_argument("--since", help="ISO date or Nd (e.g. 30d): sessions active since")
        sp.add_argument("--until", help="ISO date")
        sp.add_argument("--project", help="substring of the session cwd")
        sp.add_argument("--session", action="append", help="session id (prefix ok); repeatable; bypasses other filters")
        sp.add_argument("--all", action="store_true", help="include sessions already processed")
        sp.add_argument("--min-turns", type=int, help="skip sessions with fewer human turns")
        sp.add_argument("--limit", type=int, help="newest N only")

    sp = sub.add_parser("init"); sp.add_argument("--force", action="store_true"); sp.set_defaults(fn=cmd_init)
    sub.add_parser("doctor").set_defaults(fn=cmd_doctor)
    sp = sub.add_parser("scan"); sel(sp); sp.add_argument("--json", action="store_true"); sp.set_defaults(fn=cmd_scan)
    sp = sub.add_parser("digest"); sel(sp); sp.add_argument("--run"); sp.add_argument("--max-chars", type=int)
    sp.set_defaults(fn=cmd_digest)
    sub.add_parser("catalog").set_defaults(fn=cmd_catalog)
    for name, fn in (("validate", cmd_validate), ("report", cmd_report), ("close", cmd_close)):
        sp = sub.add_parser(name); sp.add_argument("run", nargs="?", default="latest"); sp.set_defaults(fn=fn)
    sp = sub.add_parser("decide"); sp.add_argument("run"); sp.add_argument("id")
    sp.add_argument("decision", choices=["accept", "merge", "reject", "defer"])
    sp.add_argument("--reason"); sp.add_argument("--target"); sp.set_defaults(fn=cmd_decide)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    sp = sub.add_parser("scaffold"); sp.add_argument("run"); sp.add_argument("id"); sp.add_argument("--hub")
    sp.add_argument("--force", action="store_true"); sp.set_defaults(fn=cmd_scaffold)
    sp = sub.add_parser("files"); sp.add_argument("session"); sp.set_defaults(fn=cmd_files)
    sp = sub.add_parser("extract"); sp.add_argument("session"); sp.add_argument("path", help="substring of the file path")
    sp.add_argument("--out", required=True); sp.add_argument("--prefer-disk", action="store_true")
    sp.set_defaults(fn=cmd_extract)
    sub.add_parser("version").set_defaults(fn=cmd_version)
    sp = sub.add_parser("update"); sp.add_argument("--allow-downgrade", action="store_true"); sp.set_defaults(fn=cmd_update)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary = args.fn(args)
        print(f"RESULT ok {summary}")
        return 0
    except Fail as e:
        print(f"RESULT fail code={e.code} {e.msg}")
        return 1
    except Exception as e:  # never die without the RESULT line
        print(f"RESULT fail code=E_INTERNAL {type(e).__name__}: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
