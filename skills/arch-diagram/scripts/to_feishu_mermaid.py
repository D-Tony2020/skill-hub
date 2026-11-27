#!/usr/bin/env python3
"""Convert one page of a .drawio into Feishu-whiteboard-ready Mermaid (fallback path).

Wraps drawio-skill's drawio2mermaid.py and fixes what it loses (found in testing):
  1. title / legend / note cells would become fake nodes  -> stripped before conversion
  2. bidirectional edges (startArrow set) become one-way   -> rewritten as "<-->"
  3. compressed .drawio is not readable by drawio2mermaid  -> inflated first
  4. multi-page files produce several charts               -> one page only (--page, default 1)
  5. dashed (async / undecided) edges become solid          -> rewritten as dotted "-.->"

Usage:
  py -3 to_feishu_mermaid.py diagram.drawio [-o diagram.mmd] [--page 1] [--direction LR] [--drawio-skill DIR]
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import drawio_model as dm  # noqa: E402
import house_style as hs  # noqa: E402


def find_skill_dir(explicit):
    here = Path(__file__).resolve().parent
    cands = [explicit, os.environ.get("DRAWIO_SKILL_DIR"), here.parent.parent / "drawio-skill",
             Path.cwd() / ".claude/skills/drawio-skill",
             Path.home() / ".claude/skills/drawio-skill", Path.home() / ".agents/skills/drawio-skill"]
    for c in cands:
        if c and (Path(c) / "scripts/drawio2mermaid.py").exists():
            return Path(c)
    sys.exit("drawio-skill not found; pass --drawio-skill <dir>")


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("-o", "--output")
    ap.add_argument("--page", type=int, default=1)
    ap.add_argument("--direction")
    ap.add_argument("--drawio-skill")
    a = ap.parse_args()
    skill = find_skill_dir(a.drawio_skill)

    tree, _ = dm.load(a.file)
    diagrams = list(tree.getroot().iter("diagram"))
    if not 1 <= a.page <= len(diagrams):
        sys.exit(f"page {a.page} out of range (file has {len(diagrams)})")
    keep = diagrams[a.page - 1]
    for d in diagrams:
        if d is not keep:
            tree.getroot().remove(d)
    model = keep.find("mxGraphModel")
    root = model.find("root")
    all_c = dm.cells(model)
    drop = {c.id for c in all_c.values()
            if c.id.startswith(hs.RESERVED_PREFIXES) or (c.kind == "vertex" and dm.is_text_cell(c))}
    changed = True  # children of dropped containers (e.g. legend items) go too
    while changed:
        changed = False
        for c in all_c.values():
            if c.id not in drop and c.parent in drop:
                drop.add(c.id)
                changed = True
    for el in list(root):
        cid = el.get("id")
        mc = el if el.tag == "mxCell" else el.find("mxCell")
        if cid in drop or (mc is not None and (mc.get("source") in drop or mc.get("target") in drop)):
            root.remove(el)
    def ekey(c):
        return dm.norm_text(all_c[c.source].label), dm.norm_text(all_c[c.target].label), dm.norm_text(c.label)

    real = [c for c in all_c.values() if c.kind == "edge" and c.source in all_c and c.target in all_c]
    bidir = {ekey(c) for c in real if c.bidirectional}
    dashed = {ekey(c) for c in real if c.smap.get("dashed") == "1"}

    with tempfile.TemporaryDirectory() as td:
        src, raw = Path(td) / "page.drawio", Path(td) / "raw.mmd"
        dm.save(tree, src)
        cmd = [sys.executable, str(skill / "scripts/drawio2mermaid.py"), str(src), "-o", str(raw)]
        if a.direction:
            cmd += ["--direction", a.direction]
        subprocess.run(cmd, check=True, capture_output=True)
        mmd = raw.read_text(encoding="utf-8")

    node_re = re.compile(r'^\s*(\w+)\s*[\[\(\{]+"?(.*?)"?[\]\)\}]+\s*$')
    edge_re = re.compile(r'^(\s*)(\w+)\s*-->\s*(?:\|"?(.*?)"?\|)?\s*(\w+)\s*$')
    labels, out, n_bi, n_dot = {}, [], 0, 0
    for line in mmd.splitlines():
        m = node_re.match(line)
        if m:
            labels[m.group(1)] = dm.norm_text(m.group(2))
    for line in mmd.splitlines():
        m = edge_re.match(line)
        if m:
            ind, s, lab, t = m.groups()
            key = (labels.get(s), labels.get(t), dm.norm_text(lab))
            two, dot = key in bidir, key in dashed
            if two or dot:
                n_bi += two
                n_dot += dot
                arrow = ("<-.->" if two else "-.->") if dot else "<-->"
                line = f'{ind}{s} {arrow}|"{lab}"| {t}' if lab else f"{ind}{s} {arrow} {t}"
        out.append(line)
    result = "\n".join(out).rstrip() + "\n"
    if a.output:
        dm.write_text(a.output, result)
        print(f"wrote {a.output}: page {a.page}, stripped {len(drop)} non-diagram cell(s), "
              f"{n_bi} bidirectional + {n_dot} dotted edge(s) fixed")
    else:
        sys.stdout.write(result)


if __name__ == "__main__":
    main()
