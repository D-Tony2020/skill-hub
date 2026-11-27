"""draw.io page -> Feishu whiteboard nodes (OpenAPI "raw" format for `lark-cli whiteboard +update --input_format raw`).

  py -3 to_feishu_board.py <file.drawio> --svg <file.drawio.svg> -o <out-prefix> [--page N]

writes <prefix>.openapi.json (upload payload), <prefix>.dsl.json (whiteboard-cli DSL, used for its --check text-overflow
gate and a rough local preview) and <prefix>.map.json (draw.io id -> Feishu node id).

Geometry is taken from draw.io itself: vertices from the .drawio model, edge routes and edge-label positions from the
SVG that draw.io exported for the same page (every `round` writes it). So connectors keep draw.io's exact ports and
bends (turning points) instead of being re-routed. Without the SVG, edges fall back to declared ports + waypoints.

Mapping: swimlane container -> body rect + header rect (title inside); rect/rounded rect/ellipse/rhombus/cylinder/
note/actor -> native shapes with the label *inside* the shape (editable in Feishu); text cells -> text; HTML labels ->
rich text (bold/italic/underline, one paragraph per line); edges -> connectors attached to their end shapes.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import drawio_model as dm  # noqa: E402

SVG = "{http://www.w3.org/2000/svg}"
ARROW = {"classic": "triangle_arrow", "classicThin": "triangle_arrow", "block": "triangle_arrow",
         "blockThin": "triangle_arrow", "open": "line_arrow", "openThin": "line_arrow", "async": "line_arrow",
         "openAsync": "line_arrow", "diamond": "diamond_arrow", "diamondThin": "diamond_arrow",
         "oval": "circle_arrow", "circle": "circle_arrow", "none": "none", "": "none"}
EMPTY = {"triangle_arrow": "empty_triangle_arrow", "circle_arrow": "empty_circle_arrow",
         "diamond_arrow": "empty_diamond_arrow"}
DSL_ARROW = {"triangle_arrow": "triangle", "empty_triangle_arrow": "triangle", "line_arrow": "arrow",
             "circle_arrow": "circle", "empty_circle_arrow": "circle", "diamond_arrow": "diamond",
             "empty_diamond_arrow": "diamond", "none": "none"}


# ------------------------------------------------------------------ labels -> rich text
class _Runs(HTMLParser):
    """HTML label -> lines of runs [(bold, italic, underline, text)]."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines: list[list[list]] = [[]]
        self.b = self.i = self.u = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("b", "strong"):
            self.b += 1
        elif tag in ("i", "em"):
            self.i += 1
        elif tag == "u":
            self.u += 1
        elif tag == "br":
            self.lines.append([])
        elif tag in ("div", "p", "li") and self.lines[-1]:
            self.lines.append([])

    def handle_endtag(self, tag):
        if tag in ("b", "strong"):
            self.b = max(0, self.b - 1)
        elif tag in ("i", "em"):
            self.i = max(0, self.i - 1)
        elif tag == "u":
            self.u = max(0, self.u - 1)

    def handle_data(self, data):
        key = (bool(self.b), bool(self.i), bool(self.u))
        line = self.lines[-1]
        if line and tuple(line[-1][:3]) == key:
            line[-1][3] += data
        else:
            line.append([*key, data])


def label_lines(label: str, is_html: bool, bold_all=False, italic_all=False, underline_all=False) -> list[list[dict]]:
    """-> [[{text, bold, italic, underline}, ...] per line]; empty lines and outer whitespace dropped."""
    if is_html:
        p = _Runs()
        p.feed(label or "")
        p.close()
        raw = p.lines
    else:
        raw = [[[False, False, False, ln]] for ln in (label or "").split("\n")]
    out = []
    for line in raw:
        runs = []
        for b, i, u, text in line:
            text = re.sub(r"[ \t\r\n\f\v\xa0]+", " ", text)
            if text:
                runs.append({"text": text, "bold": b or bold_all, "italic": i or italic_all,
                             "underline": u or underline_all})
        if runs:
            runs[0]["text"] = runs[0]["text"].lstrip()
            runs[-1]["text"] = runs[-1]["text"].rstrip()
            runs = [r for r in runs if r["text"]]
        if runs:
            out.append(runs)
    return out


# Feishu text layout, calibrated on real board renders: CJK 1em wide, line height ~1.45em, ~5px inner margin;
# draw.io packs text tighter (1.2em lines), so a label that just fits in draw.io can be clipped in Feishu.
LINE_H, INSET = 1.45, 5.0
_NO_LINE_START = set("、。，．,.：:；;！!？?）)」』】〕〉》”’%")


