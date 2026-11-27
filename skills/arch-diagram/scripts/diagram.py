#!/usr/bin/env python3
"""arch-diagram CLI — file management, quality gate, export, history, delivery.

  py -3 diagram.py new <slug> --title "标题"
  py -3 diagram.py inspect <slug>
  py -3 diagram.py check <slug>                  # validate + spec consistency + preview PNG
  py -3 diagram.py export <slug> [--pdf] [--highlight]
  py -3 diagram.py snapshot <slug> -m "说明"
  py -3 diagram.py round <slug> -m "说明"        # check -> export -> snapshot (one round)
  py -3 diagram.py diff <slug> [--from r01] [--to r03|current]
  py -3 diagram.py restore <slug> r02
  py -3 diagram.py legend <slug>
  py -3 diagram.py mermaid <slug>
  py -3 diagram.py adopt <slug> generated.drawio   # take autolayout.py output into house conventions
  py -3 diagram.py sync <slug>
  py -3 diagram.py list
  py -3 diagram.py doctor                        # where things are, what is missing (run first on a new machine)

Windows uses `py -3`; macOS / Linux use `python3`.

<slug> may also be a path to a .drawio file or to its folder.
Exit codes: 0 ok · 1 check failed · 2 usage / not configured · 3 required tool missing
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import drawio_model as dm  # noqa: E402
import house_style as hs  # noqa: E402

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# ------------------------------------------------------------------ environment
def diagrams_root() -> Path:
    env = os.environ.get("ARCH_DIAGRAMS_ROOT")
    if env:
        return Path(env).expanduser()
    docs = Path.home() / "Documents"
    return (docs if docs.exists() else Path.home()) / "arch-diagrams"


SKILL_DIR = HERE.parent


def drawio_skill_candidates() -> list[Path]:
    """drawio-skill is looked up next to this skill first (same skills/ folder, whatever the
    install scope), then the project-level and user-level skill folders."""
    env = os.environ.get("DRAWIO_SKILL_DIR")
    cands = [Path(env).expanduser()] if env else []
    cands += [SKILL_DIR.parent / "drawio-skill", Path.cwd() / ".claude/skills/drawio-skill",
              Path.home() / ".claude/skills/drawio-skill", Path.home() / ".agents/skills/drawio-skill"]
    return cands


def drawio_skill_dir() -> Path | None:
    for c in drawio_skill_candidates():
        if c and (Path(c) / "scripts/validate.py").exists():
            return Path(c)
    return None


def drawio_exe() -> str | None:
    env = os.environ.get("DRAWIO_CLI")
    if env:
        return env
    ds = drawio_skill_dir()
    if ds:
        sys.path.insert(0, str(ds / "scripts"))
        try:
            from drawio_cli import resolve_drawio  # type: ignore
            exe = resolve_drawio()
            if exe:
                return str(exe)
        except Exception:
            pass
    for c in (Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/draw.io/draw.io.exe",
              Path(os.environ.get("ProgramFiles", "")) / "draw.io/draw.io.exe",
              Path("/Applications/draw.io.app/Contents/MacOS/draw.io")):
        if c.is_absolute() and c.is_file():
            return str(c)
    return shutil.which("drawio") or shutil.which("draw.io")


def die(msg: str, code: int = 2):
    print(f"✗ {msg}")
    sys.exit(code)


# ------------------------------------------------------------------ paths
VERSION = "2.1.3"
_PHASES: dict[str, float] = {}


class phase:
    """`with phase("导出"):` accumulates wall time per phase (round summary + _perf.jsonl)."""

    def __init__(self, name: str):
        self.name = name

    def __enter__(self):
        self.t0 = time.perf_counter()

    def __exit__(self, *exc):
        _PHASES[self.name] = _PHASES.get(self.name, 0.0) + time.perf_counter() - self.t0
        return False


def phase_summary() -> str:
    return "⏱ " + " · ".join(f"{k} {v:.1f}s" for k, v in _PHASES.items()) + f" · 共 {sum(_PHASES.values()):.1f}s"


def perf_log(entry: dict) -> None:
    """Append one JSON line per command to <root>/_perf.jsonl. Never breaks the command."""
    try:
        root = diagrams_root()
        root.mkdir(parents=True, exist_ok=True)
        with open(root / "_perf.jsonl", "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


class Target:
    def __init__(self, arg: str):
        p = Path(arg).expanduser()
        if p.suffix == ".drawio" and p.exists():
            self.drawio = p.resolve()
            self.dir = self.drawio.parent
            self.slug = self.drawio.stem
        elif p.is_dir() and (p / f"{p.name}.drawio").exists():
            self.dir, self.slug = p.resolve(), p.name
            self.drawio = self.dir / f"{self.slug}.drawio"
        else:
            self.dir = diagrams_root() / arg
            self.slug = arg
            self.drawio = self.dir / f"{arg}.drawio"
        self.spec = self.dir / f"{self.slug}.spec.json"
        self.history = self.dir / "history"

    def must_exist(self):
        if not self.drawio.exists():
            die(f"找不到图文件：{self.drawio}（先用 new 创建，或传入 .drawio 路径）")
        return self

    def out(self, suffix: str, page: int = 1) -> Path:
        base = self.slug if page == 1 else f"{self.slug}.p{page}"
        return self.dir / f"{base}{suffix}"

    def snapshots(self) -> list[tuple[int, Path]]:
        out = []
        if self.history.exists():
            for f in self.history.glob(f"{self.slug}.r*.drawio"):
                m = re.search(r"\.r(\d+)\.drawio$", f.name)
                if m:
                    out.append((int(m.group(1)), f))
        return sorted(out)

    def snapshot_path(self, ref: str) -> Path:
        m = re.fullmatch(r"r?(\d+)", ref.strip().lower())
        if not m:
            die(f"版本号格式应为 r01 / 1：{ref}")
        n = int(m.group(1))
        for k, f in self.snapshots():
            if k == n:
                return f
        die(f"没有快照 r{n:02d}（现有：{', '.join(f'r{k:02d}' for k, _ in self.snapshots()) or '无'}）")


# ------------------------------------------------------------------ helpers
def normalize_in_place(t: Target) -> str | None:
    """Make the file plain, standard draw.io XML before anything reads it: inflate a compressed file
    (draw.io's own save) and expand style macros (Claude's shorthand). Returns a note or None."""
    note = None
    tree, compressed = dm.load(t.drawio)
    if compressed:
        t.history.mkdir(parents=True, exist_ok=True)
        stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = t.history / f"_compressed-{stamp}.drawio"
        shutil.copy2(t.drawio, backup)
        dm.save(tree, t.drawio)
        note = f"检测到压缩格式（draw.io 保存所致），已解压为明文；原文件备份：{backup.name}"
    text = t.drawio.read_text(encoding="utf-8")
    if 'style="@' in text:
        new, n = dm.expand_macros_text(text)
        if n:
            dm.write_text(t.drawio, new)
    return note


def page_count(path: Path) -> int:
    tree, _ = dm.load(path)
    return max(1, len(dm.pages(tree)))


def _drawio_job(exe: str, args: list[str], expect: Path) -> tuple[bool, str]:
    before = expect.stat().st_mtime if expect.exists() else None
    try:
        proc = subprocess.run([exe, *args], capture_output=True, text=True, timeout=180,
                              encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return False, f"✗ draw.io 导出超时：{expect.name}"
    except OSError as e:  # e.g. DRAWIO_CLI points at a missing file
        return False, f"✗ 无法启动 draw.io（{exe}）：{e.strerror or e}"
    if expect.exists() and (before is None or expect.stat().st_mtime > before):
        return True, ""
    tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
    return False, f"✗ 导出失败：{expect.name} {' | '.join(tail)}"


def run_drawio_jobs(jobs: list[tuple[list[str], Path]]) -> list[bool]:
    """Run draw.io exports concurrently (export mode skips draw.io's single-instance lock). Determinism test on
    Windows, 40 runs each: sequential 3/40 vs concurrent 2/40 PNGs came out as draw.io's rare RGBA variant
    (~30 anti-aliased title pixels, invisible) -- a draw.io trait present in v1 too, not caused by concurrency.
    AD_EXPORT_PARALLEL=1 forces sequential."""
    exe = drawio_exe()
    if not exe:
        die("找不到 draw.io 桌面版（导出需要它）。Windows：winget install --id JGraph.Draw -e", 3)
    try:
        width = max(1, int(os.environ.get("AD_EXPORT_PARALLEL", "4")))
    except ValueError:
        width = 4
    if width == 1 or len(jobs) <= 1:
        results = [_drawio_job(exe, args, dest) for args, dest in jobs]
    else:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(width, len(jobs))) as pool:
            results = list(pool.map(lambda job: _drawio_job(exe, *job), jobs))
    for ok, msg in results:
        if not ok:
            print(msg)
    return [ok for ok, _ in results]


def run_drawio(args: list[str], expect: Path) -> bool:
    return run_drawio_jobs([(args, expect)])[0]


def _png_args(src: Path, dest: Path, page: int, preview: bool) -> list[str]:
    size = ["--width", "2000"] if preview else ["-s", "2"]
    return ["-x", "-f", "png", *size, "-p", str(page), "-o", str(dest), str(src)]


def _svg_args(src: Path, dest: Path, page: int) -> list[str]:
    return ["-x", "-f", "svg", "-e", "--embed-svg-images", "-p", str(page), "-o", str(dest), str(src)]


def export_png(src: Path, dest: Path, page: int, preview: bool) -> bool:
    return run_drawio(_png_args(src, dest, page, preview), dest)


def export_svg(src: Path, dest: Path, page: int) -> bool:
    return run_drawio(_svg_args(src, dest, page), dest)


def export_previews(t: "Target") -> bool:
    """Separate review previews (--width 2000), all pages in parallel; prints one line per page."""
    n = page_count(t.drawio)
    dests = [t.out(".preview.png", p) for p in range(1, n + 1)]
    res = run_drawio_jobs([(_png_args(t.drawio, d, p, True), d) for p, d in enumerate(dests, 1)])
    for p, (d, ok) in enumerate(zip(dests, res), 1):
        if ok:
            print(f"🖼 预览（第 {p} 页）：{d}   ← 必须打开看一眼")
    return all(res)


def run_validate(path: Path) -> tuple[int, int, list[str]]:
    ds = drawio_skill_dir()
    if not ds:
        die("找不到 drawio-skill：先装好它（与本 skill 放在同一个 skills 目录），或设环境变量 DRAWIO_SKILL_DIR；`diagram.py doctor` 可查看查找位置", 3)
    proc = subprocess.run([sys.executable, str(ds / "scripts/validate.py"), str(path), "--score"],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    text = (proc.stdout + proc.stderr).strip()
    m = re.search(r"(\d+) error\(s\), (\d+) warning\(s\)", text)
    errs, warns = (int(m.group(1)), int(m.group(2))) if m else (1 if proc.returncode else 0, 0)
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return errs, warns, lines


def load_spec(t: Target) -> dict | None:
    if not t.spec.exists():
        return None
    try:
        return json.loads(t.spec.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        die(f"清单 JSON 格式错误：{t.spec.name} 第 {e.lineno} 行：{e.msg}", 1)


def all_cells(path: Path) -> tuple[list[str], dict[str, dm.Cell]]:
    tree, _ = dm.load(path)
    names, merged = [], {}
    for name, model in dm.pages(tree):
        names.append(name)
        merged.update(dm.cells(model, name))
    return names, merged


def _text_px(line: str, size: float) -> float:
    return sum(size if ord(ch) > 0x2E80 else size * 0.58 for ch in line)


def _overflow(c: dm.Cell) -> bool:
    sm = c.smap
    if not c.geo or "text" in sm or sm.get("shape") in ("umlActor",) or "swimlane" in sm:
        return False
    if sm.get("verticalLabelPosition") == "bottom":
        return False
    w, h = c.geo[2], c.geo[3]
    size = float(sm.get("fontSize", 12) or 12)
    inner_w = max(20.0, w - 16 - (w * 0.25 if "rhombus" in sm else 0))
    inner_h = h - (20 if sm.get("shape") == "cylinder3" else 6) - (h * 0.3 if "rhombus" in sm else 0)
    lines = 0
    for ln in c.text.split("\n"):
        lines += max(1, math.ceil(_text_px(ln, size) / inner_w))
    return lines * size * 1.25 > inner_h + 1


# ------------------------------------------------------------------ spec consistency
def spec_check(spec: dict, cells_by_id: dict[str, dm.Cell], page_names: list[str]):
    errors, warns = [], []
    nodes = spec.get("nodes", {}) or {}
    edges = spec.get("edges", []) or []
    tbd_norm = dm.norm_text(hs.TBD_PREFIX)
    shape_sig = {"datastore": "cylinder3", "actor": "umlActor", "decision": "rhombus",
                 "group": "swimlane", "lane": "swimlane", "note": "note"}
    for nid, n in nodes.items():
        c = cells_by_id.get(nid)
        label = n.get("label", "")
        if c is None:
            errors.append(f"缺少节点：{nid}（{label.splitlines()[0] if label else ''}）—— 清单里有，图里没有（节点 id 必须等于清单 id）")
            continue
        page = n.get("page")
        if page and c.page != page:
            errors.append(f"节点 {nid} 应在页面「{page}」，实际在「{c.page}」")
        got = dm.norm_text(c.label)
        if n.get("status") == "tbd" and got.startswith(tbd_norm):
            got = got[len(tbd_norm):]
        if label and got != dm.norm_plain(label):
            warns.append(f"标签不一致：{nid} 图中为「{c.text.replace(chr(10), ' ')}」，清单为「{label.replace(chr(10), ' ')}」")
        kind = n.get("kind", "")
        if kind and kind not in hs.KINDS:
            warns.append(f"未知类型 kind={kind}（{nid}），可选：{', '.join(hs.KINDS)}")
        sig = shape_sig.get(kind)
        is_container = any(x.parent == nid for x in cells_by_id.values() if x.kind == "vertex")
        if kind in ("group", "lane") and is_container:
            sig = None
        if sig and sig not in c.style:
            warns.append(f"形状与类型不符：{nid} 是 {kind}，样式里没有 {sig}")
        if kind == "external" and "dashed=1" not in c.style and n.get("status") != "tbd":
            warns.append(f"外部系统 {nid} 应为虚线框（dashed=1）")
        if n.get("status") == "tbd" and ("dashed=1" not in c.style or "待定" not in c.text):
            warns.append(f"待定项 {nid} 未按待定样式呈现（需 TBD 样式 + 标签前缀「{hs.TBD_PREFIX}」）")
        grp = n.get("group")
        if grp and c.parent != grp:
            errors.append(f"分组不符：{nid} 应在容器 {grp} 内（parent={grp}），实际 parent={c.parent}")
    # edges (several relations between the same pair are allowed)
    spec_edges = []
    for e in edges:
        a, b = e.get("from"), e.get("to")
        if a not in nodes or b not in nodes:
            errors.append(f"清单关系引用了不存在的节点：{a} → {b}")
            continue
        spec_edges.append(e)
    drawn = [c for c in cells_by_id.values() if c.kind == "edge"]
    used = set()

    def candidates(e):
        a, b = e["from"], e["to"]
        undirected = e.get("type") == "readwrite" or e.get("dir") in ("<->", "--")
        return [c for c in drawn if c.id not in used and
                ((c.source, c.target) == (a, b) or (undirected and (c.source, c.target) == (b, a)))]

    # pass 1: exact label matches first, so parallel edges pair up correctly
    pending = []

    def tbd_check(e, c):
        if e.get("status") == "tbd" and "dashPattern" not in c.style:
            warns.append(f"待定关系 {e['from']} → {e['to']} 未按待定样式呈现（连线追加 TBD_EDGE_SUFFIX，见 style-guide 第 2 节）")

    for e in spec_edges:
        exact = [c for c in candidates(e) if dm.norm_text(c.label) == dm.norm_plain(e.get("label", ""))]
        if exact:
            used.add(exact[0].id)
            tbd_check(e, exact[0])
            if e.get("type") == "readwrite" and not exact[0].bidirectional:
                warns.append(f"读写关系 {e['from']} ↔ {e['to']} 应为双向箭头（startArrow=classic）")
        else:
            pending.append(e)
    # pass 2: same endpoints, different label
    for e in pending:
        a, b = e["from"], e["to"]
        cand = candidates(e)
        if not cand:
            errors.append(f"缺少关系：{a} → {b}" + (f"（{e['label']}）" if e.get("label") else ""))
            continue
        match = cand[0]
        used.add(match.id)
        tbd_check(e, match)
        if e.get("label"):
            warns.append(f"关系标签不一致：{a} → {b} 图中为「{match.text}」，清单为「{e['label']}」")
        if e.get("type") == "readwrite" and not match.bidirectional:
            warns.append(f"读写关系 {a} ↔ {b} 应为双向箭头（startArrow=classic）")
    for c in drawn:
        if c.id in used:
            continue
        if c.source in nodes and c.target in nodes:
            errors.append(f"图中多出关系：{c.source} → {c.target}" + (f"（{c.text}）" if c.text else "") +
                          f"，清单里没有（edge id={c.id}）")
        elif not c.source or not c.target:
            warns.append(f"悬空连线：{c.id}（缺少 source/target）")
    # extra vertices (free-text annotations with no connections are the user's notes: keep, don't nag)
    connected = {x for c in drawn for x in (c.source, c.target) if x}
    for c in cells_by_id.values():
        if c.kind != "vertex" or c.id in nodes or c.id.startswith(hs.RESERVED_PREFIXES):
            continue
        if dm.is_edge_label(c, cells_by_id):
            continue
        if dm.is_text_cell(c) and c.id not in connected:
            continue
        warns.append(f"清单外元素：{c.id}「{c.text.replace(chr(10), ' ')[:30]}」（若是用户手动新增，请并入清单；否则删除）")
    return errors, warns


def lint(cells_by_id: dict[str, dm.Cell]) -> list[str]:
    warns = []
    degree: dict[str, int] = {}
    for c in cells_by_id.values():
        if c.kind == "edge":
            for x in (c.source, c.target):
                if x:
                    degree[x] = degree.get(x, 0) + 1
    unpinned = [c.id for c in cells_by_id.values() if c.kind == "edge" and not c.id.startswith("legend")
                and not (c.points and "edgeStyle" not in c.style) and
                ((degree.get(c.source or "", 0) >= 3 and "exitX" not in c.style) or
                 (degree.get(c.target or "", 0) >= 3 and "entryX" not in c.style))]
    if unpinned:
        warns.append(f"{len(unpinned)} 条连线连在 ≥3 度节点上却未固定端口，可能叠线：{', '.join(unpinned[:6])}"
                     f"{' …' if len(unpinned) > 6 else ''}（可运行 drawio-skill 的 edgeports.py）")
    eaten = [f"{c.id}「{'、'.join(dm.swallowed_tags(c.label))}」" for c in cells_by_id.values()
             if "html=1" in c.style and dm.swallowed_tags(c.label)]
    if eaten:
        warns.append("标签里有会被当成 HTML 标签吞掉的文字（html=1 时字面的 < > & 要写成 &amp;lt; &amp;gt; &amp;amp;）："
                     + "，".join(eaten))
    over = [c.id for c in cells_by_id.values() if c.kind == "vertex" and c.text
            and not c.id.startswith(hs.RESERVED_PREFIXES) and _overflow(c)]
    if over:
        warns.append(f"标签可能溢出节点（文字太长或框太小）：{', '.join(over)}")
    return warns


# ------------------------------------------------------------------ commands
def cmd_new(a):
    t = Target(a.slug)
    if t.drawio.exists():
        die(f"已存在：{t.drawio}")
    t.dir.mkdir(parents=True, exist_ok=True)
    t.history.mkdir(exist_ok=True)
    title = a.title or t.slug
    import xml.sax.saxutils as su
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<mxfile host="arch-diagram">
  <diagram id="page-1" name="{su.escape(a.page or '总览')}">
    <mxGraphModel dx="1200" dy="800" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="0" pageScale="1" math="0" shadow="0">
      <root>
        <mxCell id="0" />
        <mxCell id="1" parent="0" />
        <mxCell id="title" value={su.quoteattr(title)} style="{hs.TITLE_STYLE}" vertex="1" parent="1">
          <mxGeometry x="40" y="20" width="560" height="30" as="geometry" />
        </mxCell>
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>
"""
    dm.write_text(t.drawio, xml)
    dm.write_text(t.spec, json.dumps({"title": title, "nodes": {}, "edges": []}, ensure_ascii=False, indent=2) + "\n")
    print(f"✓ 已创建：{t.dir}\n  图：{t.drawio.name}\n  清单：{t.spec.name}\n  历史：history\\")


def cmd_inspect(a):
    t = Target(a.slug).must_exist()
    note = normalize_in_place(t)
    if note:
        print("ℹ " + note)
    tree, _ = dm.load(t.drawio)
    for name, model in dm.pages(tree):
        cs = dm.cells(model, name)
        print(f"## 页面「{name}」")
        n_legend = sum(1 for c in cs.values() if c.id.startswith("legend"))
        for c in cs.values():
            if c.id.startswith("legend"):
                continue
            if c.kind == "vertex" and not dm.is_edge_label(c, cs):
                x, y, w, h = (round(v) for v in (c.abs or (0, 0, 0, 0)))
                par = f" ∈{c.parent}" if c.parent not in ("1", None) and c.parent in cs else ""
                print(f"  [V] {c.id}{par}  「{c.text.replace(chr(10), ' / ')}」  @({x},{y}) {w}×{h}")
        if n_legend:
            print(f"  （图例：{n_legend} 个元素，已折叠；由 diagram.py legend 维护）")
        for c in cs.values():
            if c.kind == "edge" and not c.id.startswith("legend"):
                arrow = "↔" if c.bidirectional else "→"
                print(f"  [E] {c.id}  {c.source} {arrow} {c.target}" + (f"  「{c.text}」" if c.text else ""))
    snaps = t.snapshots()
    if snaps:
        d, names = dm.diff_files(snaps[-1][1], t.drawio)
        print(f"## 自 r{snaps[-1][0]:02d} 以来的变化\n" + dm.format_diff(d, names))


def cmd_check(a) -> int:
    t = Target(a.slug).must_exist()
    print(f"# 检查 {t.drawio}")
    note = normalize_in_place(t)
    if note:
        print("ℹ " + note)
    page_names, cs = all_cells(t.drawio)
    failed = False
    unknown = sorted(set(re.findall(r'style="(@[^";]*)', t.drawio.read_text(encoding="utf-8"))))
    if unknown:
        print(f"✗ 未知样式代号：{'、'.join(unknown)}（可用代号见 style-guide 第 1、3 节）")
        failed = True
    # 1 structural validation (drawio-skill)
    errs, warns, lines = run_validate(t.drawio)
    status = "✓" if errs == 0 else "✗"
    score = next((ln for ln in lines if ln.startswith("score")), "")
    print(f"{status} 结构校验：{errs} error, {warns} warning  {score}")
    issue_lines = [ln for ln in lines if ln.startswith(("error", "warning"))]
    for ln in issue_lines[:5]:
        print("   " + ln)
    if len(issue_lines) > 5:
        print(f"   …另有 {len(issue_lines) - 5} 条（完整列表：py -3 \"$DS\\scripts\\validate.py\" <file>）")
    failed |= errs > 0
    # 2 spec consistency
    spec = load_spec(t)
    if spec is None:
        print("⚠ 没有清单文件（<slug>.spec.json），跳过一致性检查")
    else:
        e2, w2 = spec_check(spec, cs, page_names)
        print(f"{'✓' if not e2 else '✗'} 清单一致性：{len(e2)} error, {len(w2)} warning"
              f"（清单 {len(spec.get('nodes', {}))} 节点 / {len(spec.get('edges', []))} 关系）")
        for x in e2:
            print("   ✗ " + x)
        for x in w2:
            print("   ⚠ " + x)
        failed |= bool(e2)
    notes = [c for c in cs.values() if c.kind == "vertex" and dm.is_text_cell(c)
             and not c.id.startswith(hs.RESERVED_PREFIXES) and c.id not in ((spec or {}).get("nodes") or {})]
    if notes:
        print(f"ℹ 图中有 {len(notes)} 条自由文本备注（不入清单，原样保留）：" +
              "；".join(c.text.replace(chr(10), ' ')[:20] for c in notes))
    # 3 lints
    for x in lint(cs):
        print("⚠ " + x)
    # 4 manual edits since last snapshot
    snaps = t.snapshots()
    if snaps:
        d, names = dm.diff_files(snaps[-1][1], t.drawio)
        if not d.empty():
            print(f"ℹ 自 r{snaps[-1][0]:02d} 以来的变化（若不是本轮你做的，就是用户手动改的——必须保留）：")
            for ln in dm.format_diff(d, names).splitlines():
                print("   " + ln)
    # 5 preview
    if not a.no_preview:
        failed |= not export_previews(t)
    print("结论：" + ("✗ 未通过，先修复上面的 ✗ 项" if failed else "✓ 通过（仍需人眼检查预览图）"))
    return 1 if failed else 0


def _highlight_copy(t: Target, against: Path | None) -> tuple[Path | None, str]:
    snaps = t.snapshots()
    if against is None:
        if not snaps:
            return None, "没有历史快照，无法生成变更高亮"
        d0, _ = dm.diff_files(snaps[-1][1], t.drawio)
        if d0.empty():
            if len(snaps) < 2:
                return None, "只有一个快照且当前无变化，没有可高亮的变更"
            against = snaps[-2][1]
        else:
            against = snaps[-1][1]
    d, names = dm.diff_files(against, t.drawio)
    ids = d.changed_ids()
    tree, _ = dm.load(t.drawio)
    for _, model in dm.pages(tree):
        for holder, mc, _label in dm._iter_raw_cells(model):
            cid = holder.get("id") or mc.get("id")
            if cid in ids:
                st = re.sub(r"(strokeColor|strokeWidth)=[^;]*;?", "", mc.get("style", ""))
                mc.set("style", st.rstrip(";") + ";" + hs.HIGHLIGHT)
    tmp = Path(tempfile.mkdtemp()) / f"{t.slug}.changes.drawio"
    dm.save(tree, tmp)
    ref = re.search(r"\.r(\d+)\.drawio$", against.name)
    head = f"相对 r{int(ref.group(1)):02d}" if ref else "相对基线"
    return tmp, f"{head}：\n" + dm.format_diff(d, names)


def cmd_export(a) -> int:
    t = Target(a.slug).must_exist()
    note = normalize_in_place(t)
    if note:
        print("ℹ " + note)
    n = page_count(t.drawio)
    jobs, pages = [], []
    for p in range(1, n + 1):
        png, svg = t.out(".png", p), t.out(".drawio.svg", p)
        jobs += [(_png_args(t.drawio, png, p, False), png), (_svg_args(t.drawio, svg, p), svg)]
        pages.append((p, png, svg))
    pdf = t.out(".pdf") if a.pdf else None
    if pdf:
        jobs.append((["-x", "-f", "pdf", "-a", "-o", str(pdf), str(t.drawio)], pdf))
    res = run_drawio_jobs(jobs)
    ok = all(res)
    for i, (p, png, svg) in enumerate(pages):
        if res[2 * i] and res[2 * i + 1]:
            print(f"✓ 第 {p} 页：{png.name}  {svg.name}")
            if getattr(a, "preview_copy", False):  # round: the review preview IS the delivered PNG
                prev = t.out(".preview.png", p)
                shutil.copy2(png, prev)
                print(f"🖼 预览（第 {p} 页）：{prev}   ← 必须打开看一眼")
    if pdf and res[-1]:
        print(f"✓ PDF（全部页面）：{pdf.name}")
    if a.highlight:
        against = t.snapshot_path(a.against) if a.against else None
        tmp, summary = _highlight_copy(t, against)
        if tmp is None:
            print("ℹ " + summary)
        else:
            dests = [t.out(".changes.png", p) for p in range(1, n + 1)]
            hres = run_drawio_jobs([(_png_args(tmp, d, p, False), d) for p, d in enumerate(dests, 1)])
            for p, (d, r) in enumerate(zip(dests, hres), 1):
                if r:
                    print(f"✓ 变更高亮（第 {p} 页）：{d.name}")
            ok &= all(hres)
            print(summary)
            shutil.rmtree(tmp.parent, ignore_errors=True)
    print(f"目录：{t.dir}")
    return 0 if ok else 1


def spec_diff(old: dict, new: dict) -> str:
    on, nn = old.get("nodes", {}) or {}, new.get("nodes", {}) or {}
    key = lambda e: (e.get("from"), e.get("to"), e.get("label", ""))  # noqa: E731
    oe, ne = {key(e): e for e in old.get("edges", [])}, {key(e): e for e in new.get("edges", [])}
    out = []
    for nid in nn:
        if nid not in on:
            out.append(f"+节点 {nid}")
        elif nn[nid] != on[nid]:
            ch = [k for k in set(nn[nid]) | set(on[nid]) if nn[nid].get(k) != on[nid].get(k)]
            out.append(f"~节点 {nid}（{','.join(sorted(ch))}）")
    out += [f"-节点 {nid}" for nid in on if nid not in nn]
    for k, e in ne.items():
        if k not in oe:
            out.append(f"+关系 {k[0]}→{k[1]}")
        elif e != oe[k]:
            out.append(f"~关系 {k[0]}→{k[1]}（{','.join(sorted(x for x in set(e) | set(oe[k]) if e.get(x) != oe[k].get(x)))}）")
    out += [f"-关系 {k[0]}→{k[1]}" for k in oe if k not in ne]
    return "；".join(out)


def cmd_snapshot(a) -> int:
    t = Target(a.slug).must_exist()
    normalize_in_place(t)
    t.history.mkdir(exist_ok=True)
    snaps = t.snapshots()
    summary = "首个版本"
    if snaps:
        prev_spec_path = snaps[-1][1].with_name(snaps[-1][1].name.replace(".drawio", ".spec.json"))
        prev_spec = json.loads(prev_spec_path.read_text(encoding="utf-8")) if prev_spec_path.exists() else {}
        cur_spec = load_spec(t) or {}
        sdiff = spec_diff(prev_spec, cur_spec) if prev_spec or cur_spec else ""
        if dm.canonical(snaps[-1][1]) == dm.canonical(t.drawio) and not sdiff and not a.force:
            print(f"ℹ 与 r{snaps[-1][0]:02d} 内容完全相同，未创建快照")
            return 0
        d, names = dm.diff_files(snaps[-1][1], t.drawio)
        parts = [dm.format_diff(d, names)] if not d.empty() else []
        if sdiff:
            parts.append("清单变化：" + sdiff)
        summary = "\n".join(parts) or "仅有图例或格式层面的变化"
    n = (snaps[-1][0] + 1) if snaps else 1
    tag = f"r{n:02d}"
    shutil.copy2(t.drawio, t.history / f"{t.slug}.{tag}.drawio")
    if t.spec.exists():
        shutil.copy2(t.spec, t.history / f"{t.slug}.{tag}.spec.json")
    stamp = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    log = t.history / "CHANGELOG.md"
    with log.open("a", encoding="utf-8", newline="\n") as f:
        f.write(f"\n## {tag} · {stamp} · {a.message or '（无说明）'}\n\n{summary}\n")
    print(f"✓ 快照 {tag}：history\\{t.slug}.{tag}.drawio\n{summary}")
    return 0


def _drawio_window_titles() -> list[str]:
    """Titles of visible draw.io desktop windows (Windows only; [] elsewhere or on any failure)."""
    if sys.platform != "win32":
        return []
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        titles: list[str] = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def collect(hwnd, _):
            n = user32.GetWindowTextLengthW(hwnd)
            if n and user32.IsWindowVisible(hwnd):
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                if buf.value.endswith("draw.io"):
                    titles.append(buf.value)
            return True

        user32.EnumWindows(collect, 0)
        return titles
    except Exception:
        return []


def open_reminder(drawio_name: str, titles: list[str]) -> str | None:
    """draw.io desktop does not autosave by default: an external edit shows a sync banner instead."""
    if any(drawio_name in title for title in titles):
        return ("ℹ draw.io 正开着这张图：顶部出现「文件已经被修改。点击这里进行同步。」时点它，即可载入最新版本"
                "（未保存的改动会保留）；保存时若被问是否覆盖，选「同步」，选「覆盖」会冲掉刚才的修改。")
    return None


def _remind_if_open(t) -> None:
    msg = open_reminder(t.drawio.name, _drawio_window_titles())
    if msg:
        print(msg)


def cmd_round(a) -> int:
    t = Target(a.slug).must_exist()
    normalize_in_place(t)
    first = not t.snapshots()
    with phase("图例"):
        # The first round decides the legend (same rules as `legend`); later rounds only refresh an existing one,
        # so a legend the user deleted in draw.io stays deleted.
        if first or 'id="legend' in t.drawio.read_text(encoding="utf-8"):
            cmd_legend(argparse.Namespace(slug=a.slug))
    separate = os.environ.get("AD_SEPARATE_PREVIEW") == "1"  # 1 = v1 behaviour (extra preview export)
    with phase("检查"):
        rc = cmd_check(argparse.Namespace(slug=a.slug, no_preview=not separate))
    if rc:
        if not separate:
            with phase("预览"):
                export_previews(t)  # a failed check still gets a preview to diagnose from
        print("✗ 检查未通过，本轮未导出、未快照")
        print(phase_summary())
        return rc
    with phase("导出"):
        # The review preview is the delivered PNG itself: one render instead of two, and Claude reviews
        # exactly the image the user receives.
        rc = cmd_export(argparse.Namespace(slug=a.slug, pdf=False, highlight=False, against=None,
                                           preview_copy=not separate))
    if rc:
        print(phase_summary())
        return rc
    with phase("快照"):
        rc = cmd_snapshot(argparse.Namespace(slug=a.slug, message=a.message, force=False))
    _remind_if_open(t)
    print(phase_summary())
    return rc


def cmd_diff(a) -> int:
    t = Target(a.slug).must_exist()
    normalize_in_place(t)
    snaps = t.snapshots()
    old = t.snapshot_path(a.frm) if a.frm else (snaps[-1][1] if snaps else None)
    if old is None:
        die("没有历史快照")
    new = t.drawio if a.to in (None, "current") else t.snapshot_path(a.to)
    d, names = dm.diff_files(old, new)
    print(f"{old.name} → {new.name}\n" + dm.format_diff(d, names))
    return 0


def cmd_restore(a) -> int:
    t = Target(a.slug).must_exist()
    normalize_in_place(t)
    src = t.snapshot_path(a.ref)
    before = t.snapshots()
    cur = dm.canonical(t.drawio)
    cur_spec = t.spec.read_text(encoding="utf-8") if t.spec.exists() else ""
    same = None
    for k, f in before:
        fs = f.with_name(f.name.replace(".drawio", ".spec.json"))
        if dm.canonical(f) == cur and (fs.read_text(encoding="utf-8") if fs.exists() else "") == cur_spec:
            same = f"r{k:02d}"
    if same is None:
        cmd_snapshot(argparse.Namespace(slug=a.slug, message=f"恢复到 {a.ref} 前的自动快照", force=True))
    after = t.snapshots()
    saved = same or (f"r{after[-1][0]:02d}" if after else "—")
    shutil.copy2(src, t.drawio)
    spec_src = src.with_name(src.name.replace(".drawio", ".spec.json"))
    if spec_src.exists():
        shutil.copy2(spec_src, t.spec)
    how = "与已有快照相同：" if same else "已自动快照为"
    print(f"✓ 已恢复到 {src.name}。恢复前的状态{how} {saved}，需要时 restore {saved} 即可回来")
    _remind_if_open(t)
    return 0


def _legend_name(typ: str, k: str) -> str:
    if typ == "v":
        return hs.KINDS[k][0]
    if typ == "e":
        return hs.EDGES[k][0]
    return "待定项" if typ == "tbd" else "待定关系"


def _legend_xml(items, minx, maxy, actual=None, pfx="legend") -> str:
    import xml.sax.saxutils as su
    cols, cw, rh = 3, 170, 34
    rows = math.ceil(len(items) / cols)
    W, H = cols * cw + 16, rows * rh + 38
    out = []

    def vertex(cid, value, style, x, y, w, h, parent):
        out.append(f'<mxCell id="{cid}" value={su.quoteattr(value)} style="{style}" vertex="1" parent="{parent}">'
                   f'<mxGeometry x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" as="geometry" /></mxCell>')

    vertex(pfx, "图例", hs.KINDS["group"][1] + "fontSize=12;startSize=24;", minx, maxy + 50, W, H, "1")
    for i, (typ, k) in enumerate(items):
        r, ccol = divmod(i, cols)
        x0, y0 = 10 + ccol * cw, 32 + r * rh
        if typ == "v":
            name, style, _ = hs.KINDS[k]
            style = (actual or {}).get(k, style)
            sw, sh = (14, 24) if k == "actor" else (36, 22)
            vertex(f"{pfx}-{k}", "", style, x0, y0, sw, sh, pfx)
        elif typ == "tbd":
            name, style = "待定项", hs.KINDS["agent"][1] + hs.TBD_SUFFIX
            vertex(f"{pfx}-tbd", "", style, x0, y0, 36, 22, pfx)
        else:
            name, style = ("待定关系", hs.EDGES["sync"][1] + hs.TBD_EDGE_SUFFIX) if typ == "tbde" else hs.EDGES[k]
            if typ == "e":
                style = (actual or {}).get(("edge", k), style)
            a_id, b_id = f"{pfx}-e-{typ}-{k}-a", f"{pfx}-e-{typ}-{k}-b"
            dot = "ellipse;fillColor=#90a4ae;strokeColor=none;html=1;"
            vertex(a_id, "", dot, x0, y0 + 9, 4, 4, pfx)
            vertex(b_id, "", dot, x0 + 36, y0 + 9, 4, 4, pfx)
            out.append(f'<mxCell id="{pfx}-e-{typ}-{k}" value="" style="{style}labelBackgroundColor=none;" edge="1" '
                       f'parent="{pfx}" source="{a_id}" target="{b_id}"><mxGeometry relative="1" as="geometry" /></mxCell>')
        vertex(f"{pfx}-t-{typ}-{k}", name, "text;html=1;align=left;verticalAlign=middle;fontFamily=Arial;fontSize=11;",
               x0 + 46, y0, cw - 52, 22, pfx)
    return "\n".join(out)


_LEGEND_CELL = re.compile(r'\s*<mxCell id="legend[^"]*"[^>]*?(?:/>|>.*?</mxCell>)', re.S)


def _page_legend_items(spec: dict, page_name: str, first: bool):
    nodes = spec.get("nodes", {}) or {}
    on_page = {nid for nid, n in nodes.items() if n.get("page") == page_name or (first and not n.get("page"))}
    present = {nodes[nid].get("kind") for nid in on_page} - {"group", "lane", "note", None}
    pure_flow = present <= set(hs.FLOW_KINDS)
    kinds = [k for k in hs.KINDS if k in present and not (pure_flow and k in hs.FLOW_KINDS)]
    tbd = any(nodes[n].get("status") == "tbd" for n in on_page)
    page_edges = [e for e in spec.get("edges", []) if e.get("from") in on_page]
    tbde = any(e.get("status") == "tbd" for e in page_edges)
    etypes = []
    for e in page_edges:
        k = e.get("type", "sync")
        if k in hs.EDGES and k not in etypes and e.get("status") != "tbd":
            etypes.append(k)
    etypes.sort(key=list(hs.EDGES).index)
    need = len([k for k in kinds if k not in hs.FLOW_KINDS]) >= 3 or tbd or tbde or any(k != "sync" for k in etypes)
    if etypes == ["sync"] and not kinds:
        etypes = []
    items = ([("v", k) for k in kinds] + ([("tbd", "tbd")] if tbd else []) +
             [("e", k) for k in etypes] + ([("tbde", "tbde")] if tbde else []))
    return need, items, on_page


def cmd_legend(a) -> int:
    """Insert / refresh one legend per page that needs it, by text surgery (the rest of the file stays byte-identical).
    A page needs a legend when it uses >=3 node kinds, has undecided items, or uses non-default line types."""
    from collections import Counter
    t = Target(a.slug).must_exist()
    normalize_in_place(t)
    spec = load_spec(t) or {"nodes": {}, "edges": []}
    text = t.drawio.read_text(encoding="utf-8")
    tree, _ = dm.load(t.drawio)
    models = dm.pages(tree)
    matches = list(re.finditer(r"<diagram\b.*?</diagram>", text, re.S))
    if not matches:
        die("文件里没有页面")
    out, last, report = [], 0, []
    for i, m in enumerate(matches):
        name, model = models[i] if i < len(models) else (f"Page-{i + 1}", None)
        page = _LEGEND_CELL.sub("", m.group(0))
        need, items, on_page = _page_legend_items(spec, name, i == 0)
        if need and items and model is not None:
            cs = dm.cells(model)
            boxes = [c.abs for c in cs.values() if c.kind == "vertex" and c.abs and not c.id.startswith("legend")
                     and not dm.is_edge_label(c, cs)]
            minx = min(b[0] for b in boxes) if boxes else 40
            maxy = max(b[1] + b[3] for b in boxes) if boxes else 40
            if any(c.kind == "vertex" and c.smap.get("shape") == "umlActor" for c in cs.values()):
                maxy += 24  # actor labels hang below the shape
            votes = {}
            for nid in on_page:
                n, c = spec["nodes"][nid], cs.get(nid)
                if c is not None and n.get("status") != "tbd" and n.get("kind") in hs.KINDS:
                    votes.setdefault(n["kind"], Counter())[c.style] += 1
            for e in spec.get("edges", []):
                if e.get("from") not in on_page or e.get("status") == "tbd":
                    continue
                for c in cs.values():
                    if c.kind == "edge" and (c.source, c.target) == (e.get("from"), e.get("to")):
                        routing = re.sub(r"(exit|entry)(X|Y|Dx|Dy|Perimeter)=[^;]*;?", "", c.style)
                        votes.setdefault(("edge", e.get("type", "sync")), Counter())[routing] += 1
                        break
            actual = {k: cnt.most_common(1)[0][0] for k, cnt in votes.items()}
            pfx = "legend" if i == 0 else f"legend-p{i + 1}"
            pos = page.rfind("</root>")
            page = page[:pos] + _legend_xml(items, minx, maxy, actual, pfx) + "\n" + page[pos:]
            report.append(f"第 {i + 1} 页 {len(items)} 项（{'、'.join(_legend_name(typ, k) for typ, k in items)}）")
        out.append(text[last:m.start()] + page)
        last = m.end()
    out.append(text[last:])
    dm.write_text(t.drawio, "".join(out))
    if report:
        print("✓ 图例已更新：" + "；".join(report))
    else:
        print("ℹ 无需图例（每页 kind < 3、无待定项、只有默认连线；流程图通用符号不进图例）")
    return 0


ADOPTED_GROUP_STYLE = ("rounded=0;whiteSpace=wrap;html=1;fillColor=none;strokeColor=#90a4ae;fontColor=#455a64;"
                       "verticalAlign=top;align=left;spacingLeft=8;fontStyle=1;dashed=1;fontFamily=Arial;fontSize=13;")


def _fixed_route(style: str) -> str:
    """House edge style without draw.io auto-routing, for edges whose waypoints were computed by Graphviz."""
    for k in ("edgeStyle=orthogonalEdgeStyle;", "orthogonalLoop=1;", "jettySize=auto;"):
        style = style.replace(k, "")
    return style


def cmd_adopt(a) -> int:
    """Bring a generated .drawio (e.g. autolayout.py output) into house conventions and make it this diagram."""
    t = Target(a.slug).must_exist()
    src = Path(a.file)
    if not src.exists():
        die(f"找不到文件：{src}")
    spec = load_spec(t) or {"nodes": {}, "edges": []}
    nodes = spec.get("nodes", {}) or {}
    _, cur = all_cells(t.drawio)
    if any(c.kind == "vertex" and c.id != "title" for c in cur.values()):
        cmd_snapshot(argparse.Namespace(slug=a.slug, message="adopt 前自动快照", force=False))
    tree, _ = dm.load(src)
    pages = dm.pages(tree)
    if not pages:
        die("生成的文件里没有页面")
    model = pages[0][1]
    raw = list(dm._iter_raw_cells(model))
    cs = dm.cells(model)
    parents = {c.parent for c in cs.values() if c.kind == "vertex"}
    group_specs = {dm.norm_text(n.get("label", "")): nid for nid, n in nodes.items() if n.get("kind") in ("group", "lane")}
    rename = {}
    for c in cs.values():
        if c.kind == "vertex" and c.id in parents and c.id not in nodes and c.id not in ("0", "1"):
            rename[c.id] = group_specs.get(dm.norm_text(c.label)) or f"_grp-{len(rename) + 1}"
    edge_types = {(e.get("from"), e.get("to")): e for e in spec.get("edges", [])}
    tops = [c.abs for c in cs.values() if c.kind == "vertex" and c.parent == "1" and c.abs]
    dx = 40 - min(b[0] for b in tops) if tops else 0
    dy = 70 - min(b[1] for b in tops) if tops else 0
    out_cells = []
    for holder, mc, label in raw:
        cid = holder.get("id") or mc.get("id")
        if cid in ("0", "1"):
            continue
        if cid in rename:
            holder.set("id", rename[cid])
        for attr in ("parent", "source", "target"):
            if mc.get(attr) in rename:
                mc.set(attr, rename[mc.get(attr)])
        new_id = holder.get("id")
        g = mc.find("mxGeometry")
        if mc.get("vertex") == "1":
            if new_id in nodes and nodes[new_id].get("kind") in hs.KINDS:
                n = nodes[new_id]
                style = hs.KINDS[n["kind"]][1] + (hs.TBD_SUFFIX if n.get("status") == "tbd" else "")
                if n["kind"] in ("group", "lane"):
                    style = ADOPTED_GROUP_STYLE
                mc.set("style", style)
            elif new_id.startswith("_grp-") or new_id in rename.values():
                mc.set("style", ADOPTED_GROUP_STYLE)
            if mc.get("parent") == "1" and g is not None:
                g.set("x", f"{float(g.get('x', 0)) + dx:g}")
                g.set("y", f"{float(g.get('y', 0)) + dy:g}")
        elif mc.get("edge") == "1":
            e = edge_types.get((mc.get("source"), mc.get("target"))) or edge_types.get((mc.get("target"), mc.get("source")))
            typ = (e or {}).get("type", "sync")
            style = _fixed_route(hs.EDGES.get(typ, hs.EDGES["sync"])[1])
            if e and e.get("status") == "tbd":
                style += hs.TBD_EDGE_SUFFIX
            mc.set("style", style)
            if e and e.get("label") and not (holder.get("value") or holder.get("label")):
                holder.set("value" if holder is mc else "label", e["label"])
            if mc.get("parent") == "1" and g is not None:
                for pt in g.iter("mxPoint"):
                    pt.set("x", f"{float(pt.get('x', 0)) + dx:g}")
                    pt.set("y", f"{float(pt.get('y', 0)) + dy:g}")
        out_cells.append(dm.ET.tostring(holder, encoding="unicode"))
    text = t.drawio.read_text(encoding="utf-8")
    title = re.search(r'<mxCell id="title".*?</mxCell>', text, re.S)
    body = "\n        ".join(([title.group(0)] if title else []) + out_cells)
    page = re.search(r"<diagram\b.*?</diagram>", text, re.S)
    root_start = page.group(0).index("<root>") + len("<root>")
    root_end = page.group(0).rindex("</root>")
    new_page = (page.group(0)[:root_start] + '\n        <mxCell id="0" />\n        <mxCell id="1" parent="0" />\n        '
                + body + "\n      " + page.group(0)[root_end:])
    dm.write_text(t.drawio, text[:page.start()] + new_page + text[page.end():])
    print(f"✓ 已采纳 {src.name}：{sum(1 for c in cs.values() if c.kind == 'vertex')} 个节点、"
          f"{sum(1 for c in cs.values() if c.kind == 'edge')} 条连线；容器重命名 {rename}")
    print("  已套用规范样式、保留自动布局的走线；下一步：diagram.py round " + t.slug)
    _remind_if_open(t)
    return 0


def cmd_mermaid(a) -> int:
    t = Target(a.slug).must_exist()
    normalize_in_place(t)
    out = t.out(".mmd")
    ds = drawio_skill_dir()
    proc = subprocess.run([sys.executable, str(HERE / "to_feishu_mermaid.py"), str(t.drawio), "-o", str(out),
                           *(["--drawio-skill", str(ds)] if ds else [])],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    print((proc.stdout + proc.stderr).strip())
    if proc.returncode == 0:
        print("ℹ Mermaid 是降级格式：会丢颜色、飞书画板会重新排版。优先把 .drawio 导入飞书画板。")
    return proc.returncode


def cmd_sync(a) -> int:
    """draw.io -> native Feishu whiteboard (one board per page, appended to the receiving doc on first sync)."""
    import feishu_sync as fs
    import to_feishu_board as tfb
    t = Target(a.slug).must_exist()
    normalize_in_place(t)
    if not fs.lark_cmd():
        print("✗ 未安装 lark-cli，无法自动同步。手动交付：飞书文档里插入画板 → 右上角 → 导入 → 选择")
        print(f"    {t.drawio}")
        print("  安装与授权见 references/feishu-sync.md")
        return 2
    cfg_path, root_cfg_path = t.dir / "feishu.json", diagrams_root() / "_feishu.json"
    cfg, root_cfg = fs.load_json(cfg_path), fs.load_json(root_cfg_path)
    cfg.setdefault("pages", {})
    fdir = t.dir / "feishu"
    fdir.mkdir(exist_ok=True)
    n = page_count(t.drawio)
    pages = [a.page] if a.page else list(range(1, n + 1))
    doc = a.doc or cfg.get("doc") or root_cfg.get("default_doc")
    rc = 0
    for p in pages:
        base = t.out("", p).name
        svg = t.out(".drawio.svg", p)
        with phase("导出"):
            if not svg.exists() or svg.stat().st_mtime < t.drawio.stat().st_mtime:
                svg = fdir / f"{base}.src.svg"
                if not export_svg(t.drawio, svg, p):
                    print(f"✗ 第 {p} 页 SVG 导出失败，无法取得连线几何")
                    return 1
        with phase("转换"):
            api, dsl, ids, notes = tfb.convert(t.drawio, svg, p)
            payload = fdir / f"{base}.openapi.json"
            for path, obj in ((payload, api), (fdir / f"{base}.map.json", ids)):
                dm.write_text(path, json.dumps(obj, ensure_ascii=False, indent=1))
        tag = f"第 {p} 页" if n > 1 else "画板"
        print(f"✓ {tag}：{sum(1 for x in api['nodes'] if x['type'] != 'connector')} 个图形、"
              f"{sum(1 for x in api['nodes'] if x['type'] == 'connector')} 条连线")
        for x in notes:
            print("  ⚠ " + x)
        if a.dry_run:  # nothing is sent; optional rough local render through whiteboard-cli
            dsl_path = fdir / f"{base}.dsl.json"
            dm.write_text(dsl_path, json.dumps(dsl, ensure_ascii=False, indent=1))
            png = fdir / f"{base}.dsl.png"
            if fs.wb_render(dsl_path, png):
                print(f"🖼 本地近似预览（不经飞书；以同步后的飞书预览为准）：{png}")
            continue
        payload_sha = hashlib.sha1(payload.read_bytes()).hexdigest()[:12]
        board = cfg["pages"].get(str(p))
        try:
            if not board or a.new_board:
                if not doc:
                    print("✗ 首次同步需要接收文档：diagram.py sync <slug> --doc <飞书文档链接>")
                    return 2
                with phase("飞书"):
                    board = fs.create_board(doc, fdir)
                cfg["doc"] = doc
                cfg["pages"][str(p)] = board
                fs.save_json(cfg_path, cfg)  # recorded before writing: a retry never creates a second board
                if not root_cfg.get("default_doc"):
                    root_cfg["default_doc"] = doc
                    fs.save_json(root_cfg_path, root_cfg)
                print(f"  ＋ 在文档末尾新建了画板（{board['whiteboard']}）")
            token = board["whiteboard"]
            png = fdir / f"{base}.feishu.jpg"  # Feishu previews are JPEG
            same_payload = board.get("payload_sha") == payload_sha
            with phase("飞书"):
                if board.get("fingerprint") and same_payload:  # likely nothing to do: read state, then preview
                    before, ok = fs.export_both(token, png, parallel=False)  # first call of the run: token may refresh
                else:
                    before, ok = (fs.fingerprint(fs.export_raw(token, fdir)) if board.get("fingerprint") else None), None
            if before and before != board["fingerprint"] and not a.force:
                print(f"✗ {tag}在上次同步后被人在飞书里改过（内容指纹不一致），本次没有覆盖。")
                print("  先和用户确认：覆盖飞书里的改动（加 --force），或写到一块新画板（加 --new-board）。")
                if ok:
                    print(f"🖼 飞书里现在的样子：{png}")
                rc = 3
                continue
            if before and before == board["fingerprint"] and same_payload:
                print(f"  = {tag}已是最新，未重复写入")
            else:
                idem = "ad-" + hashlib.sha1(f"{a.slug}|{p}|{payload_sha}|{before}".encode()).hexdigest()[:20]
                with phase("飞书"):
                    fs.write_board(token, payload, idem)
                    board["fingerprint"], ok = fs.export_both(token, png)
                board.update(payload_sha=payload_sha, synced_at=_dt.datetime.now().isoformat(timespec="seconds"),
                             rev=(t.snapshots()[-1][0] if t.snapshots() else None))
                fs.save_json(cfg_path, cfg)
                print(f"  ✓ 已写入飞书画板（覆盖本工具建的这块画板）")
            if ok:
                print(f"🖼 飞书预览（{tag}）：{png} ← 必须打开看一眼")
        except fs.LarkError as e:
            print(f"✗ 飞书操作失败：{e}")
            return 10 if e.rc == 10 else 1
    if not a.dry_run and doc:
        print(f"✓ 飞书文档：{fs.doc_url(cfg.get('doc') or doc)}")
    print(phase_summary())
    return rc


def cmd_doctor(a) -> int:
    """Show resolved locations and settings (config.schema.json slots); exit 3 if a required tool is missing."""
    sys.path.insert(0, str(HERE))
    import feishu_sync as fs  # noqa: E402
    ds, exe, lark = drawio_skill_dir(), drawio_exe(), fs.lark_cmd()
    root = diagrams_root()
    default_doc = None
    try:
        default_doc = json.loads((root / "_feishu.json").read_text(encoding="utf-8")).get("default_doc")
    except Exception:
        pass
    rows = [
        ("arch-diagram", f"{VERSION}  {SKILL_DIR}"),
        ("python", f"{sys.version.split()[0]}  {sys.executable}"),
        ("drawio-skill（必需）", str(ds) if ds else "✗ 未找到；查找顺序：" + " → ".join(str(c) for c in drawio_skill_candidates())),
        ("draw.io CLI（必需）", exe or "✗ 未找到；装 draw.io 桌面版，或设 DRAWIO_CLI"),
        ("图档根目录", f"{root}{'' if root.exists() else '（首次 new 时创建）'}" + ("  ← ARCH_DIAGRAMS_ROOT" if os.environ.get("ARCH_DIAGRAMS_ROOT") else "")),
        ("lark-cli（可选，飞书同步）", " ".join(lark) if lark else "未安装：画图 / 迭代 / 导出不受影响，只是不能 sync"),
        ("默认飞书文档", "已设置（_feishu.json）" if default_doc else "未设置：首次 sync 时用 --doc 指定"),
    ]
    for k, v in rows:
        print(f"{k}：{v}")
    return 0 if (ds and exe) else 3


def cmd_list(a) -> int:
    root = diagrams_root()
    if not root.exists():
        print(f"（还没有图）{root}")
        return 0
    rows = []
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        f = d / f"{d.name}.drawio"
        if f.exists():
            t = Target(str(f))
            snaps = t.snapshots()
            last = f"r{snaps[-1][0]:02d}" if snaps else "—"
            mt = _dt.datetime.fromtimestamp(f.stat().st_mtime).strftime("%m-%d %H:%M")
            rows.append(f"  {d.name:<28} {last:<5} {mt}")
    print(f"{root}\n" + ("\n".join(rows) if rows else "  （还没有图）"))
    return 0


def cmd_perf(a) -> int:
    log = diagrams_root() / "_perf.jsonl"
    if a.mark:
        perf_log({"ts": _dt.datetime.now().isoformat(timespec="milliseconds"), "cmd": "mark",
                  "label": a.mark, "dur": 0, "v": VERSION})
        print(f"✓ 已打点：{a.mark}")
        return 0
    if not log.exists():
        print("（还没有计时记录）")
        return 0
    rows = []
    for line in log.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    rows = rows[-a.last:]
    print("时间      命令      图 / 标记               耗时   距上条命令结束（≈ Claude 思考、写作和工具往返）")
    prev_end = None
    for r in rows:
        start = _dt.datetime.fromisoformat(r["ts"])
        gap = "" if prev_end is None else f"{(start - prev_end).total_seconds():8.1f}s"
        label = str(r.get("slug") or r.get("label") or "")
        print(f"{start:%H:%M:%S}  {r['cmd']:<8} {label[:22]:<22} {r.get('dur', 0):6.1f}s {gap}")
        prev_end = start + _dt.timedelta(seconds=r.get("dur", 0))
    import statistics
    by: dict[str, list[float]] = {}
    for r in rows:
        if r["cmd"] != "mark":
            by.setdefault(r["cmd"], []).append(r.get("dur", 0))
    if by:
        print("中位耗时：" + "；".join(f"{k} {statistics.median(v):.1f}s（{len(v)} 次）" for k, v in by.items()))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="diagram.py", description="arch-diagram CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("new"); s.add_argument("slug"); s.add_argument("--title"); s.add_argument("--page")
    s = sub.add_parser("inspect"); s.add_argument("slug")
    s = sub.add_parser("check"); s.add_argument("slug"); s.add_argument("--no-preview", action="store_true")
    s = sub.add_parser("export"); s.add_argument("slug"); s.add_argument("--pdf", action="store_true")
    s.add_argument("--highlight", action="store_true"); s.add_argument("--against")
    s = sub.add_parser("snapshot"); s.add_argument("slug"); s.add_argument("-m", "--message", default="")
    s.add_argument("--force", action="store_true")
    s = sub.add_parser("round"); s.add_argument("slug"); s.add_argument("-m", "--message", default="")
    s = sub.add_parser("diff"); s.add_argument("slug"); s.add_argument("--from", dest="frm"); s.add_argument("--to")
    s = sub.add_parser("restore"); s.add_argument("slug"); s.add_argument("ref")
    s = sub.add_parser("legend"); s.add_argument("slug")
    s = sub.add_parser("mermaid"); s.add_argument("slug")
    s = sub.add_parser("adopt"); s.add_argument("slug"); s.add_argument("file")
    s = sub.add_parser("sync"); s.add_argument("slug"); s.add_argument("--doc"); s.add_argument("--page", type=int)
    s.add_argument("--dry-run", action="store_true"); s.add_argument("--new-board", action="store_true")
    s.add_argument("--force", action="store_true")
    sub.add_parser("list")
    sub.add_parser("doctor")
    s = sub.add_parser("perf"); s.add_argument("--last", type=int, default=30); s.add_argument("--mark")
    a = ap.parse_args(argv)
    fn = {"new": cmd_new, "inspect": cmd_inspect, "check": cmd_check, "export": cmd_export,
          "snapshot": cmd_snapshot, "round": cmd_round, "diff": cmd_diff, "restore": cmd_restore,
          "legend": cmd_legend, "mermaid": cmd_mermaid, "adopt": cmd_adopt, "sync": cmd_sync, "list": cmd_list,
          "perf": cmd_perf, "doctor": cmd_doctor}[a.cmd]
    started, t0, rc = _dt.datetime.now(), time.perf_counter(), 1
    try:
        rc = fn(a) or 0
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else 1
        raise
    finally:
        if a.cmd != "perf":
            perf_log({"ts": started.isoformat(timespec="milliseconds"), "cmd": a.cmd, "slug": getattr(a, "slug", None),
                      "dur": round(time.perf_counter() - t0, 3), "rc": rc,
                      "phases": {k: round(v, 3) for k, v in _PHASES.items()}, "v": VERSION})
    return rc


if __name__ == "__main__":
    sys.exit(main())
