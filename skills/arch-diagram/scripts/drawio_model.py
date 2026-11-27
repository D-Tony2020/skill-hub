"""Read / normalize / diff .drawio files (stdlib only).

Handles what drawio-skill's validate.py / drawio2mermaid.py do not:
  * compressed <diagram> payloads (base64 + raw deflate + URL-encoding) as saved by draw.io
  * <object>/<UserObject> wrappers (cells with custom properties or links)
  * multi-page files, nested containers (absolute coordinates)
"""
from __future__ import annotations

import base64
import copy
import html
import re
import urllib.parse
import zlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

import house_style as hs

WRAPPERS = ("object", "UserObject")


# ---------------------------------------------------------------- load / save
def decompress_payload(text: str) -> str:
    raw = base64.b64decode(text.strip())
    try:
        xml = zlib.decompress(raw, -15).decode("utf-8")
    except zlib.error:
        xml = zlib.decompress(raw).decode("utf-8")
    return urllib.parse.unquote(xml)


def load(path) -> tuple[ET.ElementTree, bool]:
    """Parse a .drawio; inflate compressed pages in memory. Returns (tree, was_compressed)."""
    tree = ET.parse(str(path))
    root = tree.getroot()
    if root.tag == "mxGraphModel":  # bare model file -> wrap
        mxfile = ET.Element("mxfile", {"host": "arch-diagram"})
        d = ET.SubElement(mxfile, "diagram", {"id": "page-1", "name": "Page-1"})
        d.append(root)
        tree = ET.ElementTree(mxfile)
        root = mxfile
    compressed = False
    for d in root.iter("diagram"):
        if d.find("mxGraphModel") is None and (d.text or "").strip():
            model = ET.fromstring(decompress_payload(d.text))
            d.text = None
            d.append(model)
            compressed = True
    for el in root.iter():  # style macros read as the full house style everywhere
        s = el.get("style")
        if s and s.startswith("@"):
            el.set("style", expand_style(s))
    return tree, compressed


def expand_style(style: str) -> str:
    """'@agent;fontStyle=1;' -> house agent style + 'fontStyle=1;'. Unknown names come back unchanged."""
    if not style.startswith("@"):
        return style
    name, _, rest = style[1:].partition(";")
    full = hs.MACROS.get(name)
    return style if full is None else full + rest


def expand_macros_text(text: str) -> tuple[str, int]:
    """Expand style macros in raw XML text, touching nothing else (byte-identical to hand-copied styles)."""
    count = 0

    def sub(mt):
        nonlocal count
        new = expand_style(mt.group(1))
        count += new != mt.group(1)
        return f'style="{new}"'

    return re.sub(r'style="(@[^"]*)"', sub, text), count


def write_text(path, text: str) -> None:
    """UTF-8 with LF on every OS: draw.io and editors write LF, while Windows text mode would turn
    every newline into CRLF and break multi-line find/replace edits on the file."""
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def save(tree: ET.ElementTree, path) -> None:
    root = tree.getroot()
    root.attrib.pop("compressed", None)
    ET.indent(tree, space="  ")
    data = ET.tostring(root, encoding="unicode")
    write_text(path, '<?xml version="1.0" encoding="UTF-8"?>\n' + data + "\n")


def canonical(path) -> str:
    """Formatting-insensitive serialization: equal strings <=> same diagram content."""
    tree, _ = load(path)
    root = copy.deepcopy(tree.getroot())
    for el in root.iter():
        el.text = (el.text or "").strip() or None
        el.tail = None
        if el.tag == "mxfile":
            for k in ("modified", "agent", "etag", "version", "host", "compressed"):
                el.attrib.pop(k, None)
    return ET.tostring(root, encoding="unicode")