def _char_w(ch: str, fs: float, bold: bool) -> float:
    o = ord(ch)
    if (0x2E80 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF or 0xFF00 <= o <= 0xFFEF or 0x3000 <= o <= 0x303F
            or 0x2460 <= o <= 0x24FF):
        w = 1.0
    elif ch == " ":
        w = 0.26
    elif ch.isupper() or ch in "MW@%&":
        w = 0.64
    elif ch.isdigit():
        w = 0.56
    elif ch.isalpha():
        w = 0.53
    else:
        w = 0.33
    return w * fs * (1.04 if bold else 1.0)


def text_lines_needed(t: dict, width: float) -> int:
    """Wrapped line count of a Feishu text object in a box `width` wide (inner margins already removed)."""
    fs = t["font_size"]
    n = 0
    for para in t["rich_text"]["paragraphs"]:
        chars = [(ch, bool(el["text_element"]["text_style"].get("font_weight") == "bold"))
                 for el in para["elements"] for ch in el["text_element"]["text"]]
        line_w, lines, i = 0.0, 1, 0
        while i < len(chars):
            # keep a Latin word, or a char plus following no-line-start punctuation, together
            j = i + 1
            if chars[i][0].isascii() and chars[i][0].isalnum():
                while j < len(chars) and chars[j][0].isascii() and chars[j][0].isalnum():
                    j += 1
            while j < len(chars) and chars[j][0] in _NO_LINE_START:
                j += 1
            seg = sum(_char_w(c, fs, b) for c, b in chars[i:j])
            if line_w > 0 and line_w + seg > width:
                lines += 1
                line_w = 0.0
                if chars[i][0] == " ":
                    i += 1
                    continue
            line_w += seg
            i = j
        n += lines
    return n


def fit_font(t: dict, w: float, h: float, min_size: int = 9) -> tuple[int, float]:
    """Largest font size (<= the label's own) at which the label fits the shape in Feishu; plus the box height the
    original size would need."""
    def needed(fs):
        tt = dict(t, font_size=fs)
        return text_lines_needed(tt, max(1.0, w - 2 * INSET)) * fs * LINE_H + 2 * INSET
    orig = t["font_size"]
    need = needed(orig)
    for fs in range(orig, max(min_size, orig - 2) - 1, -1):
        if needed(fs) <= h + 0.5:
            return fs, need
    return orig, need


def _font_flags(sm: dict) -> tuple[bool, bool, bool]:
    fs = int(_num(sm.get("fontStyle"), 0))
    return bool(fs & 1), bool(fs & 2), bool(fs & 4)


def _num(v, default):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _color(v, default):
    return default if v in (None, "", "default", "none") else v


