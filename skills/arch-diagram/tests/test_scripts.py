"""Unit + CLI tests for arch-diagram scripts (stdlib unittest; runs on Windows and Linux).

  py -3 -m unittest discover -s tests -v            (from the skill root)

Export-dependent tests are skipped when no draw.io CLI is available.
"""
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import urllib.parse
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import drawio_model as dm  # noqa: E402
import house_style as hs  # noqa: E402
import diagram  # noqa: E402

BASE = """<mxfile><diagram id="p1" name="总览"><mxGraphModel><root>
<mxCell id="0"/><mxCell id="1" parent="0"/>
<mxCell id="title" value="标题" style="{title}" vertex="1" parent="1"><mxGeometry x="40" y="10" width="300" height="30" as="geometry"/></mxCell>
<mxCell id="grp" value="应用层" style="swimlane;startSize=28;" vertex="1" parent="1"><mxGeometry x="100" y="100" width="400" height="200" as="geometry"/></mxCell>
<mxCell id="a" value="&lt;b&gt;Agent A&lt;/b&gt;&lt;br&gt;规划" style="{agent}" vertex="1" parent="grp"><mxGeometry x="20" y="40" width="160" height="60" as="geometry"/></mxCell>
<object id="db" label="记忆 &amp;amp; 知识" link="https://x"><mxCell style="{db}" vertex="1" parent="1"><mxGeometry x="600" y="140" width="120" height="80" as="geometry"/></mxCell></object>
<mxCell id="e1" value="读写" style="{rw}" edge="1" parent="1" source="a" target="db"><mxGeometry relative="1" as="geometry"/></mxCell>
</root></mxGraphModel></diagram></mxfile>"""


def fixture(**over):
    s = BASE.format(title=hs.TITLE_STYLE, agent=hs.KINDS["agent"][1], db=hs.KINDS["datastore"][1],
                    rw=hs.EDGES["readwrite"][1])
    for k, v in over.items():
        s = s.replace(k, v)
    return s


def compress(xml_text: str) -> str:
    model = re.search(r"<mxGraphModel>.*</mxGraphModel>", xml_text, re.S).group(0)
    co = zlib.compressobj(9, zlib.DEFLATED, -15)
    raw = co.compress(urllib.parse.quote(model, safe="").encode()) + co.flush()
    payload = base64.b64encode(raw).decode()
    return re.sub(r"<mxGraphModel>.*</mxGraphModel>", payload, xml_text, flags=re.S)


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


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ad 测试 "))  # space + CJK on purpose
        os.environ["ARCH_DIAGRAMS_ROOT"] = str(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, name, text):
        d = self.tmp / name
        d.mkdir(parents=True, exist_ok=True)
        f = d / f"{name}.drawio"
        f.write_text(text, encoding="utf-8")
        return f

    def cli(self, *args):
        p = subprocess.run([sys.executable, str(SCRIPTS / "diagram.py"), *args], capture_output=True,
                           text=True, encoding="utf-8", env={**os.environ})
        return p.returncode, p.stdout + p.stderr


