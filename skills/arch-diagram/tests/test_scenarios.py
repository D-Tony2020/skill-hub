"""Scenario regression suite: replays the acceptance scenarios (tests/scenarios.md) on saved artifacts.

  py -3 -m unittest tests.test_scenarios -v        (from the skill root)

Runs without draw.io (structure, spec consistency, diff, history, legend, Mermaid). When a draw.io CLI is
available (or DRAWIO_CLI points at one), RoundTrip also exercises preview + export + snapshot.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures"
sys.path.insert(0, str(ROOT / "scripts"))
import drawio_model as dm  # noqa: E402
import diagram  # noqa: E402
import house_style as hs  # noqa: E402


def to_macros(text):
    """What Claude writes under perf #8: house style strings replaced by @macros, its own keys kept after them."""
    table = sorted(hs.MACROS.items(), key=lambda kv: -len(kv[1]))

    def sub(m):
        st = m.group(1)
        for name, full in table:
            if st.startswith(full):
                rest = st[len(full):]
                return f'style="@{name}' + (";" + rest if rest else "") + '"'
        return m.group(0)
    return re.sub(r'style="([^"]*)"', sub, text)


class Base(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="arch 回归 "))
        shutil.copytree(FIX, self.root, dirs_exist_ok=True)
        os.environ["ARCH_DIAGRAMS_ROOT"] = str(self.root)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def cli(self, *args):
        p = subprocess.run([sys.executable, str(ROOT / "scripts" / "diagram.py"), *args], capture_output=True,
                           text=True, encoding="utf-8", env={**os.environ})
        return p.returncode, p.stdout + p.stderr

    def spec_result(self, slug, drawio=None, spec=None):
        d = self.root / slug
        f = drawio or d / f"{slug}.drawio"
        s = json.loads((spec or d / f"{slug}.spec.json").read_text(encoding="utf-8"))
        names, cs = diagram.all_cells(f)
        return diagram.spec_check(s, cs, names)