# ------------------------------------------------------------------ SVG geometry
_TOK = re.compile(r"[MLQCZmlqcz]|-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def parse_path(d: str) -> tuple[list[tuple[float, float]], bool]:
    """draw.io edge path -> (polyline vertices, curved). Rounded corners (Q) collapse to their corner point."""
    toks = _TOK.findall(d or "")
    pts: list[tuple[float, float]] = []
    curved = False
    i, cmd, prev = 0, None, None

    def num():
        nonlocal i
        v = float(toks[i])
        i += 1
        return v

    while i < len(toks):
        if toks[i].isalpha():
            cmd = toks[i].upper()
            i += 1
            if cmd == "Z":
                continue
        if cmd == "M":
            pts.append((num(), num()))
            prev = "M"
        elif cmd == "L":
            pts.append((num(), num()))
            prev = "L"
        elif cmd == "Q":
            c = (num(), num())
            num(), num()  # arc end: lies on the next segment
            if prev == "L" and len(pts) > 1:
                pts[-1] = c
            else:
                pts.append(c)
            prev = "Q"
        elif cmd == "C":
            num(), num(), num(), num()
            pts.append((num(), num()))
            curved = True
            prev = "C"
        else:  # unknown token: skip
            i += 1
    return _simplify(pts), curved


def _simplify(pts):
    out = []
    for p in pts:
        if out and abs(p[0] - out[-1][0]) < 0.01 and abs(p[1] - out[-1][1]) < 0.01:
            continue
        out.append(p)
    i = 1
    while i < len(out) - 1:  # drop collinear interior points
        (x0, y0), (x1, y1), (x2, y2) = out[i - 1], out[i], out[i + 1]
        if abs((x1 - x0) * (y2 - y1) - (y1 - y0) * (x2 - x1)) < 0.01:
            out.pop(i)
        else:
            i += 1
    return out


def _own(g):
    """Descendants of a cell group that are not inside a nested cell group."""
    stack = list(g)
    while stack:
        el = stack.pop(0)
        if el.tag == SVG + "g" and el.get("data-cell-id"):
            continue
        yield el
        stack[0:0] = list(el)


def svg_geometry(svg_path, cells: dict) -> dict:
    """{'offset': (dx, dy), 'edges': {id: [points]}, 'curved': {id}, 'labels': {id: (x, y)}} in model coordinates."""
    root = ET.parse(svg_path).getroot()
    groups = {g.get("data-cell-id"): g for g in root.iter(SVG + "g") if g.get("data-cell-id")}
    cands = Counter()
    for cid, g in groups.items():
        c = cells.get(cid)
        if not c or c.kind != "vertex" or not c.abs:
            continue
        for el in _own(g):
            if el.tag == SVG + "rect":
                w, h = _num(el.get("width"), -1), _num(el.get("height"), -1)
                if abs(w - c.abs[2]) < 0.6 and abs(h - c.abs[3]) < 0.6:
                    cands[(round(c.abs[0] - _num(el.get("x"), 0), 1), round(c.abs[1] - _num(el.get("y"), 0), 1))] += 1
                    break
    if not cands:
        raise ValueError("SVG 与 draw.io 文件对不上（找不到可对齐的图形）")
    dx, dy = cands.most_common(1)[0][0]
    edges, curved, labels = {}, set(), {}
    for cid, g in groups.items():
        c = cells.get(cid)
        if not c:
            continue
        own = list(_own(g))
        if c.kind == "edge":
            for el in own:
                if el.tag == SVG + "path" and el.get("fill") == "none" and el.get("stroke") not in (None, "none"):
                    pts, cv = parse_path(el.get("d", ""))
                    if len(pts) >= 2:
                        edges[cid] = [(x + dx, y + dy) for x, y in pts]
                        if cv:
                            curved.add(cid)
                    break
        if c.kind == "edge" or dm.is_edge_label(c, cells):
            pos = _label_center(own)
            if pos:
                key = c.id if c.kind == "edge" else c.parent
                labels.setdefault(key, (pos[0] + dx, pos[1] + dy))
    return {"offset": (dx, dy), "edges": edges, "curved": curved, "labels": labels}


def _label_center(own):
    for el in own:
        if el.tag.endswith("div"):
            st = el.get("style", "")
            m1, m2 = re.search(r"padding-top:\s*([-\d.]+)px", st), re.search(r"margin-left:\s*([-\d.]+)px", st)
            if m1 and m2:
                return float(m2.group(1)), float(m1.group(1))
    for el in own:
        if el.tag == SVG + "image":
            return (_num(el.get("x"), 0) + _num(el.get("width"), 0) / 2,
                    _num(el.get("y"), 0) + _num(el.get("height"), 0) / 2)
    for el in own:
        if el.tag == SVG + "text":
            return _num(el.get("x"), 0), _num(el.get("y"), 0)
    return None


# ------------------------------------------------------------------ geometry helpers
def _side_of(bbox, p, toward):
    """Where a route leaves/enters bbox: (side, fx, fy). `toward` is the next route point away from the shape."""
    x, y, w, h = bbox
    px, py = p
    vx, vy = toward[0] - px, toward[1] - py
    if abs(vx) >= abs(vy) and abs(vx) > 0.01:
        side = "right" if vx > 0 else "left"
    elif abs(vy) > 0.01:
        side = "bottom" if vy > 0 else "top"
    else:
        d = {"left": abs(px - x), "right": abs(px - x - w), "top": abs(py - y), "bottom": abs(py - y - h)}
        side = min(d, key=d.get)
    fx = 0.0 if side == "left" else 1.0 if side == "right" else min(1, max(0, (px - x) / w if w else 0.5))
    fy = 0.0 if side == "top" else 1.0 if side == "bottom" else min(1, max(0, (py - y) / h if h else 0.5))
    return side, round(fx, 4), round(fy, 4)


def _port(sm, kx, ky):
    if sm.get(kx) is None or sm.get(ky) is None:
        return None
    fx, fy = _num(sm.get(kx), 0.5), _num(sm.get(ky), 0.5)
    side = "left" if fx <= 0 else "right" if fx >= 1 else "top" if fy <= 0 else "bottom" if fy >= 1 else "auto"
    return side, fx, fy


def _at(bbox, fx, fy):
    return bbox[0] + bbox[2] * fx, bbox[1] + bbox[3] * fy


def _param_on(route, p):
    """Fraction along the polyline of the point nearest to p."""
    total, best, best_d, acc = 0.0, 0.5, float("inf"), 0.0
    segs = list(zip(route, route[1:]))
    lengths = [math.dist(a, b) for a, b in segs]
    total = sum(lengths) or 1.0
    for (a, b), ln in zip(segs, lengths):
        if ln == 0:
            continue
        t = max(0.0, min(1.0, ((p[0] - a[0]) * (b[0] - a[0]) + (p[1] - a[1]) * (b[1] - a[1])) / (ln * ln)))
        q = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
        d = math.dist(p, q)
        if d < best_d:
            best_d, best = d, (acc + t * ln) / total
        acc += ln
    return round(best, 4)


# ------------------------------------------------------------------ the converter
class Board:
    def __init__(self, cells: dict, geo: dict | None):
        self.cells = cells
        self.geo = geo or {"edges": {}, "curved": set(), "labels": {}}
        self.nodes: list[dict] = []  # OpenAPI
        self.dsl: list[dict] = []  # whiteboard-cli DSL (flat, absolute)
        self.dsl_edges: list[dict] = []
        self.ids: dict[str, str] = {}  # draw.io id -> feishu id
        self.n = Counter()
        self.notes: list[str] = []
        layers = {c.id for c in cells.values() if c.parent == "0" or (c.parent is None and c.id != "0")}
        self.order = [c for c in cells.values() if c.id not in layers and c.id != "0"]

    def _svg_node(self, cid, x, y, w, h, code):
        return {"id": self.nid("p", cid), "type": "svg", "x": x, "y": y, "width": w, "height": h,
                "style": {"border_style": "none", "fill_opacity": 100, "fill_color_type": 0,
                          "theme_fill_color_code": -1},
                "svg": {"svg_code": code}}

    def nid(self, prefix, cid=None):
        self.n[prefix] += 1
        v = f"{prefix}001:{self.n[prefix]}"
        if cid:
            self.ids[cid] = v
        return v

    # -- style objects
    @staticmethod
    def _shape_style(sm, fill_default="#ffffff"):
        stroke = _color(sm.get("strokeColor"), None if sm.get("strokeColor") == "none" else "#000000")
        fill = sm.get("fillColor")
        st = {}
        if stroke is None or _num(sm.get("strokeWidth"), 1) == 0:
            st["border_style"] = "none"
        else:
            st.update(border_opacity=100, border_width=_width(sm.get("strokeWidth")), border_color=stroke,
                      border_color_type=1, border_style="dash" if sm.get("dashed") == "1" else "solid")
        if fill == "none":
            st.update(fill_opacity=0, fill_color="#ffffff", fill_color_type=1)
        else:
            st.update(fill_opacity=int(_num(sm.get("fillOpacity", sm.get("opacity")), 100)),
                      fill_color=_color(fill, fill_default), fill_color_type=1)
        return st

    @staticmethod
    def _text(cell, sm, *, align=None, valign=None, angle=0):
        bold, italic, underline = _font_flags(sm)
        lines = label_lines(cell.label, sm.get("html") == "1", bold, italic, underline)
        if not lines:
            return None
        paragraphs = []
        for runs in lines:
            els = []
            for r in runs:
                ts = {"italic": r["italic"], "underline": r["underline"], "line_through": False}
                if r["bold"]:
                    ts = {"font_weight": "bold", **ts}
                els.append({"element_type": 0, "text_element": {"text_style": ts, "text": r["text"]}})
            paragraphs.append({"paragraph_type": 0, "elements": els, "indent": 0, "list_begin_index": 0,
                               "quote": False})
        va = valign or {"top": "top", "bottom": "bottom"}.get(sm.get("verticalAlign"), "mid")
        ha = align or sm.get("align")
        return {"text": "\n".join("".join(r["text"] for r in runs) for runs in lines),
                "font_weight": "bold" if bold else "regular", "font_size": int(_num(sm.get("fontSize"), 11)),
                "horizontal_align": ha if ha in ("left", "center", "right") else "center",
                "vertical_align": va, "line_through": False, "underline": underline, "italic": italic,
                "angle": angle, "text_color": _color(sm.get("fontColor"), "#000000"), "text_color_type": 1,
                "text_background_color_type": 0, "theme_text_background_color_code": -1,
                "rich_text": {"paragraphs": paragraphs}}

    # -- vertices
    def vertex(self, c):
        sm = c.smap
        x, y, w, h = c.abs
        if "swimlane" in sm:
            return self.swimlane(c, sm, x, y, w, h)
        if dm.is_text_cell(c):
            t = self._text(c, sm)
            if t:
                self.nodes.append({"id": self.nid("a", c.id), "type": "text_shape", "x": x, "y": y, "width": w,
                                   "height": h, "text": t})
                self._dsl_text(c.id, x, y, w, h, t)
            return
        shape = sm.get("shape")
        if shape == "umlActor":  # Feishu's native actor shrinks inside its box; draw draw.io's figure instead
            self.nodes.append(self._svg_node(c.id, x, y, w, h, actor_svg(w, h, sm)))
            self.dsl.append({"type": "svg", "id": c.id, "x": x, "y": y, "width": w, "height": h,
                             "svg": {"code": actor_svg(w, h, sm)}})
            t = self._text(c, sm, align="center", valign="top")
            if t:  # label sits under the figure, as draw.io's verticalLabelPosition=bottom
                lw = max(w, 16 + max(len(ln) for ln in t["text"].split("\n")) * t["font_size"])
                lh = 6 + t["font_size"] * 1.4 * (t["text"].count("\n") + 1)
                self.nodes.append({"id": self.nid("a"), "type": "text_shape", "x": x + w / 2 - lw / 2, "y": y + h + 2,
                                   "width": lw, "height": lh, "text": t})
                self._dsl_text(c.id + "__label", x + w / 2 - lw / 2, y + h + 2, lw, lh, t)
            return
        if shape in ("cylinder3", "cylinder", "datastore") and h < 50:
            code = cylinder_svg(w, h, sm)
            self.nodes.append(self._svg_node(c.id, x, y, w, h, code))
            self.dsl.append({"type": "svg", "id": c.id, "x": x, "y": y, "width": w, "height": h, "svg": {"code": code}})
            t = self._text(c, sm)
            if t:
                self.nodes.append({"id": self.nid("a"), "type": "text_shape", "x": x, "y": y, "width": w, "height": h,
                                   "text": t})
            return
        if shape in ("cylinder3", "cylinder", "datastore"):
            typ = "cylinder"
        elif "rhombus" in sm or shape == "rhombus":
            typ = "diamond"
        elif "ellipse" in sm or shape == "ellipse":
            typ = "ellipse"
        elif shape == "triangle":
            typ = "triangle"
        elif shape == "note":
            typ = "note_shape"
        elif shape in (None, "rect", "rectangle", "label"):
            typ = "round_rect" if sm.get("rounded") == "1" else "rect"
        else:
            typ = "round_rect" if sm.get("rounded") == "1" else "rect"
            self.notes.append(f"{c.id}: draw.io 图形 {shape} 在飞书画成矩形")
        node = {"id": self.nid("o", c.id), "type": "composite_shape", "x": x, "y": y, "width": w, "height": h,
                "style": self._shape_style(sm), "composite_shape": {"type": typ}}
        t = self._text(c, sm)
        if t:
            # usable text area per Feishu shape (diamond/ellipse lose their corners, cylinder its caps)
            aw, ah = {"diamond": (w * 0.6, h * 0.6), "ellipse": (w * 0.75, h * 0.8),
                      "cylinder": (w, h - 16 - 6), "note_shape": (w - 6, h)}.get(typ, (w, h))
            fs, need = fit_font(t, aw, ah)
            if fs != t["font_size"]:
                self.notes.append(f"{c.id}: 文字在飞书里排不下，字号 {t['font_size']}→{fs}"
                                  f"（想保持原字号：把框加高到约 {math.ceil(need + h - ah)}）")
                t["font_size"] = fs
            elif need > ah + 0.5:
                self.notes.append(f"{c.id}: 文字在飞书里会被裁切（框高 {h:g}，约需 {math.ceil(need + h - ah)}）——"
                                  "把框加高或精简文字")
            node["text"] = t
        self.nodes.append(node)
        self._dsl_shape(c.id, typ, x, y, w, h, sm, t)

    def swimlane(self, c, sm, x, y, w, h):
        start = _num(sm.get("startSize"), 23)
        horizontal = sm.get("horizontal", "1") != "0"
        body_sm = dict(sm, fillColor=sm.get("swimlaneFillColor", "#ffffff"), dashed=sm.get("dashed", "0"))
        self.nodes.append({"id": self.nid("o", c.id), "type": "composite_shape", "x": x, "y": y, "width": w,
                           "height": h, "style": self._shape_style(body_sm), "composite_shape": {"type": "rect"}})
        hw, hh = (w, start) if horizontal else (start, h)
        self.nodes.append({"id": self.nid("o"), "type": "composite_shape", "x": x, "y": y, "width": hw, "height": hh,
                           "style": self._shape_style(sm, "#ffffff"), "composite_shape": {"type": "rect"}})
        self._dsl_shape(c.id, "rect", x, y, w, h, body_sm, None)
        self._dsl_shape(c.id + "__header", "rect", x, y, hw, hh, sm, None)
        t = self._text(c, sm, valign="mid", angle=0 if horizontal else 270)
        if t:
            sp = _num(sm.get("spacing"), 2)
            left = sp + (_num(sm.get("spacingLeft"), 0) if t["horizontal_align"] == "left" else 0)
            right = sp + (_num(sm.get("spacingRight"), 0) if t["horizontal_align"] == "right" else 0)
            if horizontal:
                bx, by, bw, bh = x + left, y, max(10.0, w - left - right), start
            else:
                bx, by, bw, bh = x, y + sp, start, max(10.0, h - 2 * sp)
            self.nodes.append({"id": self.nid("a"), "type": "text_shape", "x": bx, "y": by, "width": bw,
                               "height": bh, "text": t})
            self._dsl_text(c.id + "__title", bx, by, bw, bh, t)

    # -- edges
    def edge(self, e):
        sm = e.smap
        src, tgt = self.cells.get(e.source or ""), self.cells.get(e.target or "")
        route = self.geo["edges"].get(e.id)
        ends = {}
        for end, term, kx, ky, idx, nxt in (("start", src, "exitX", "exitY", 0, 1), ("end", tgt, "entryX", "entryY", -1, -2)):
            if term is None or term.kind != "vertex" or not term.abs or term.id not in self.ids:
                if route:
                    ends[end] = {"position": {"x": route[idx][0], "y": route[idx][1]}, "point": route[idx]}
                    continue
                self.notes.append(f"{e.id}: 连线缺少端点图形，未转换")
                return
            port = _port(sm, kx, ky)
            if port is None or port[0] == "auto":
                if route:
                    port = _side_of(term.abs, route[idx], route[nxt])
                elif port is None:  # no SVG: face the other end, middle of that side
                    other = tgt if end == "start" else src
                    toward = _center(other.abs) if other is not None and other.abs else _center(term.abs)
                    port = _side_of(term.abs, _center(term.abs), toward)
            side, fx, fy = port
            ends[end] = {"attached_object": {"id": self.ids[term.id], "snap_to": side, "position": {"x": fx, "y": fy}},
                         "point": _at(term.abs, fx, fy)}
        corners = route[1:-1] if route else self._model_waypoints(e)
        pts = [ends["start"]["point"], *corners, ends["end"]["point"]]
        x0, y0 = min(p[0] for p in pts), min(p[1] for p in pts)
        x1, y1 = max(p[0] for p in pts), max(p[1] for p in pts)
        style = sm.get("edgeStyle")
        if e.id in self.geo["curved"] or sm.get("curved") == "1":
            shape = "curve"
        elif style or corners:
            shape = "polyline" if sm.get("rounded") == "1" else "right_angled_polyline"
        else:
            shape = "straight"
        conn = {"start": {k: v for k, v in ends["start"].items() if k != "point"},
                "end": {k: v for k, v in ends["end"].items() if k != "point"},
                "shape": shape, "caption_auto_direction": False, "specified_coordinate": True}
        conn["start"]["arrow_style"] = self._arrow(sm, "startArrow", "startFill", "none")
        conn["end"]["arrow_style"] = self._arrow(sm, "endArrow", "endFill", "classic")
        if corners and shape != "curve":
            conn["turning_points"] = [{"x": round(px - x0, 2), "y": round(py - y0, 2)} for px, py in corners]
        label = self._edge_label(e)
        if label:
            cap = self._text(label[0], label[0].smap if label[0] is not e else sm, align="center", valign="mid")
            conn["captions"] = {"data": [cap]}
            pos = self.geo["labels"].get(e.id)
            conn["caption_position"] = _param_on(pts, pos) if pos else round((_num(e.label_pos.split(",")[0], 0) + 1) / 2, 4)
        stroke = _color(sm.get("strokeColor"), "#000000")
        node = {"id": self.nid("c", e.id), "type": "connector", "x": round(x0, 2), "y": round(y0, 2),
                "width": round(max(1.0, x1 - x0), 2), "height": round(max(1.0, y1 - y0), 2),
                "style": {"border_opacity": 100, "border_width": _width(sm.get("strokeWidth")), "border_color": stroke,
                          "border_color_type": 1, "border_style": "dash" if sm.get("dashed") == "1" else "solid"},
                "connector": conn}
        self.nodes.append(node)
        d = {"from": e.source if "attached_object" in conn["start"] else {"x": pts[0][0], "y": pts[0][1]},
             "to": e.target if "attached_object" in conn["end"] else {"x": pts[-1][0], "y": pts[-1][1]},
             "lineShape": {"polyline": "polyline", "right_angled_polyline": "rightAngle"}.get(shape, shape),
             "lineColor": stroke, "lineWidth": _num(sm.get("strokeWidth"), 1),
             "startArrow": DSL_ARROW.get(conn["start"]["arrow_style"], "none"),
             "endArrow": DSL_ARROW.get(conn["end"]["arrow_style"], "triangle")}
        for k, key in (("start", "fromAnchor"), ("end", "toAnchor")):
            side = conn[k].get("attached_object", {}).get("snap_to")
            if side in ("top", "right", "bottom", "left"):
                d[key] = side
        if corners:
            d["waypoints"] = [{"x": px, "y": py} for px, py in corners]
        if sm.get("dashed") == "1":
            d["lineStyle"] = "dashed"
        if label:
            d["label"] = conn["captions"]["data"][0]["text"].replace("\n", " ")
            d["labelPosition"] = conn["caption_position"]
        self.dsl_edges.append({"type": "connector", "id": e.id, "connector": d})

    def _edge_label(self, e):
        if e.text:
            return (e,)
        for c in self.order:
            if c.parent == e.id and c.kind == "vertex" and c.text:
                return (c,)
        return None

    def _model_waypoints(self, e):
        par = self.cells.get(e.parent or "")
        ox, oy = (par.abs[0], par.abs[1]) if par is not None and par.kind == "vertex" and par.abs else (0, 0)
        return [(px + ox, py + oy) for px, py in e.points]

    @staticmethod
    def _arrow(sm, key, fill_key, default):
        a = ARROW.get(sm.get(key, default), "triangle_arrow")
        return EMPTY.get(a, a) if sm.get(fill_key) == "0" else a

    # -- DSL mirror (for whiteboard-cli --check / preview)
    def _dsl_text(self, cid, x, y, w, h, t):
        self.dsl.append({"type": "text", "id": cid, "x": x, "y": y, "width": w, "height": h, **_dsl_text_props(t)})

    def _dsl_shape(self, cid, typ, x, y, w, h, sm, t):
        st = self._shape_style(sm)
        n = {"type": {"round_rect": "rect", "note_shape": "rect", "cylinder": "cylinder", "diamond": "diamond",
                      "ellipse": "ellipse", "triangle": "triangle"}.get(typ, "rect"),
             "id": cid, "x": x, "y": y, "width": w, "height": h,
             "fillColor": "transparent" if st.get("fill_opacity") == 0 else st.get("fill_color", "#ffffff"),
             "borderColor": st.get("border_color", "transparent"),
             "borderWidth": 0 if st.get("border_style") == "none" else _num(sm.get("strokeWidth"), 1)}
        if st.get("border_style") == "dash":
            n["borderDash"] = "dashed"
        if typ == "round_rect":
            arc = _num(sm.get("arcSize"), 15)
            n["borderRadius"] = round(arc / 2 if sm.get("absoluteArcSize") == "1" else min(w, h) * arc / 100, 1)
        elif n["type"] == "rect":
            n["borderRadius"] = 0
        if t:
            n.update(_dsl_text_props(t))
        self.dsl.append(n)

    def build(self):
        for c in self.order:
            if c.kind == "vertex" and c.abs and not dm.is_edge_label(c, self.cells):
                self.vertex(c)
        for c in self.order:
            if c.kind == "edge":
                self.edge(c)
        return self


def _dsl_text_props(t):
    runs = []
    for i, p in enumerate(t["rich_text"]["paragraphs"]):
        for j, el in enumerate(p["elements"]):
            te = el["text_element"]
            r = {"content": ("\n" if i and not j else "") + te["text"]}
            if te["text_style"].get("font_weight") == "bold":
                r["bold"] = True
            if te["text_style"].get("italic"):
                r["italic"] = True
            if te["text_style"].get("underline"):
                r["underline"] = True
            runs.append(r)
    return {"text": runs, "fontSize": t["font_size"], "textColor": t["text_color"],
            "textAlign": t["horizontal_align"], "verticalAlign": {"mid": "middle"}.get(t["vertical_align"], t["vertical_align"])}


def _svg_open(w, h):
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{_f(w)}" height="{_f(h)}" viewBox="0 0 {_f(w)} {_f(h)}">'


def _f(v):
    return f"{v:.2f}".rstrip("0").rstrip(".")


def actor_svg(w, h, sm):
    """draw.io's umlActor: head ellipse (w/4, 0, w/2, h/4), body to 2h/3, arms at h/3, legs to the bottom corners."""
    stroke = _color(sm.get("strokeColor"), "#000000")
    fill = _color(sm.get("fillColor"), "#ffffff") if sm.get("fillColor") != "none" else "none"
    sw = max(1.0, _num(sm.get("strokeWidth"), 1))
    i = sw / 2
    return (_svg_open(w, h)
            + f'<ellipse cx="{_f(w / 2)}" cy="{_f(h / 8)}" rx="{_f(max(1, w / 4 - i))}" ry="{_f(max(1, h / 8 - i))}" '
              f'fill="{fill}" stroke="{stroke}" stroke-width="{_f(sw)}"/>'
            + f'<path d="M {_f(w / 2)} {_f(h / 4)} L {_f(w / 2)} {_f(2 * h / 3)} M {_f(i)} {_f(h / 3)} L {_f(w - i)} {_f(h / 3)} '
              f'M {_f(w / 2)} {_f(2 * h / 3)} L {_f(i)} {_f(h - i)} M {_f(w / 2)} {_f(2 * h / 3)} L {_f(w - i)} {_f(h - i)}" '
              f'fill="none" stroke="{stroke}" stroke-width="{_f(sw)}" stroke-linecap="round"/></svg>')


def cylinder_svg(w, h, sm):
    """draw.io's cylinder3 outline (cap radius = style size, at most h/2)."""
    stroke = _color(sm.get("strokeColor"), "#000000")
    fill = _color(sm.get("fillColor"), "#ffffff") if sm.get("fillColor") != "none" else "none"
    sw = max(1.0, _num(sm.get("strokeWidth"), 1))
    i = sw / 2
    W, H = w - 2 * i, h - 2 * i
    d = max(0.0, min(H / 2, _num(sm.get("size"), 15)))
    body = (f"M {_f(i)} {_f(i + d)} C {_f(i)} {_f(i - d / 3)} {_f(i + W)} {_f(i - d / 3)} {_f(i + W)} {_f(i + d)} "
            f"L {_f(i + W)} {_f(i + H - d)} C {_f(i + W)} {_f(i + H + d / 3)} {_f(i)} {_f(i + H + d / 3)} {_f(i)} {_f(i + H - d)} Z")
    front = f"M {_f(i)} {_f(i + d)} C {_f(i)} {_f(i + 2 * d)} {_f(i + W)} {_f(i + 2 * d)} {_f(i + W)} {_f(i + d)}"
    return (_svg_open(w, h) + f'<path d="{body}" fill="{fill}" stroke="{stroke}" stroke-width="{_f(sw)}"/>'
            + f'<path d="{front}" fill="none" stroke="{stroke}" stroke-width="{_f(sw)}"/></svg>')


def _width(v):
    w = _num(v, 1)
    return "extra_narrow" if w <= 1 else "narrow" if w <= 2 else "medium" if w <= 3 else "bold"


def _center(b):
    return b[0] + b[2] / 2, b[1] + b[3] / 2


def convert(drawio, svg=None, page: int = 1) -> tuple[dict, dict, dict, list[str]]:
    tree, _ = dm.load(drawio)
    pages = dm.pages(tree)
    if not 1 <= page <= len(pages):
        raise SystemExit(f"没有第 {page} 页（共 {len(pages)} 页）")
    name, model = pages[page - 1]
    cells = dm.cells(model, name)
    geo, why = None, "没有 SVG"
    if svg:
        try:
            geo = svg_geometry(svg, cells)
        except (ET.ParseError, ValueError, OSError) as e:
            why = f"SVG 无法使用（{str(e)[:80]}）"
    b = Board(cells, geo).build()
    if geo is None:
        b.notes.append(why + "：连线按声明的端口和途经点画，拐点可能与 draw.io 不完全一致")
    return {"nodes": b.nodes}, {"version": 2, "nodes": b.dsl + b.dsl_edges}, b.ids, b.notes


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("drawio")
    ap.add_argument("--svg")
    ap.add_argument("--page", type=int, default=1)
    ap.add_argument("-o", "--out", required=True, help="output prefix")
    a = ap.parse_args(argv)
    api, dsl, ids, notes = convert(a.drawio, a.svg, a.page)
    pre = Path(a.out)
    for suffix, obj in ((".openapi.json", api), (".dsl.json", dsl), (".map.json", ids)):
        dm.write_text(pre.with_name(pre.name + suffix), json.dumps(obj, ensure_ascii=False, indent=1))
    kinds = Counter(n["type"] for n in api["nodes"])
    print(f"wrote {pre.name}.openapi.json: " + ", ".join(f"{k} {v}" for k, v in sorted(kinds.items())))
    for x in notes:
        print("  ⚠ " + x)
    return 0


if __name__ == "__main__":
    sys.exit(main())