class ModelTests(Tmp):
    def test_style_macros_expand_exactly(self):  # perf #8
        self.assertEqual(dm.expand_style("@agent"), hs.KINDS["agent"][1])
        self.assertEqual(dm.expand_style("@agent;fontStyle=1;"), hs.KINDS["agent"][1] + "fontStyle=1;")
        self.assertEqual(dm.expand_style("@external+tbd"), hs.KINDS["external"][1] + hs.TBD_SUFFIX)
        self.assertEqual(dm.expand_style("@async+tbd;exitX=1;"), hs.EDGES["async"][1] + hs.TBD_EDGE_SUFFIX + "exitX=1;")
        self.assertEqual(dm.expand_style("@title"), hs.TITLE_STYLE)
        self.assertEqual(dm.expand_style("@agnet"), "@agnet")  # unknown stays visible for check
        self.assertEqual(dm.expand_style("rounded=1;"), "rounded=1;")

    def test_macro_file_reads_as_full_styles(self):  # perf #8: every reader sees house styles
        f = self.write("mx", to_macros(fixture()))
        self.assertIn('style="@', f.read_text(encoding="utf-8"))
        tree, _ = dm.load(f)
        cs = dm.cells(dm.pages(tree)[0][1])
        self.assertTrue(all(not (c.style or "").startswith("@") for c in cs.values()))

    def test_plain_and_object_wrapper(self):
        f = self.write("m1", fixture())
        tree, comp = dm.load(f)
        self.assertFalse(comp)
        cs = dm.cells(dm.pages(tree)[0][1])
        self.assertEqual(cs["a"].text, "Agent A\n规划")
        self.assertEqual(cs["db"].text, "记忆 & 知识")
        self.assertEqual(cs["db"].kind, "vertex")
        self.assertTrue(cs["e1"].bidirectional)

    def test_absolute_coords_through_container(self):
        f = self.write("m2", fixture())
        tree, _ = dm.load(f)
        cs = dm.cells(dm.pages(tree)[0][1])
        self.assertEqual(cs["a"].abs[:2], (120.0, 140.0))

    def test_compressed_roundtrip(self):
        f = self.write("m3", compress(fixture()))
        tree, comp = dm.load(f)
        self.assertTrue(comp)
        self.assertIn("a", dm.cells(dm.pages(tree)[0][1]))
        out = self.tmp / "out.drawio"
        dm.save(tree, out)
        t2, comp2 = dm.load(out)
        self.assertFalse(comp2)
        self.assertEqual(set(dm.cells(dm.pages(t2)[0][1])), set(dm.cells(dm.pages(tree)[0][1])))

    def test_diff_detects_every_change_type(self):
        old = self.write("d_old", fixture())
        new_xml = fixture().replace('x="600" y="140"', 'x="650" y="140"') \
            .replace("&lt;br&gt;规划", "&lt;br&gt;计划") \
            .replace('<mxCell id="e1"', '<mxCell id="n1" value="新" style="rounded=1;" vertex="1" parent="1">'
                     '<mxGeometry x="10" y="400" width="80" height="40" as="geometry"/></mxCell><mxCell id="e1"')
        new_xml = new_xml.replace('source="a" target="db"', 'source="n1" target="db"')
        new = self.write("d_new", new_xml)
        d, names = dm.diff_files(old, new)
        self.assertEqual([x[0] for x in d.added_v], ["n1"])
        self.assertEqual([x[0] for x in d.relabeled_v], ["a"])
        self.assertEqual([x[0] for x in d.moved_v], ["db"])
        self.assertEqual([x[0] for x in d.changed_e], ["e1"])
        self.assertIn("改名", dm.format_diff(d, names))

    def test_reroute_and_resize_are_changes(self):  # regression D10
        old = self.write("rr_old", fixture())
        new = self.write("rr_new", fixture().replace('source="a" target="db">', 'source="a" target="db">').replace(
            'style="' + hs.EDGES["readwrite"][1] + '"', 'style="' + hs.EDGES["readwrite"][1] + 'exitX=1;exitY=0.5;"').replace(
            'width="120" height="80"', 'width="140" height="80"'))
        d, names = dm.diff_files(old, new)
        self.assertEqual([x[0] for x in d.rerouted_e], ["e1"])
        self.assertEqual([x[0] for x in d.resized_v], ["db"])
        self.assertNotEqual(dm.canonical(old), dm.canonical(new))

    def test_waypoint_only_change_triggers_snapshot(self):  # regression D10
        f = self.write("wp", fixture().replace('<mxGeometry relative="1" as="geometry"/></mxCell>\n</root>',
                                                '<mxGeometry relative="1" as="geometry"><Array as="points"><mxPoint x="300" y="300"/></Array></mxGeometry></mxCell>\n</root>'))
        self.cli("snapshot", "wp", "-m", "a")
        f.write_text(f.read_text(encoding="utf-8").replace('x="300" y="300"', 'x="320" y="300"'), encoding="utf-8")
        rc, out = self.cli("snapshot", "wp", "-m", "b")
        self.assertIn("快照 r02", out)
        self.assertIn("连线走向", out)

    def test_no_diff_when_identical(self):
        a = self.write("same", fixture())
        d, _ = dm.diff_files(a, a)
        self.assertTrue(d.empty())