class Scenarios(Base):
    SLUGS = ["kitting-agent", "platform-layers", "expedite-flow", "mes-services", "测试 图"]

    def test_R13_R14_every_final_diagram_passes_check(self):
        for slug in self.SLUGS:
            with self.subTest(slug=slug):
                rc, out = self.cli("check", slug, "--no-preview")
                self.assertEqual(rc, 0, out)
                self.assertIn("清单一致性：0 error, 0 warning", out)

    def test_macro_shorthand_expands_byte_identical_for_every_fixture(self):  # perf #8 zero-regression
        files = sorted(self.root.glob("*/*.drawio")) + sorted(self.root.glob("*/history/*.r*.drawio"))
        self.assertGreater(len(files), 8)
        saved = 0
        for f in files:
            with self.subTest(f=f.name):
                text = f.read_text(encoding="utf-8")
                short = to_macros(text)
                back, _ = dm.expand_macros_text(short)
                self.assertEqual(back, text)
                saved += len(text) - len(short)
        self.assertGreater(saved, 0)

    def test_R13_every_snapshot_matches_its_own_spec(self):
        for f in sorted(self.root.glob("*/history/*.r*.drawio")):
            with self.subTest(snapshot=f.name):
                e, w = self.spec_result(f.parent.parent.name, f, f.with_name(f.name.replace(".drawio", ".spec.json")))
                self.assertEqual(e, [], f.name)

    def test_S1_S2_layout_stability(self):
        h = self.root / "kitting-agent" / "history"
        d, _ = dm.diff_files(h / "kitting-agent.r01.drawio", h / "kitting-agent.r03.drawio")
        self.assertEqual(d.moved_v, [], "S2 moved unchanged nodes")
        self.assertEqual({x[0] for x in d.added_v}, {"expedite", "supplier", "srm"})
        self.assertEqual({(x[1], x[2]) for x in d.removed_e}, {("kitting", "erp")})

    def test_S3_user_edits_preserved(self):
        h = self.root / "kitting-agent" / "history"
        d, _ = dm.diff_files(h / "kitting-agent.r03.drawio", h / "kitting-agent.r05.drawio")
        self.assertEqual({x[0] for x in d.moved_v}, {"wms", "supplier"})       # user's drags kept
        self.assertIn("srm", {x[0] for x in d.restyled_v})                      # user's red SRM kept
        self.assertIn("Kq3zY7pLm2Xc-1", {x[0] for x in d.added_v})              # user's note kept
        self.assertIn("approval", {x[0] for x in d.added_v})                    # the requested change

    def test_S3_compressed_user_file_is_readable(self):
        tree, compressed = dm.load(self.root / "kitting-agent" / "user-session-compressed.drawio")
        self.assertTrue(compressed)
        ids = set(dm.cells(dm.pages(tree)[0][1]))
        self.assertTrue({"kitting", "srm", "Kq3zY7pLm2Xc-1"} <= ids)

    def test_S4_S7_groups_and_tbd(self):
        e, w = self.spec_result("platform-layers")
        self.assertEqual((e, w), ([], []))
        names, cs = diagram.all_cells(self.root / "platform-layers" / "platform-layers.drawio")
        self.assertEqual(cs["kitting"].parent, "app")
        self.assertIn("dashed=1", cs["sched"].style)
        self.assertTrue(cs["sched"].text.startswith("【待定】"))

    def test_S5_swimlane_branches_labeled(self):
        spec = json.loads((self.root / "expedite-flow" / "expedite-flow.spec.json").read_text(encoding="utf-8"))
        decisions = [k for k, n in spec["nodes"].items() if n["kind"] == "decision"]
        for dnode in decisions:
            labels = sorted(e["label"] for e in spec["edges"] if e["from"] == dnode)
            self.assertEqual(labels, ["否", "是"], dnode)

    def test_S6_adopted_autolayout_conforms(self):
        e, w = self.spec_result("mes-services")
        self.assertEqual((e, w), ([], []))
        names, cs = diagram.all_cells(self.root / "mes-services" / "mes-services.drawio")
        self.assertFalse([c for c in cs.values() if c.id.startswith("group_")], "autolayout ids leaked")
        self.assertEqual(len([c for c in cs.values() if c.kind == "edge" and not c.id.startswith("legend")]), 30)

    def test_S7_S9_per_page_legends(self):
        spec = json.loads((self.root / "platform-layers" / "platform-layers.spec.json").read_text(encoding="utf-8"))
        n1, items1, _ = diagram._page_legend_items(spec, "总览", True)
        n2, items2, _ = diagram._page_legend_items(spec, "齐套 Agent 内部", False)
        self.assertIn(("tbd", "tbd"), items1)
        self.assertNotIn(("e", "feedback"), items1)    # page-2-only line type stays on page 2
        self.assertIn(("e", "feedback"), items2)

    def test_S8_restore_roundtrip_is_lossless(self):
        f = self.root / "kitting-agent" / "kitting-agent.drawio"
        before = dm.canonical(f)
        self.assertEqual(self.cli("restore", "kitting-agent", "r01")[0], 0)
        self.assertNotEqual(dm.canonical(f), before)
        snaps = sorted(int(re.search(r"\.r(\d+)\.", p.name).group(1))
                       for p in (self.root / "kitting-agent" / "history").glob("*.r*.drawio"))
        rc, out = self.cli("restore", "kitting-agent", f"r{snaps[-1]:02d}")
        self.assertEqual(rc, 0, out)
        self.assertEqual(dm.canonical(f), before)

    def test_S10_mermaid_fallback(self):
        rc, out = self.cli("mermaid", "kitting-agent")
        self.assertEqual(rc, 0, out)
        mmd = (self.root / "kitting-agent" / "kitting-agent.mmd").read_text(encoding="utf-8")
        self.assertEqual(mmd.count("<-->"), 2)          # two read/write relations
        self.assertEqual(mmd.count("-.->"), 1)          # one async message
        self.assertNotIn("图例", mmd)
        self.assertNotIn("Excel", mmd)                  # user's free-text note is not a node
        with mock.patch.dict(os.environ, {"AD_LARK_CLI": "none"}):  # no lark-cli: manual delivery steps
            rc, out = self.cli("sync", "kitting-agent")
        self.assertEqual(rc, 2)
        self.assertIn("导入", out)

    def test_S11_cjk_space_path_and_escaping(self):
        rc, out = self.cli("check", "测试 图", "--no-preview")
        self.assertEqual(rc, 0, out)
        self.assertNotIn("吞掉", out)
        self.assertNotIn("溢出", out)


def _has_drawio():
    return bool(diagram.drawio_exe())


