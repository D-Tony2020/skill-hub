"""Regenerate the style tables in references/style-guide.md from scripts/house_style.py.

  py -3 tests/regen_style_tables.py
Tables live between <!-- kinds:start -->/<!-- kinds:end --> and <!-- edges:start -->/<!-- edges:end -->.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import house_style as hs  # noqa: E402


def tables():
    k = ["| kind | 代号 | 用途 | 默认尺寸 | 展开后的 style |", "| --- | --- | --- | --- | --- |"]
    k += [f"| `{key}` | `@{key}` | {name} | {w}×{h} | `{style}` |" for key, (name, style, (w, h)) in hs.KINDS.items()]
    e = ["| type | 代号 | 用途 | 展开后的 style |", "| --- | --- | --- | --- |"]
    e += [f"| `{key}` | `@{key}` | {name} | `{style}` |" for key, (name, style) in hs.EDGES.items()]
    return "\n".join(k), "\n".join(e)


def main():
    doc_path = ROOT / "references" / "style-guide.md"
    doc = doc_path.read_text(encoding="utf-8")
    kt, et = tables()
    for tag, body in (("kinds", kt), ("edges", et)):
        doc = re.sub(rf"<!-- {tag}:start -->.*?<!-- {tag}:end -->",
                     f"<!-- {tag}:start -->\n{body}\n<!-- {tag}:end -->", doc, flags=re.S)
    doc = re.sub(r"`dashed=1;dashPattern=8 4;fillColor=#fffde7[^`]*`", f"`{hs.TBD_SUFFIX}`", doc)
    doc_path.write_text(doc, encoding="utf-8")
    print("style-guide.md tables regenerated")


if __name__ == "__main__":
    main()