class SpecTests(Tmp):
    def spec(self, **kw):
        s = {"title": "t", "nodes": {"grp": {"label": "应用层", "kind": "group"},
                                     "a": {"label": "Agent A\n规划", "kind": "agent", "group": "grp"},
                                     "db": {"label": "记忆 & 知识", "kind": "datastore"}},
             "edges": [{"from": "a", "to": "db", "label": "读写", "type": "readwrite"}]}
        s.update(kw)
        return s

    def run_spec(self, spec, xml=None):
        f = self.write("s", xml or fixture())
        names, cs = diagram.all_cells(f)
        return diagram.spec_check(spec, cs, names)

    def test_consistent(self):
        e, w = self.run_spec(self.spec())
        self.assertEqual(e, [])
        self.assertEqual(w, [])

    def test_missing_node_and_edge(self):
        s = self.spec()
        s["nodes"]["x"] = {"label": "X", "kind": "service"}
        s["edges"].append({"from": "a", "to": "x"})
        e, _ = self.run_spec(s)
        self.assertTrue(any("缺少节点：x" in m for m in e))
        self.assertTrue(any("缺少关系：a → x" in m for m in e))

    def test_extra_relation_is_error(self):
        s = self.spec(edges=[])
        e, _ = self.run_spec(s)
        self.assertTrue(any("图中多出关系" in m for m in e))

    def test_group_membership(self):
        s = self.spec()
        s["nodes"]["db"]["group"] = "grp"
        e, _ = self.run_spec(s)
        self.assertTrue(any("分组不符：db" in m for m in e))

    def test_tbd_style_required(self):
        s = self.spec()
        s["nodes"]["a"]["status"] = "tbd"
        _, w = self.run_spec(s)
        self.assertTrue(any("待定项 a" in m for m in w))
        xml = fixture().replace("&lt;b&gt;Agent A", "【待定】&lt;b&gt;Agent A").replace(
            hs.KINDS["agent"][1], hs.KINDS["agent"][1] + hs.TBD_SUFFIX)
        _, w2 = self.run_spec(s, xml)
        self.assertFalse(any("待定项 a" in m for m in w2))
        self.assertFalse(any("标签不一致：a" in m for m in w2))

    def test_readwrite_reverse_direction_ok(self):
        s = self.spec(edges=[{"from": "db", "to": "a", "label": "读写", "type": "readwrite"}])
        e, _ = self.run_spec(s)
        self.assertEqual(e, [])

    def test_free_text_note_not_flagged(self):  # regression D12
        xml = fixture().replace('<mxCell id="e1"', '<mxCell id="Kq3-1" value="用户的备注" style="text;html=1;" vertex="1" parent="1">'
                                '<mxGeometry x="0" y="500" width="80" height="40" as="geometry"/></mxCell><mxCell id="e1"')
        e, w = self.run_spec(self.spec(), xml)
        self.assertEqual((e, w), ([], []))

    def test_tbd_edge_style_required(self):  # regression D14
        s = self.spec()
        s["edges"][0]["status"] = "tbd"
        _, w = self.run_spec(s)
        self.assertTrue(any("待定关系" in m for m in w))

    def test_literal_angle_brackets_in_spec(self):  # regression D22
        xml = fixture().replace("记忆 &amp;amp; 知识", "A &amp;amp; B &amp;lt;服务&amp;gt;")
        s = self.spec()
        s["nodes"]["db"]["label"] = "A & B <服务>"
        e, w = self.run_spec(s, xml)
        self.assertEqual((e, w), ([], []))

    def test_swallowed_tag_lint(self):  # regression G5
        self.assertEqual(dm.swallowed_tags("调用 <api> 接口"), ["<api>"])
        self.assertEqual(dm.swallowed_tags("A &amp; B <服务> 与 a < b"), [])
        self.assertEqual(dm.swallowed_tags("<b>ERP</b><br>库存"), [])

    def test_parallel_edges_same_pair(self):  # regression D1
        xml = fixture().replace('</root>', '<mxCell id="e2" value="写入" style="" edge="1" parent="1" source="a" target="db">'
                                '<mxGeometry relative="1" as="geometry"/></mxCell></root>')
        s = self.spec(edges=[{"from": "a", "to": "db", "label": "写入"},
                             {"from": "a", "to": "db", "label": "读写", "type": "readwrite"}])
        e, w = self.run_spec(s, xml)
        self.assertEqual(e, [])
        self.assertEqual(w, [])

    def test_extra_vertex_warning_but_reserved_ignored(self):
        xml = fixture().replace('<mxCell id="e1"', '<mxCell id="note-1" value="备注" style="shape=note;" vertex="1" parent="1">'
                                '<mxGeometry x="0" y="500" width="80" height="40" as="geometry"/></mxCell>'
                                '<mxCell id="zz" value="手加的" style="rounded=1;" vertex="1" parent="1">'
                                '<mxGeometry x="0" y="600" width="80" height="40" as="geometry"/></mxCell><mxCell id="e1"')
        _, w = self.run_spec(self.spec(), xml)
        self.assertTrue(any("清单外元素：zz" in m for m in w))
        self.assertFalse(any("note-1" in m for m in w))