@unittest.skipUnless(_has_drawio(), "draw.io CLI not available")
class RoundTrip(Base):
    def test_round_exports_and_snapshots(self):
        rc, out = self.cli("round", "expedite-flow", "-m", "回归")
        self.assertEqual(rc, 0, out)
        d = self.root / "expedite-flow"
        for name in ("expedite-flow.png", "expedite-flow.drawio.svg", "expedite-flow.preview.png"):
            self.assertTrue((d / name).exists(), name)

    def _fresh(self, src_slug, new_slug):
        """A just-authored diagram: final content of a fixture, no legend, no history."""
        src, d = self.root / src_slug, self.root / new_slug
        d.mkdir()
        text = (src / f"{src_slug}.drawio").read_text(encoding="utf-8")
        (d / f"{new_slug}.drawio").write_text(diagram._LEGEND_CELL.sub("", text), encoding="utf-8")
        shutil.copy2(src / f"{src_slug}.spec.json", d / f"{new_slug}.spec.json")
        return d

    def test_round_preview_is_the_delivered_png(self):  # perf #1
        rc, out = self.cli("round", "expedite-flow", "-m", "x")
        self.assertEqual(rc, 0, out)
        d = self.root / "expedite-flow"
        self.assertEqual((d / "expedite-flow.preview.png").read_bytes(), (d / "expedite-flow.png").read_bytes())
        self.assertIn("必须打开看一眼", out)
        self.assertIn("⏱", out)

    def test_first_round_decides_legend_and_respects_deletion(self):  # perf #3
        d = self._fresh("kitting-agent", "kit-new")
        rc, out = self.cli("round", str(d), "-m", "初版")
        self.assertEqual(rc, 0, out)
        f = d / "kit-new.drawio"
        self.assertIn('id="legend"', f.read_text(encoding="utf-8"))
        f.write_text(diagram._LEGEND_CELL.sub("", f.read_text(encoding="utf-8")), encoding="utf-8")
        rc, out = self.cli("round", str(d), "-m", "用户删了图例")
        self.assertEqual(rc, 0, out)
        self.assertNotIn('id="legend"', f.read_text(encoding="utf-8"))

    def test_v1_flow_and_v2_flow_produce_identical_files(self):  # perf #3 equivalence
        a, b = self._fresh("kitting-agent", "flow-v1"), self._fresh("kitting-agent", "flow-v2")
        self.assertEqual(self.cli("legend", str(a))[0], 0)  # v1: explicit legend, then round
        self.assertEqual(self.cli("round", str(a), "-m", "初版")[0], 0)
        self.assertEqual(self.cli("round", str(b), "-m", "初版")[0], 0)  # v2: round alone
        self.assertEqual((a / "flow-v1.drawio").read_bytes(), (b / "flow-v2.drawio").read_bytes())
        self.assertEqual((a / "flow-v1.png").read_bytes(), (b / "flow-v2.png").read_bytes())

    def test_round_with_macros_equals_round_with_full_styles(self):  # perf #8 end-to-end
        a, b = self._fresh("kitting-agent", "full"), self._fresh("kitting-agent", "short")
        fb = b / "short.drawio"
        fb.write_text(to_macros(fb.read_text(encoding="utf-8")), encoding="utf-8")
        self.assertEqual(self.cli("round", str(a), "-m", "初版")[0], 0)
        rc, out = self.cli("round", str(b), "-m", "初版")
        self.assertEqual(rc, 0, out)
        self.assertEqual((a / "full.drawio").read_bytes(), fb.read_bytes())
        self.assertEqual((a / "full.png").read_bytes(), (b / "short.png").read_bytes())
        self.assertEqual((a / "full.drawio.svg").read_bytes(), (b / "short.drawio.svg").read_bytes())

    def test_failed_check_still_gives_a_preview_but_no_export_or_snapshot(self):
        d = self._fresh("kitting-agent", "kit-bad")
        spec = json.loads((d / "kit-bad.spec.json").read_text(encoding="utf-8"))
        spec["nodes"]["ghost"] = {"label": "不存在的节点", "kind": "service"}
        (d / "kit-bad.spec.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
        rc, out = self.cli("round", str(d), "-m", "x")
        self.assertEqual(rc, 1, out)
        self.assertTrue((d / "kit-bad.preview.png").exists(), out)
        self.assertFalse((d / "kit-bad.png").exists())
        self.assertFalse(list(d.glob("history/*.r*.drawio")))

    def test_parallel_export_is_byte_identical_to_sequential(self):  # perf #2
        d = self.root / "platform-layers"
        outs = {}
        for mode in ("1", "4"):
            os.environ["AD_EXPORT_PARALLEL"] = mode
            try:
                rc, out = self.cli("export", str(d))
            finally:
                os.environ.pop("AD_EXPORT_PARALLEL", None)
            self.assertEqual(rc, 0, out)
            outs[mode] = {f.name: f.read_bytes() for f in d.glob("*.png")} | {f.name: f.read_bytes() for f in d.glob("*.svg")}
        self.assertEqual(sorted(outs["1"]), sorted(outs["4"]))
        for name in outs["1"]:
            self.assertEqual(outs["1"][name], outs["4"][name], name)

    def test_multi_page_export(self):
        rc, out = self.cli("export", "platform-layers")
        self.assertEqual(rc, 0, out)
        self.assertTrue((self.root / "platform-layers" / "platform-layers.p2.png").exists())


if __name__ == "__main__":
    unittest.main()
