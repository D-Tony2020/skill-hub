"""Feishu side of `diagram.py sync`: lark-cli / whiteboard-cli runners, board bookkeeping, foreign-edit guard.

Everything that touches Feishu goes through the official CLIs:
- lark-cli (npm @larksuite/cli): docs +update (create a blank whiteboard block), whiteboard +update / +export
- whiteboard-cli (npm @larksuite/whiteboard-cli): --check (text overflow) and a local DSL preview
Both are looked up as installed npm packages and run with node directly (Windows .cmd shims mangle <, >, &).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

WB_PKG = "@larksuite/whiteboard-cli"
WB_VERSION = "^0.2.13"


def _npm_global_js(pkg: str, rel: str) -> Path | None:
    roots = []
    if os.name == "nt" and os.environ.get("APPDATA"):
        roots.append(Path(os.environ["APPDATA"]) / "npm" / "node_modules")
    npm = shutil.which("npm")
    if npm and os.name != "nt":
        roots.append(Path(npm).resolve().parent.parent / "lib" / "node_modules")
    for r in roots:
        p = r / pkg / rel
        if p.exists():
            return p
    return None


def _node_cmd(env_key: str, pkg: str, rel: str, exe: str, fallback: list[str] | None = None) -> list[str] | None:
    if os.environ.get(env_key):  # "none" disables the tool (tests, or to force the manual path)
        v = os.environ[env_key]
        return None if v.lower() in ("none", "off", "0") else v.split("|")
    js = _npm_global_js(pkg, rel)
    node = shutil.which("node")
    if js and node:
        return [node, str(js)]
    found = shutil.which(exe)
    if found:
        return [found]
    return fallback


def lark_cmd() -> list[str] | None:
    return _node_cmd("AD_LARK_CLI", "@larksuite/cli", "scripts/run.js", "lark-cli")


def wb_cmd() -> list[str] | None:
    npx = shutil.which("npx")
    return _node_cmd("AD_WHITEBOARD_CLI", WB_PKG, "bin/cli.js", "whiteboard-cli",
                     [npx, "-y", f"{WB_PKG}@{WB_VERSION}"] if npx else None)


class LarkError(RuntimeError):
    def __init__(self, msg, rc=1, payload=None):
        super().__init__(msg)
        self.rc, self.payload = rc, payload


def _run(cmd: list[str], cwd: Path, timeout=180) -> tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, timeout=timeout)
    except OSError as e:
        return 127, "", f"无法启动 {cmd[0]}：{e.strerror or e}"
    except subprocess.TimeoutExpired:
        return 124, "", f"{Path(cmd[-1]).name if cmd else ''} 超时（{timeout}s）"
    dec = lambda b: (b or b"").decode("utf-8", errors="replace")  # noqa: E731
    return p.returncode, dec(p.stdout), dec(p.stderr)


def _json(text: str):
    text = text.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        i = text.find("{")
        if i >= 0:
            try:
                return json.loads(text[i:])
            except json.JSONDecodeError:
                return None
    return None


def lark(args: list[str], cwd: Path, timeout=180) -> dict:
    """Run lark-cli as the user; file arguments must be relative to cwd. Raises LarkError with a readable message."""
    base = lark_cmd()
    if not base:
        raise LarkError("找不到 lark-cli（npm i -g @larksuite/cli）", 127)
    rc, out, err = _run([*base, *args, "--as", "user"], cwd, timeout)
    data = _json(out) or _json(err)
    if rc == 10:  # high-risk confirmation gate: never auto-confirm
        raise LarkError("lark-cli 要求确认高风险写操作，需先征得用户同意：" + (err or out).strip()[:400], 10, data)
    if rc != 0 or (isinstance(data, dict) and data.get("ok") is False):
        msg = ""
        if isinstance(data, dict):
            e = data.get("error") or {}
            msg = e.get("message") or e.get("msg") or data.get("msg") or ""
            hint = e.get("hint")
            if hint:
                msg += f"（{hint}）"
        msg = msg or (err or out).strip()[-400:]
        low = msg.lower()
        if any(k in low for k in ("auth", "token expired", "not logged", "login", "unauthorized", "99991")):
            msg += "\n  → 需要重新授权：lark-cli auth login --recommend"
        raise LarkError(msg, rc or 1, data)
    return data if isinstance(data, dict) else {"raw": out}


# ------------------------------------------------------------------ whiteboard-cli
def wb_check(dsl: Path) -> list[str]:
    """Text that would overflow its box in Feishu (whiteboard-cli's own layout engine). [] when clean or unavailable."""
    base = wb_cmd()
    if not base:
        return ["（未安装 whiteboard-cli，跳过飞书排版检查）"]
    rc, out, err = _run([*base, "-i", dsl.name, "--check"], dsl.parent, 120)
    data = _json(out)
    if not isinstance(data, dict):
        return [f"（whiteboard-cli 检查失败：{(err or out).strip()[:200]}）"]
    chk = (data.get("data") or {}).get("check") or data.get("check") or {}
    issues = []
    for it in chk.get("issues") or []:
        kind = it.get("type") or it.get("kind") or ""
        if "overflow" in kind.lower() or "occlusion" in kind.lower():
            who = it.get("nodeId") or it.get("id") or it.get("node") or ""
            issues.append(f"{who}: {it.get('message') or kind}")
    return issues


def wb_render(dsl: Path, png: Path) -> bool:
    base = wb_cmd()
    if not base:
        return False
    rc, _, _ = _run([*base, "-i", dsl.name, "-o", os.path.relpath(png, dsl.parent)], dsl.parent, 180)
    return rc == 0 and png.exists()


# ------------------------------------------------------------------ boards
def create_board(doc: str, workdir: Path) -> dict:
    """Append one blank whiteboard block at the end of the doc -> {'whiteboard': token, 'block_id': id}."""
    xml = workdir / "_new_board.xml"
    xml.write_text('<whiteboard type="blank"></whiteboard>', encoding="utf-8")
    try:
        res = lark(["docs", "+update", "--doc", doc, "--command", "append", "--content", "@" + xml.name], workdir)
    finally:
        xml.unlink(missing_ok=True)
    blocks = (((res.get("data") or {}).get("document") or {}).get("new_blocks")) or []
    for b in blocks:
        if b.get("block_type") == "whiteboard" and b.get("block_token"):
            return {"whiteboard": b["block_token"], "block_id": b.get("block_id")}
    raise LarkError("文档里新建画板后没拿到画板 token：" + json.dumps(res, ensure_ascii=False)[:400])


def write_board(token: str, payload: Path, idem: str) -> dict:
    return lark(["whiteboard", "+update", "--whiteboard-token", token, "--input_format", "raw",
                 "--source", "@" + payload.name, "--overwrite", "--idempotent-token", idem], payload.parent, 300)


def export_raw(token: str, workdir: Path) -> list[dict]:
    res = lark(["whiteboard", "+export", "--whiteboard-token", token, "--output-type", "raw"], workdir)
    return _nodes_of(res)


def export_preview(token: str, png: Path) -> bool:
    lark(["whiteboard", "+export", "--whiteboard-token", token, "--output-type", "preview",
          "--output", png.name, "--overwrite"], png.parent)
    return png.exists()


def export_both(token: str, png: Path, parallel: bool = True) -> tuple[str, bool]:
    """Board fingerprint and preview image (both read-only). Run them concurrently only when the token is known to be
    fresh (right after a successful write): two lark-cli processes refreshing an expiring token at the same time could
    race on Feishu's single-use refresh token."""
    if not parallel:
        return fingerprint(export_raw(token, png.parent)), export_preview(token, png)
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(2) as ex:
        raw = ex.submit(export_raw, token, png.parent)
        pre = ex.submit(export_preview, token, png)
        return fingerprint(raw.result()), pre.result()


def _nodes_of(obj) -> list[dict]:
    """Find the node list in whatever envelope +export raw returns."""
    if isinstance(obj, list):
        return obj if all(isinstance(x, dict) for x in obj) else []
    if isinstance(obj, dict):
        if isinstance(obj.get("nodes"), list):
            return obj["nodes"]
        for v in obj.values():
            found = _nodes_of(v)
            if found:
                return found
    return []


def fingerprint(nodes: list[dict]) -> str:
    """Content fingerprint of a board: shape kinds, rounded geometry and texts (ids are server-assigned)."""
    rows = []
    for n in nodes:
        t = (n.get("text") or {}).get("text", "")
        caps = "|".join(c.get("text", "") for c in ((n.get("connector") or {}).get("captions") or {}).get("data", []))
        kind = n.get("type", "")
        sub = (n.get("composite_shape") or {}).get("type", "")
        geo = tuple(round(float(n.get(k, 0) or 0)) for k in ("x", "y", "width", "height"))
        rows.append(json.dumps([kind, sub, geo, t, caps], ensure_ascii=False))
    rows.sort()
    return hashlib.sha1("\n".join(rows).encode("utf-8")).hexdigest()[:16]


def load_json(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_json(p: Path, obj: dict) -> None:
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")


def doc_url(doc: str) -> str:
    return doc if doc.startswith("http") else f"https://feishu.cn/docx/{doc}"


if __name__ == "__main__":
    print(lark_cmd(), wb_cmd(), file=sys.stderr)