class EnvTests(Tmp):
    def test_drawio_skill_found_next_to_this_skill(self):  # hub install: any scope, sibling folder
        skills = self.tmp / "proj" / ".claude" / "skills"
        (skills / "drawio-skill" / "scripts").mkdir(parents=True)
        (skills / "drawio-skill" / "scripts" / "validate.py").write_text("", encoding="utf-8")
        with mock.patch.dict(os.environ, {"DRAWIO_SKILL_DIR": ""}), \
                mock.patch.object(diagram, "SKILL_DIR", skills / "arch-diagram"), \
                mock.patch.object(diagram.Path, "home", return_value=self.tmp / "nohome"):
            self.assertEqual(diagram.drawio_skill_dir(), skills / "drawio-skill")

    def test_doctor_reports_missing_drawio_skill(self):
        env = {**os.environ, "DRAWIO_SKILL_DIR": str(self.tmp / "none"), "HOME": str(self.tmp),
               "USERPROFILE": str(self.tmp), "DRAWIO_CLI": "drawio"}
        p = subprocess.run([sys.executable, str(SCRIPTS / "diagram.py"), "doctor"], capture_output=True,
                           text=True, encoding="utf-8", env=env, cwd=str(self.tmp))
        out = p.stdout + p.stderr
        if (SCRIPTS.parent.parent / "drawio-skill" / "scripts" / "validate.py").exists():
            self.skipTest("a sibling drawio-skill is installed next to this checkout")
        self.assertEqual(p.returncode, 3, out)
        self.assertIn("drawio-skill", out)
        self.assertIn("未找到", out)
        self.assertIn("默认飞书文档", out)