# ---------------------------------------------------------------- cells
def plain(label: str | None) -> str:
    """HTML label -> plain text (one line per <br>/block)."""
    s = label or ""
    s = re.sub(r"<br\s*/?>|</div>|</p>|</li>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in s.split("\n")]
    return "\n".join(ln for ln in lines if ln)


def norm_text(label: str | None) -> str:
    """Normalize an HTML label from a .drawio for comparison."""
    return re.sub(r"\s+", "", plain(label)).lower()


def norm_plain(text: str | None) -> str:
    """Normalize a plain-text label (spec.json): no HTML parsing, so '<服务>' stays literal."""
    return re.sub(r"\s+", "", text or "").lower()


KNOWN_TAGS = {"b", "i", "u", "br", "div", "span", "font", "p", "ul", "ol", "li", "sup", "sub", "strike", "s", "a",
              "hr", "table", "tr", "td", "th", "tbody", "thead", "img", "h1", "h2", "h3", "h4", "h5", "h6", "pre",
              "code", "em", "strong", "blockquote", "small", "big", "center"}


def swallowed_tags(label: str | None) -> list[str]:
    """Text in an html=1 label the renderer treats as an unknown tag and hides.
    Verified by rendering: literal '<api>' disappears; '<服务>' and 'a < b' survive (HTML tag names start with A-Z/a-z)."""
    out = []
    for m in re.finditer(r"<\s*/?\s*([A-Za-z][^\s>/]*)[^>]*>", label or ""):
        if m.group(1).lower() not in KNOWN_TAGS:
            out.append(m.group(0))
    return out


def style_map(style: str | None) -> dict:
    out = {}
    for part in (style or "").split(";"):
        if not part:
            continue
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
        else:
            out[part.strip()] = ""
    return out


@dataclass
class Cell:
    id: str
    kind: str  # vertex | edge | other
    label: str
    style: str
    parent: str | None
    source: str | None = None
    target: str | None = None
    geo: tuple | None = None  # relative x, y, w, h
    abs: tuple | None = None  # absolute x, y, w, h
    points: list = field(default_factory=list)
    page: str = ""
    label_pos: str = ""

    @property
    def text(self) -> str:
        return plain(self.label)

    @property
    def smap(self) -> dict:
        return style_map(self.style)

    @property
    def bidirectional(self) -> bool:
        sa = self.smap.get("startArrow")
        return self.kind == "edge" and sa not in (None, "", "none")


def _iter_raw_cells(model: ET.Element):
    root = model.find("root")
    if root is None:
        return
    for el in root:
        if el.tag == "mxCell":
            yield el, el, el.get("value", "")
        elif el.tag in WRAPPERS:
            mc = el.find("mxCell")
            if mc is not None:
                yield el, mc, el.get("label", el.get("value", ""))


def pages(tree: ET.ElementTree) -> list[tuple[str, ET.Element]]:
    out = []
    for i, d in enumerate(tree.getroot().iter("diagram")):
        m = d.find("mxGraphModel")
        if m is not None:
            out.append((d.get("name") or f"Page-{i + 1}", m))
    return out


def cells(model: ET.Element, page: str = "") -> dict[str, Cell]:
    found: dict[str, Cell] = {}
    for holder, mc, label in _iter_raw_cells(model):
        cid = holder.get("id") or mc.get("id")
        if cid is None:
            continue
        kind = "vertex" if mc.get("vertex") == "1" else "edge" if mc.get("edge") == "1" else "other"
        g = mc.find("mxGeometry")
        geo, pts = None, []
        if g is not None:
            if kind == "vertex":
                geo = tuple(float(g.get(k, 0) or 0) for k in ("x", "y", "width", "height"))
            arr = g.find("Array")
            if arr is not None:
                pts = [(float(p.get("x", 0)), float(p.get("y", 0))) for p in arr.findall("mxPoint")]
        lp = "" if g is None or kind != "edge" else f'{g.get("x", "")},{g.get("y", "")}'
        found[cid] = Cell(cid, kind, label or "", mc.get("style", ""), mc.get("parent"),
                          mc.get("source"), mc.get("target"), geo, None, pts, page, lp)
    # absolute coordinates through container parents
    for c in found.values():
        if c.kind != "vertex" or c.geo is None:
            continue
        x, y, w, h = c.geo
        p = found.get(c.parent or "")
        guard = 0
        while p is not None and p.kind == "vertex" and p.geo is not None and guard < 50:
            x += p.geo[0]
            y += p.geo[1]
            p = found.get(p.parent or "")
            guard += 1
        c.abs = (x, y, w, h)
    return found


def is_edge_label(c: Cell, all_cells: dict[str, Cell]) -> bool:
    par = all_cells.get(c.parent or "")
    return c.kind == "vertex" and par is not None and par.kind == "edge"


def is_text_cell(c: Cell) -> bool:
    sm = c.smap
    return "text" in sm and sm.get("shape") is None


# ---------------------------------------------------------------- diff
@dataclass
class Diff:
    added_v: list = field(default_factory=list)
    removed_v: list = field(default_factory=list)
    relabeled_v: list = field(default_factory=list)
    moved_v: list = field(default_factory=list)
    restyled_v: list = field(default_factory=list)
    resized_v: list = field(default_factory=list)
    added_e: list = field(default_factory=list)
    removed_e: list = field(default_factory=list)
    changed_e: list = field(default_factory=list)
    rerouted_e: list = field(default_factory=list)
    pages_added: list = field(default_factory=list)
    pages_removed: list = field(default_factory=list)

    def empty(self) -> bool:
        return not any(getattr(self, f) for f in self.__dataclass_fields__)

    def changed_ids(self) -> set:
        ids = set()
        for f in ("added_v", "relabeled_v", "moved_v", "restyled_v", "resized_v", "added_e", "changed_e", "rerouted_e"):
            for item in getattr(self, f):
                ids.add(item[0] if isinstance(item, tuple) else item)
        return ids


_ROUTE_KEYS = ("exitX", "exitY", "entryX", "entryY", "exitDx", "exitDy", "entryDx", "entryDy",
               "exitPerimeter", "entryPerimeter", "edgeStyle")


def _skip(cid: str) -> bool:
    return cid.startswith("legend")  # regenerated automatically; never part of a design change


def _short(c: Cell) -> str:
    t = c.text.split("\n")[0] if c.text else ""
    return (t[:24] + "…") if len(t) > 25 else (t or c.id)


def _relabel(old: str, new: str) -> tuple[str, str]:
    """Readable before/after: when the first line is unchanged, show the lines that did change."""
    ol, nl = old.split("\n"), new.split("\n")
    if ol[0] == nl[0] and len(ol) + len(nl) > 2:
        return f"{ol[0]}「{' / '.join(ol[1:]) or '—'}」", f"「{' / '.join(nl[1:]) or '—'}」"
    return ol[0], nl[0]


def diff_files(old_path, new_path) -> tuple[Diff, dict]:
    told, _ = load(old_path)
    tnew, _ = load(new_path)
    po, pn = dict(pages(told)), dict(pages(tnew))
    d = Diff()
    d.pages_added = [p for p in pn if p not in po]
    d.pages_removed = [p for p in po if p not in pn]
    names = {}
    for page in [p for p in pn if p in po]:
        co, cn = cells(po[page], page), cells(pn[page], page)
        for cid, c in cn.items():
            names[cid] = _short(c)
            if _skip(cid):
                continue
            o = co.get(cid)
            if c.kind == "vertex":
                if is_edge_label(c, cn):
                    continue
                if o is None:
                    d.added_v.append((cid, _short(c)))
                    continue
                if norm_text(o.label) != norm_text(c.label):
                    d.relabeled_v.append((cid, _relabel(o.text, c.text)[0], _relabel(o.text, c.text)[1]))
                if o.abs and c.abs and (abs(o.abs[0] - c.abs[0]) >= 1 or abs(o.abs[1] - c.abs[1]) >= 1):
                    d.moved_v.append((cid, _short(c)))
                if o.abs and c.abs and (abs(o.abs[2] - c.abs[2]) >= 1 or abs(o.abs[3] - c.abs[3]) >= 1):
                    d.resized_v.append((cid, _short(c)))
                if o.smap != c.smap:
                    d.restyled_v.append((cid, _short(c)))
            elif c.kind == "edge":
                if o is None:
                    d.added_e.append((cid, c.source, c.target, c.text))
                    continue
                if (o.source, o.target) != (c.source, c.target) or norm_text(o.label) != norm_text(c.label) \
                        or o.bidirectional != c.bidirectional:
                    d.changed_e.append((cid, c.source, c.target, c.text))
                    continue
                so, sn = o.smap, c.smap
                if o.points != c.points or o.label_pos != c.label_pos or \
                        any(so.get(k) != sn.get(k) for k in _ROUTE_KEYS):
                    d.rerouted_e.append((cid, c.source, c.target, c.text))
                elif so != sn:
                    d.rerouted_e.append((cid, c.source, c.target, c.text))
        for cid, o in co.items():
            names.setdefault(cid, _short(o))
            if cid in cn or _skip(cid):
                continue
            if o.kind == "vertex" and not is_edge_label(o, co):
                d.removed_v.append((cid, _short(o)))
            elif o.kind == "edge":
                d.removed_e.append((cid, o.source, o.target, o.text))
    return d, names


def format_diff(d: Diff, names: dict) -> str:
    if d.empty():
        return "无变化"
    n = lambda i: names.get(i, i)  # noqa: E731
    out = []
    if d.pages_added:
        out.append("新增页面：" + "、".join(d.pages_added))
    if d.pages_removed:
        out.append("删除页面：" + "、".join(d.pages_removed))
    if d.added_v:
        out.append("新增节点：" + "、".join(t for _, t in d.added_v))
    if d.removed_v:
        out.append("删除节点：" + "、".join(t for _, t in d.removed_v))
    if d.relabeled_v:
        out.append("改名：" + "、".join(f"{a} → {b}" for _, a, b in d.relabeled_v))
    if d.restyled_v:
        out.append("样式变化：" + "、".join(t for _, t in d.restyled_v))
    if d.moved_v:
        out.append("位置移动：" + "、".join(t for _, t in d.moved_v))
    if d.resized_v:
        out.append("尺寸变化：" + "、".join(t for _, t in d.resized_v))
    fmt_e = lambda e: f"{n(e[1])} → {n(e[2])}" + (f"（{e[3]}）" if e[3] else "")  # noqa: E731
    if d.added_e:
        out.append("新增关系：" + "；".join(fmt_e(e) for e in d.added_e))
    if d.removed_e:
        out.append("删除关系：" + "；".join(fmt_e(e) for e in d.removed_e))
    if d.changed_e:
        out.append("修改关系：" + "；".join(fmt_e(e) for e in d.changed_e))
    if d.rerouted_e:
        out.append("连线走向/样式调整：" + "；".join(fmt_e(e) for e in d.rerouted_e))
    return "\n".join(out)
