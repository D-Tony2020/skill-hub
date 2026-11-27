"""Feishu bridge tests: draw.io -> whiteboard nodes conversion, text fit, and the sync flow (fake lark-cli).

  py -3 -m unittest tests.test_feishu -v

Fixtures are two real diagrams with the SVG draw.io desktop exported for them (base64 label fallbacks stripped).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
FIX = ROOT / "tests" / "fixtures" / "feishu"
sys.path.insert(0, str(SCRIPTS))
import to_feishu_board as tfb  # noqa: E402
import feishu_sync as fs  # noqa: E402

AU, FL = "agent-unit-architecture", "four-layer-ownership"


def conv(slug, svg=True):
    return tfb.convert(FIX / f"{slug}.drawio", FIX / f"{slug}.drawio.svg" if svg else None)


def by_type(api, typ):
    return [n for n in api["nodes"] if n["type"] == typ]


def conn_of(api, ids, cid):
    fid = ids[cid]
    return next(n for n in api["nodes"] if n["id"] == fid)


class PathParsing(unittest.TestCase):
    def test_rounded_corners_collapse_to_corner_points(self):
        pts, curved = tfb.parse_path("M 480 430 L 585 430 Q 595 430 595 420 L 595 316.37")
        self.assertEqual(pts, [(480, 430), (595, 430), (595, 316.37)])
        self.assertFalse(curved)

    def test_collinear_and_duplicate_points_dropped(self):
        pts, _ = tfb.parse_path("M 0 0 L 10 0 L 20 0 L 20 0 L 20 10")
        self.assertEqual(pts, [(0, 0), (20, 0), (20, 10)])

    def test_curve_flagged(self):
        _, curved = tfb.parse_path("M 0 0 C 10 0 20 10 30 10")
        self.assertTrue(curved)


class Conversion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.au = conv(AU)
        cls.fl = conv(FL)

    def test_every_cell_is_carried_over(self):
        api, _, ids, notes = self.au
        self.assertEqual(len(by_type(api, "connector")), 15)
        for cid in ("charter", "playbook", "approver", "legend-datastore", "e-trigger-charter"):
            self.assertIn(cid, ids)
        self.assertEqual([n for n in notes if "未转换" in n], [])

    def test_labels_live_inside_their_shapes(self):
        api, _, ids, _ = self.au
        charter = next(n for n in api["nodes"] if n["id"] == ids["charter"])
        self.assertEqual(charter["type"], "composite_shape")
        self.assertEqual(charter["text"]["text"], "01 任务契约\n谁用、触发、完成定义、自主度")
        first = charter["text"]["rich_text"]["paragraphs"][0]["elements"][0]["text_element"]
        self.assertEqual(first["text_style"].get("font_weight"), "bold")
        # every text object carries the fields the API validates (a missing background code is rejected)
        for n in api["nodes"]:
            texts = [n.get("text")] + [c for c in ((n.get("connector") or {}).get("captions") or {}).get("data", [])]
            for t in filter(None, texts):
                self.assertEqual(t["text_background_color_type"], 0)
                self.assertEqual(t["theme_text_background_color_code"], -1)

    def test_shape_kinds(self):
        api, _, ids, _ = self.au
        kind = {cid: next(n for n in api["nodes"] if n["id"] == fid) for cid, fid in ids.items()}
        self.assertEqual(kind["charter"]["composite_shape"]["type"], "rect")        # rounded=0
        self.assertEqual(kind["playbook"]["composite_shape"]["type"], "round_rect")  # rounded=1
        self.assertEqual(kind["context"]["composite_shape"]["type"], "cylinder")
        self.assertEqual(kind["note-layers"]["composite_shape"]["type"], "note_shape")
        self.assertEqual(kind["approver"]["type"], "svg")          # actor drawn as draw.io's figure
        self.assertEqual(kind["legend-datastore"]["type"], "svg")  # 22px cylinder: native caps would swallow it
        self.assertIn("<ellipse", kind["approver"]["svg"]["svg_code"])

    def test_swimlane_title_is_a_text_box_over_the_header(self):
        api, _, ids, _ = self.au
        body = next(n for n in api["nodes"] if n["id"] == ids["unit"])
        titles = [n for n in by_type(api, "text_shape") if n["text"]["text"] == "Agent 单位（七槽位）"]
        self.assertEqual(len(titles), 1)
        t = titles[0]
        self.assertEqual((t["y"], t["height"]), (body["y"], 28.0))
        self.assertGreater(t["x"], body["x"])  # spacingLeft respected

    def test_declared_ports_are_exact(self):
        api, _, ids, _ = self.au
        c = conn_of(api, ids, "e-playbook-handoff")["connector"]
        self.assertEqual(c["start"]["attached_object"]["position"], {"x": 1.0, "y": 0.25})
        self.assertEqual(c["end"]["attached_object"]["snap_to"], "left")
        back = conn_of(api, ids, "e-handoff-playbook")["connector"]
        self.assertEqual(back["start"]["attached_object"]["position"]["y"], 0.75)

    def test_routes_follow_drawio_bends(self):
        api, _, ids, _ = self.au
        n = conn_of(api, ids, "e-systems-perception")
        c = n["connector"]
        # systems top (0.25) -> up -> left -> up into perception bottom, as draw.io drew it
        self.assertEqual(c["start"]["attached_object"]["position"], {"x": 0.25, "y": 0.0})
        pts = [(n["x"] + p["x"], n["y"] + p["y"]) for p in c["turning_points"]]
        self.assertEqual(pts, [(600.0, 570.0), (430.0, 570.0)])
        self.assertEqual(c["shape"], "polyline")  # orthogonal + rounded

    def test_floating_ends_take_the_side_drawio_used(self):
        api, _, ids, _ = self.au
        c = conn_of(api, ids, "e-perception-playbook")["connector"]
        self.assertEqual(c["end"]["attached_object"]["snap_to"], "bottom")
        self.assertAlmostEqual(c["end"]["attached_object"]["position"]["x"], 0.25, places=3)

    def test_captions_keep_drawio_size_and_color(self):
        api, _, ids, _ = self.au
        cap = conn_of(api, ids, "e-handoff-playbook")["connector"]["captions"]["data"][0]
        self.assertEqual((cap["text"], cap["font_size"], cap["text_color"]), ("批准 / 驳回", 11, "#c62828"))
        rw = conn_of(api, ids, "e-handoff-approver")["connector"]
        self.assertEqual((rw["start"]["arrow_style"], rw["end"]["arrow_style"]), ("triangle_arrow", "triangle_arrow"))

    def test_dashed_edges_and_shapes(self):
        api = self.fl[0]
        dashed = [n for n in api["nodes"] if n.get("style", {}).get("border_style") == "dash"]
        self.assertTrue(any(n["type"] == "connector" for n in dashed))        # async edge
        self.assertTrue(any(n["type"] == "composite_shape" for n in dashed))  # external systems

    def test_without_svg_falls_back_to_declared_geometry(self):
        api, _, ids, notes = conv(AU, svg=False)
        self.assertEqual(len(by_type(api, "connector")), 15)
        self.assertTrue(any("没有 SVG" in x for x in notes))
        c = conn_of(api, ids, "e-playbook-handoff")["connector"]
        self.assertEqual(c["start"]["attached_object"]["position"], {"x": 1.0, "y": 0.25})

    def test_unreadable_svg_degrades_instead_of_crashing(self):
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "x.svg"
            bad.write_text("<svg><g><br></g></svg>", encoding="utf-8")
            api, _, _, notes = tfb.convert(FIX / f"{AU}.drawio", bad)
        self.assertEqual(len(by_type(api, "connector")), 15)
        self.assertTrue(any("SVG 无法使用" in x for x in notes))

    def test_output_is_deterministic(self):
        a = json.dumps(conv(FL)[0], ensure_ascii=False, sort_keys=True)
        b = json.dumps(conv(FL)[0], ensure_ascii=False, sort_keys=True)
        self.assertEqual(a, b)


class TextFit(unittest.TestCase):
    """Calibrated on real Feishu renders of the fixtures: only 场景包 (title + 2 wrapped lines in 240x60) clipped."""

    def test_only_the_clipped_box_is_adjusted(self):
        for slug in (AU, FL):
            _, _, _, notes = conv(slug)
            fit = [x for x in notes if "字号" in x or "裁切" in x]
            self.assertEqual(fit, ["scenario-pack: 文字在飞书里排不下，字号 12→11（想保持原字号：把框加高到约 63）"]
                             if slug == FL else [])

    def test_shrunk_font_is_applied(self):
        api, _, ids, _ = conv(FL)
        pack = next(n for n in api["nodes"] if n["id"] == ids["scenario-pack"])
        self.assertEqual(pack["text"]["font_size"], 11)

    def test_wrap_estimate_matches_feishu(self):
        t = {"font_size": 12, "rich_text": {"paragraphs": [{"elements": [{"text_element": {
            "text": "黑湖连接器（默认）、下沉来的外部适配器", "text_style": {}}}]}]}}
        self.assertEqual(tfb.text_lines_needed(t, 240 - 2 * tfb.INSET), 1)  # Feishu: one line
        t["rich_text"]["paragraphs"][0]["elements"][0]["text_element"]["text"] = "任务契约、编排 SOP、工具选用、审批点、考卷"
        self.assertEqual(tfb.text_lines_needed(t, 240 - 2 * tfb.INSET), 2)  # Feishu: wraps before 点、


class Fingerprint(unittest.TestCase):
    def test_ignores_server_ids_but_sees_edits(self):
        api, _, _, _ = conv(AU)
        a = [dict(n, id=f"x{i}") for i, n in enumerate(api["nodes"])]
        b = [dict(n, id=f"y{i}") for i, n in enumerate(reversed(api["nodes"]))]
        self.assertEqual(fs.fingerprint(a), fs.fingerprint(b))
        b[0] = dict(b[0], x=b[0]["x"] + 30)
        self.assertNotEqual(fs.fingerprint(a), fs.fingerprint(b))


class SyncFlow(unittest.TestCase):
    """diagram.py sync end to end against tests/fake_lark.py (no network)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "diagrams"
        d = self.root / AU
        d.mkdir(parents=True)
        shutil.copy(FIX / f"{AU}.drawio", d / f"{AU}.drawio")
        shutil.copy(FIX / f"{AU}.drawio.svg", d / f"{AU}.drawio.svg")
        st = (d / f"{AU}.drawio").stat()
        os.utime(d / f"{AU}.drawio.svg", (st.st_atime, st.st_mtime + 5))  # SVG is fresh: no draw.io needed
        self.dir = d
        self.state = self.tmp / "lark.json"
        self.env = dict(os.environ, ARCH_DIAGRAMS_ROOT=str(self.root), FAKE_LARK_STATE=str(self.state),
                        AD_LARK_CLI=f"{sys.executable}|{ROOT / 'tests' / 'fake_lark.py'}", PYTHONIOENCODING="utf-8")
        self.env.pop("FAKE_LARK_FAIL", None)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def sync(self, *args, **env):
        e = dict(self.env, **env)
        p = subprocess.run([sys.executable, str(SCRIPTS / "diagram.py"), "sync", AU, *args], env=e,
                           capture_output=True, text=True, encoding="utf-8")
        return p.returncode, p.stdout + p.stderr

    def calls(self):
        d = Path(str(self.state) + ".calls.d")
        return [json.loads(f.read_text(encoding="utf-8")) for f in sorted(d.glob("*.json"))] if d.exists() else []

    def test_first_sync_needs_a_doc(self):
        rc, out = self.sync()
        self.assertEqual(rc, 2, out)
        self.assertIn("--doc", out)
        self.assertEqual(self.calls(), [])

    def test_full_cycle(self):
        rc, out = self.sync("--doc", "https://x.feishu.cn/docx/DOC1")
        self.assertEqual(rc, 0, out)
        self.assertIn("新建了画板", out)
        self.assertIn("必须打开看一眼", out)
        cfg = json.loads((self.dir / "feishu.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["pages"]["1"]["whiteboard"], "wbtok0001")
        self.assertEqual(json.loads((self.root / "_feishu.json").read_text(encoding="utf-8"))["default_doc"],
                         "https://x.feishu.cn/docx/DOC1")
        self.assertTrue((self.dir / "feishu" / f"{AU}.feishu.jpg").exists())
        writes = [c for c in self.calls() if c[:2] == ["whiteboard", "+update"]]
        self.assertEqual(len(writes), 1)
        self.assertIn("--overwrite", writes[0])

        rc, out = self.sync()  # unchanged: nothing written
        self.assertEqual(rc, 0, out)
        self.assertIn("已是最新", out)
        self.assertEqual(len([c for c in self.calls() if c[:2] == ["whiteboard", "+update"]]), 1)

        st = json.loads(self.state.read_text())  # someone edits the board in Feishu
        st["boards"]["wbtok0001"][3]["x"] += 40
        self.state.write_text(json.dumps(st))
        rc, out = self.sync()
        self.assertEqual(rc, 3, out)
        self.assertIn("被人在飞书里改过", out)
        self.assertEqual(len([c for c in self.calls() if c[:2] == ["whiteboard", "+update"]]), 1)

        rc, out = self.sync("--force")
        self.assertEqual(rc, 0, out)
        self.assertEqual(len([c for c in self.calls() if c[:2] == ["whiteboard", "+update"]]), 2)

        rc, out = self.sync("--new-board")  # second board in the same (remembered) doc
        self.assertEqual(rc, 0, out)
        cfg = json.loads((self.dir / "feishu.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["pages"]["1"]["whiteboard"], "wbtok0002")

    def test_new_diagram_uses_the_remembered_doc(self):
        (self.root / "_feishu.json").write_text(json.dumps({"default_doc": "DOCX9"}), encoding="utf-8")
        rc, out = self.sync()
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.calls()[0][:4], ["docs", "+update", "--doc", "DOCX9"])

    def test_dry_run_sends_nothing(self):
        rc, out = self.sync("--dry-run", AD_WHITEBOARD_CLI="false-cli-not-there")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.calls(), [])
        self.assertTrue((self.dir / "feishu" / f"{AU}.openapi.json").exists())

    def test_lark_failure_is_reported(self):
        rc, out = self.sync("--doc", "D", FAKE_LARK_FAIL="whiteboard +update")
        self.assertEqual(rc, 1, out)
        self.assertIn("飞书操作失败", out)
        # the board was recorded before the failing write: a retry reuses it instead of creating another
        cfg = json.loads((self.dir / "feishu.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["pages"]["1"]["whiteboard"], "wbtok0001")
        rc, out = self.sync()
        self.assertEqual(rc, 0, out)
        self.assertEqual(len([c for c in self.calls() if c[:2] == ["docs", "+update"]]), 1)

    def test_stale_svg_is_reexported(self):
        os.utime(self.dir / f"{AU}.drawio.svg", (0, 0))  # older than the .drawio
        rc, out = self.sync("--dry-run", DRAWIO_CLI=str(self.tmp / "no-drawio"))
        self.assertNotEqual(rc, 0)
        self.assertIn("SVG 导出失败", out)


class Runners(unittest.TestCase):
    def test_exit_10_is_never_auto_confirmed(self):
        with tempfile.TemporaryDirectory() as d:
            script = Path(d) / "gate.py"
            script.write_text("import sys,json;sys.stderr.write(json.dumps({'ok':False,'error':{'type':'confirmation',"
                              "'hint':'add --yes'}}));sys.exit(10)", encoding="utf-8")
            old = os.environ.get("AD_LARK_CLI")
            os.environ["AD_LARK_CLI"] = f"{sys.executable}|{script}"
            try:
                with self.assertRaises(fs.LarkError) as cm:
                    fs.lark(["drive", "+delete"], Path(d))
            finally:
                if old is None:
                    os.environ.pop("AD_LARK_CLI", None)
                else:
                    os.environ["AD_LARK_CLI"] = old
        self.assertEqual(cm.exception.rc, 10)
        self.assertIn("征得用户同意", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