class CliTests(Tmp):
    def test_new_snapshot_diff_restore(self):
        rc, out = self.cli("new", "flow", "--title", "流程 & <测试>")
        self.assertEqual(rc, 0, out)
        f = self.tmp / "flow" / "flow.drawio"
        self.assertIn("流程 &amp; &lt;测试&gt;", f.read_text(encoding="utf-8"))
        rc, out = self.cli("snapshot", "flow", "-m", "初版")
        self.assertIn("快照 r01", out)
        rc, out = self.cli("snapshot", "flow", "-m", "重复")
        self.assertIn("完全相同", out)
        f.write_text(f.read_text(encoding="utf-8").replace('width="560"', 'width="600"').replace(
            'value="流程 &amp; &lt;测试&gt;"', 'value="新标题"'), encoding="utf-8")
        rc, out = self.cli("snapshot", "flow", "-m", "改标题")
        self.assertIn("快照 r02", out)
        self.assertIn("改名", out)
        rc, out = self.cli("diff", "flow", "--from", "r01", "--to", "r02")
        self.assertIn("新标题", out)
        rc, out = self.cli("restore", "flow", "r01")
        self.assertEqual(rc, 0, out)
        self.assertIn("流程 &amp;", f.read_text(encoding="utf-8"))
        log = (self.tmp / "flow" / "history" / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("r02", log)

    def test_spec_only_change_is_recorded(self):  # regression D16
        self.write("so", fixture())
        sp = self.tmp / "so" / "so.spec.json"
        sp.write_text(json.dumps({"nodes": {"a": {"label": "A", "kind": "agent"}}, "edges": []}), encoding="utf-8")
        self.cli("snapshot", "so", "-m", "1")
        sp.write_text(json.dumps({"nodes": {"a": {"label": "A", "kind": "agent", "status": "tbd"}}, "edges": []}), encoding="utf-8")
        rc, out = self.cli("snapshot", "so", "-m", "2")
        self.assertIn("快照 r02", out)
        self.assertIn("~节点 a（status）", out)

    def test_human_edit_fields_are_accepted(self):  # human-edits.md: by / since / intent / decisions
        self.write("he", fixture())
        sp = self.tmp / "he" / "he.spec.json"
        spec = {"nodes": {"grp": {"label": "应用层", "kind": "group"},
                          "a": {"label": "Agent A\n规划", "kind": "agent", "group": "grp"},
                          "db": {"label": "记忆 & 知识", "kind": "datastore"}},
                "edges": [{"from": "a", "to": "db", "label": "读写", "type": "readwrite"}]}
        sp.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(self.cli("snapshot", "he", "-m", "1")[0], 0)
        spec["nodes"]["a"].update(by="team:张三", since="r02", intent="统一术语")
        spec["nodes"]["db"]["by"] = "user"
        spec["edges"][0]["by"] = "team"
        spec["decisions"] = [{"rule": "统一用「规划」", "from": "h001", "status": "assumed"}]
        sp.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
        rc, out = self.cli("check", "he", "--no-preview")
        self.assertEqual(rc, 0, out)
        self.assertNotIn("未知", out)
        rc, out = self.cli("snapshot", "he", "-m", "合入 1 处人工改动")
        self.assertIn("快照 r02", out)  # provenance changes are recorded in the history
        self.assertIn("~节点 a", out)

    def test_check_normalizes_compressed_and_reports(self):
        f = self.write("cmp", compress(fixture()))
        rc, out = self.cli("check", "cmp", "--no-preview")
        self.assertIn("检测到压缩格式", out)
        self.assertNotIn("<diagram id=\"p1\" name=\"总览\">H", f.read_text(encoding="utf-8"))
        self.assertTrue(list((self.tmp / "cmp" / "history").glob("_compressed-*.drawio")))
        self.assertIn("没有清单文件", out)

    def test_check_fails_on_spec_error(self):
        self.write("bad", fixture())
        (self.tmp / "bad" / "bad.spec.json").write_text(json.dumps(
            {"nodes": {"ghost": {"label": "幽灵", "kind": "agent"}}, "edges": []}, ensure_ascii=False), encoding="utf-8")
        rc, out = self.cli("check", "bad", "--no-preview")
        self.assertEqual(rc, 1, out)
        self.assertIn("缺少节点：ghost", out)

    def test_bad_json_spec_reports_line(self):
        self.write("bj", fixture())
        (self.tmp / "bj" / "bj.spec.json").write_text('{"nodes": {,}}', encoding="utf-8")
        rc, out = self.cli("check", "bj", "--no-preview")
        self.assertEqual(rc, 1)
        self.assertIn("JSON 格式错误", out)

    def test_sync_unconfigured_is_clear(self):
        self.write("sy", fixture())
        with mock.patch.dict(os.environ, {"AD_LARK_CLI": "none"}):  # no lark-cli: manual delivery steps
            rc, out = self.cli("sync", "sy")
        self.assertEqual(rc, 2)
        self.assertIn("导入", out)

    def test_legend_is_valid_and_idempotent(self):
        f = self.write("lg", fixture())
        (self.tmp / "lg" / "lg.spec.json").write_text(json.dumps(
            {"nodes": {"grp": {"label": "应用层", "kind": "group"}, "a": {"label": "Agent A\n规划", "kind": "agent", "group": "grp"},
                       "db": {"label": "记忆 & 知识", "kind": "datastore", "status": "tbd"}},
             "edges": [{"from": "a", "to": "db", "label": "读写", "type": "readwrite"}]}, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(self.cli("legend", "lg")[0], 0)
        self.assertEqual(self.cli("legend", "lg")[0], 0)
        text = f.read_text(encoding="utf-8")
        self.assertEqual(text.count('id="legend"'), 1)
        errs, _, lines = diagram.run_validate(f)
        self.assertEqual(errs, 0, lines)

    def test_legend_keeps_rest_of_file_byte_identical(self):  # regression D9
        f = self.write("bi", fixture())
        before = f.read_text(encoding="utf-8")
        self.cli("legend", "bi")
        after = f.read_text(encoding="utf-8")
        stripped = re.sub(r'\s*<mxCell id="legend[^"]*"[^>]*?(?:/>|>.*?</mxCell>)', "", after, flags=re.S)
        self.assertEqual(stripped.replace("\n</root>", "</root>"), before.replace("\n</root>", "</root>"))

    def test_written_files_use_lf_on_every_os(self):  # regression W1: Windows text mode wrote CRLF
        self.assertEqual(self.cli("new", "lf", "--title", "换行")[0], 0)
        d = self.tmp / "lf"
        (d / "lf.drawio").write_bytes(fixture().encode("utf-8"))
        (d / "lf.spec.json").write_bytes(json.dumps(
            {"nodes": {"a": {"label": "Agent A\n规划", "kind": "agent"},
                       "db": {"label": "记忆 & 知识", "kind": "datastore", "status": "tbd"}},
             "edges": []}, ensure_ascii=False).encode("utf-8"))
        out = self.cli("legend", "lf")[1]
        self.assertIn("待定项", out)  # legend summary uses display names, not internal keys
        self.assertEqual(self.cli("snapshot", "lf", "-m", "r1")[0], 0)
        for p in [d / "lf.drawio", d / "history" / "CHANGELOG.md"]:
            self.assertNotIn(b"\r", p.read_bytes(), p.name)
        self.assertEqual(self.cli("new", "lf2")[0], 0)
        for p in (self.tmp / "lf2").glob("lf2.*"):
            self.assertNotIn(b"\r", p.read_bytes(), p.name)

    def test_export_failure_is_not_reported_as_success(self):  # regression B23
        self.write("ex", fixture())
        old = os.environ.get("DRAWIO_CLI")
        os.environ["DRAWIO_CLI"] = sys.executable  # any program that exits without writing the output
        try:
            rc, out = self.cli("export", "ex", "--pdf")
        finally:
            if old is None:
                os.environ.pop("DRAWIO_CLI", None)
            else:
                os.environ["DRAWIO_CLI"] = old
        self.assertEqual(rc, 1, out)
        self.assertIn("✗ 导出失败", out)
        self.assertNotIn("✓ 第 1 页", out)
        self.assertNotIn("✓ PDF", out)

    def test_macros_are_expanded_on_disk_and_unknown_ones_fail(self):  # perf #8
        f = self.write("mc", to_macros(fixture()))
        self.cli("inspect", "mc")
        self.assertNotIn('style="@', f.read_text(encoding="utf-8"))
        self.assertEqual(f.read_text(encoding="utf-8"), fixture())  # expansion restores the exact original
        bad = self.write("mb", fixture().replace('style="', 'style="@agnet;', 1))
        rc, out = self.cli("check", "mb", "--no-preview")
        self.assertEqual(rc, 1, out)
        self.assertIn("未知样式代号：@agnet", out)

    def test_perf_log_mark_and_summary(self):  # perf #9
        self.assertEqual(self.cli("list")[0], 0)
        self.assertEqual(self.cli("perf", "--mark", "实验开始")[0], 0)
        self.assertEqual(self.cli("new", "pf", "--title", "计时")[0], 0)
        rows = [json.loads(x) for x in (self.tmp / "_perf.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([r["cmd"] for r in rows], ["list", "mark", "new"])
        self.assertTrue(all("dur" in r and "ts" in r for r in rows))
        rc, out = self.cli("perf")
        self.assertEqual(rc, 0, out)
        self.assertIn("距上条命令结束", out)
        self.assertIn("实验开始", out)
        self.assertIn("中位耗时", out)

    def test_open_reminder_matches_drawio_window(self):  # W2: draw.io open while the file changes
        msg = diagram.open_reminder("kitting-agent.drawio", ["kitting-agent.drawio - draw.io", "笔记 - 记事本"])
        self.assertIn("点击这里进行同步", msg)
        self.assertIn("选「同步」", msg)
        self.assertIsNone(diagram.open_reminder("kitting-agent.drawio", ["other.drawio - draw.io"]))
        self.assertIsInstance(diagram._drawio_window_titles(), list)

    def test_legend_mirrors_actual_colors(self):  # regression D18
        f = self.write("lc", fixture().replace("fillColor=#e3f2fd;strokeColor=#1565c0;", "fillColor=#123456;strokeColor=#654321;"))
        (self.tmp / "lc" / "lc.spec.json").write_text(json.dumps(
            {"nodes": {"a": {"label": "Agent A\n规划", "kind": "agent"}, "db": {"label": "记忆 & 知识", "kind": "datastore"}},
             "edges": [{"from": "a", "to": "db", "label": "读写", "type": "readwrite"}]}, ensure_ascii=False), encoding="utf-8")
        self.cli("legend", "lc")
        legend = re.search(r'<mxCell id="legend-agent"[^>]*>', f.read_text(encoding="utf-8")).group(0)
        self.assertIn("#123456", legend)

    def test_legend_per_page_and_flow_rules(self):  # regression D15/D20
        sp = {"nodes": {"a": {"label": "A", "kind": "agent"}, "s": {"label": "S", "kind": "step"},
                        "d": {"label": "D", "kind": "decision", "page": "流程"}, "x": {"label": "X", "kind": "step", "page": "流程"}},
              "edges": [{"from": "a", "to": "s", "type": "readwrite"}, {"from": "d", "to": "x"}]}
        need1, items1, _ = diagram._page_legend_items(sp, "总览", True)
        need2, items2, _ = diagram._page_legend_items(sp, "流程", False)
        self.assertTrue(need1)
        self.assertIn(("v", "step"), items1)        # flow symbol inside an architecture page: explained
        self.assertFalse(need2)                     # pure flowchart page with plain arrows: no legend

    def test_lint_ignores_legend_and_empty_cells(self):  # regression D2
        f = self.write("ln", fixture())
        self.cli("legend", "ln")
        _, cs = diagram.all_cells(f)
        self.assertFalse(any("legend" in w for w in diagram.lint(cs)))

    def test_mermaid_strips_reserved_and_fixes_bidir(self):
        f = self.write("mm", fixture())
        self.cli("legend", "mm")
        rc, out = self.cli("mermaid", "mm")
        self.assertEqual(rc, 0, out)
        mmd = (self.tmp / "mm" / "mm.mmd").read_text(encoding="utf-8")
        self.assertNotIn("标题", mmd)
        self.assertNotIn("图例", mmd)
        self.assertIn("<-->", mmd)


class DocTests(unittest.TestCase):
    def test_style_guide_matches_house_style(self):
        doc = (ROOT / "references" / "style-guide.md").read_text(encoding="utf-8")
        for kind, (_, style, _) in hs.KINDS.items():
            self.assertIn(style, doc, f"style-guide.md 中 {kind} 的样式与 house_style.py 不一致")
        for kind, (_, style) in hs.EDGES.items():
            self.assertIn(style, doc, f"style-guide.md 中连线 {kind} 的样式与 house_style.py 不一致")
        self.assertIn(hs.TBD_SUFFIX, doc)
        self.assertIn(hs.TBD_EDGE_SUFFIX, doc)
        for name in [*hs.KINDS, *hs.EDGES, "title"]:  # perf #8: every macro is documented
            self.assertIn(f"`@{name}`", doc, f"style-guide.md 缺少代号 @{name}")
        self.assertIn("+tbd", doc)

    def test_skill_md_references_exist(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        for rel in re.findall(r"\$AD[\\/]([\w./\\-]+\.(?:md|py|json))", text):
            self.assertTrue((ROOT / rel.replace("\\", "/")).exists(), f"SKILL.md 引用的文件不存在：{rel}")
        sub = set(re.findall(r"diagram\.py (\w+)", text))
        known = set(re.findall(r'add_parser\("(\w+)"', (SCRIPTS / "diagram.py").read_text(encoding="utf-8")))
        self.assertTrue(sub <= known, f"SKILL.md 提到了不存在的子命令：{sub - known}")

    def test_frontmatter(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        m = re.match(r"---\nname: ([a-z0-9-]+)\ndescription: (.+?)\n---\n", text, re.S)
        self.assertIsNotNone(m, "frontmatter 格式错误")
        self.assertEqual(m.group(1), "arch-diagram")
        self.assertLessEqual(len(m.group(2)), 1024)
        self.assertNotIn("disable-model-invocation", text.split("---")[1])


if __name__ == "__main__":
    unittest.main()
