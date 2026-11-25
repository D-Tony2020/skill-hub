"""Unit + integration tests for scripts/sd.py. Run: python -m unittest discover -s tests"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
sys.path.insert(0, str(SKILL / "scripts"))
sys.path.insert(0, str(HERE))
import sd  # noqa: E402
import fixtures  # noqa: E402


def run(*argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = sd.main(list(argv))
    out = buf.getvalue()
    return rc, out, out.strip().splitlines()[-1]


class Env(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.projects = self.tmp / "claude" / "projects"
        self.ids = fixtures.build(self.projects)
        self.hub = self.tmp / "hub"
        (self.hub / "skills" / "existing-skill").mkdir(parents=True)
        (self.hub / "skills" / "existing-skill" / "SKILL.md").write_text(
            "---\nname: existing-skill\ndescription: does an existing thing\n---\nbody\n", encoding="utf-8")
        self.env = {"SD_HOME": str(self.tmp / "sdhome"), "CLAUDE_CONFIG_DIR": str(self.tmp / "claude"),
                    "SD_HUB": str(self.hub)}
        self._old = {k: os.environ.get(k) for k in self.env}
        os.environ.update(self.env)
        rc, _, last = run("init")
        self.assertEqual(rc, 0, last)

    def tearDown(self):
        for k, v in self._old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def digest(self, *extra):
        rc, out, last = run("digest", *extra)
        self.assertEqual(rc, 0, out)
        return sd.run_dir("latest")


class TestParsing(Env):
    def test_human_turns_skip_noise(self):
        s = sd.parse_session(self.ids["a"])
        users = [t["user"] for t in s["turns"]]
        self.assertEqual(users[0], "/init")
        self.assertEqual(len(users), 3)
        self.assertFalse(any("Caveat" in u or "SIDECHAIN" in u for u in users))
        self.assertTrue(s["turns"][2]["correction"])
        self.assertEqual(s["corrections"], 1)
        self.assertEqual(s["errors"], 1)
        self.assertEqual(s["title"], "采购单清洗脚本")
        self.assertIn("/work/daxin-po/clean_po.py", s["files_written"])

    def test_envelope_unwrapped_and_compaction_counted(self):
        s = sd.parse_session(self.ids["b"])
        self.assertEqual(s["turns"][0]["user"], "新客户的采购单也要清洗，复用上次的思路")
        self.assertEqual(s["compactions"], 1)
        self.assertEqual(s["skills"]["xlsx"], 1)
        self.assertEqual(s["mcp"]["feishu"], 1)
        self.assertTrue(s["turns"][1]["correction"])  # 别再

    def test_command_heads(self):
        self.assertEqual(sd.command_heads("cd /x && python3 -m pip install a | tee log"), ["python3 -m pip", "tee"])
        self.assertEqual(sd.command_heads("python C:\\x\\scripts\\sd.py scan"), ["python sd.py"])
        self.assertEqual(sd.command_heads("FOO=1 git push origin main"), ["git push"])
        self.assertEqual(sd.command_heads("python3 - <<'EOF'\nimport x\nopen(p)\nEOF\n"), ["python3"])


class TestRedaction(unittest.TestCase):
    def test_patterns(self):
        r = sd.Redactor(terms=["大欣精密"])
        out = r(f"push https://dean:{fixtures.SECRET_GH}@github.com {fixtures.SECRET_PW} 电话 {fixtures.PHONE} "
                "mail dean@example.com key sk-ant-api03-abcdefghijklmnop 客户 大欣精密 "
                "Authorization: Bearer abcdefghijklmnopqrstuvwxyz 身份证 110101199003071234")
        for leak in (fixtures.SECRET_GH, "Sup3rS3cret", fixtures.PHONE, "dean@example.com", "sk-ant-api03",
                     "大欣精密", "abcdefghijklmnopqrstuvwxyz", "110101199003071234"):
            self.assertNotIn(leak, out)
        self.assertIn("password=[REDACTED:secret]", out)
        self.assertIn("[TERM1]", out)

    def test_plain_text_untouched(self):
        r = sd.Redactor(terms=[])
        s = "订单号 PO-2026-0001 数量 1200 件，工序 30 分钟"
        self.assertEqual(r(s), s)


class TestPipeline(Env):
    def test_scan_filters_and_incremental(self):
        rc, out, last = run("scan", "--json")
        sel = json.loads(out[: out.rindex("RESULT")])
        self.assertEqual({m["id"][:4] for m in sel}, {"aaaa", "bbbb"})  # cccc has 1 turn
        self.assertNotIn("agent-x", out)
        rd = self.digest()
        run("close")
        rc, out, last = run("scan")
        self.assertIn("sessions=0", last)
        # a session that grows comes back as changed
        with open(self.ids["b"], "a", encoding="utf-8") as f:
            f.write(json.dumps({"type": "user", "sessionId": "bbbb2222-0000-4000-8000-000000000002",
                                "message": {"role": "user", "content": "再加一个字段"}}) + "\n")
        rc, out, last = run("scan")
        self.assertIn("changed=1", last)

    def test_filters(self):
        _, _, last = run("scan", "--project", "other-factory")
        self.assertIn("sessions=1", last)
        _, _, last = run("scan", "--since", "2026-11-05")
        self.assertIn("sessions=1", last)
        _, _, last = run("scan", "--session", "cccc")
        self.assertIn("sessions=1", last)  # explicit id bypasses min-turns

    def test_digest_content_redacted(self):
        (Path(self.env["SD_HOME"]) / "redact.txt").write_text("大欣精密\n", encoding="utf-8")
        rd = self.digest()
        text = (rd / "digests" / "aaaa1111-0000-4000-8000-000000000001.md").read_text(encoding="utf-8")
        for leak in (fixtures.SECRET_GH, "Sup3rS3cret", fixtures.PHONE, "大欣精密"):
            self.assertNotIn(leak, text)
        # nothing in the run directory may carry the raw sensitive term (index titles included)
        for f in rd.rglob("*"):
            if f.is_file():
                self.assertNotIn("大欣精密", f.read_text(encoding="utf-8"), f.name)
        self.assertIn("### T3", text)
        self.assertIn("⚑correction", text)
        self.assertIn("clean_po.py", text)
        ov = (rd / "overview.md").read_text(encoding="utf-8")
        self.assertIn("`python3 -m pip` in 2", ov)  # recurring across both sessions
        cat = (rd / "catalog.md").read_text(encoding="utf-8")
        self.assertIn("existing-skill", cat)
        self.assertIn("Security: credentials found", ov)
        self.assertIn("aaaa1111", ov.split("Security")[1])
        idx = json.loads((rd / "index.json").read_text(encoding="utf-8"))
        self.assertGreater(sum(idx["redactions"].values()), 0)

    def test_digest_budget(self):
        rd = self.digest("--max-chars", "1500")
        for p in (rd / "digests").glob("*.md"):
            self.assertLessEqual(len(p.read_text(encoding="utf-8")), 1500)

    def test_no_sessions(self):
        rc, _, last = run("digest", "--project", "nope")
        self.assertEqual(rc, 1)
        self.assertIn("E_NO_SESSIONS", last)


def good_candidates(run_id):
    return {"run": run_id, "candidates": [
        {"id": "purchase-doc-normalizer", "title": "采购单据标准化", "kind": "rule+code", "layer": "industry",
         "builds_on": ["existing-skill"],
         "summary": "清洗 ERP 采购单", "problem": "每个项目都重写", "fit_rationale": "组件库",
         "evidence": [{"session": "aaaa1111", "turns": ["T3"], "quote": "单位换算"},
                      {"session": "bbbb2222", "turns": ["T1", "T2"]}],
         "scores": {"fit": 5, "reuse": 4, "leverage": 4, "maturity": 3},
         "dedupe": {"action": "new", "target": None},
         "packaging": {"form": "skill", "scripts": ["normalize.py"], "triggers": ["清洗采购单"], "tags": ["procurement"]}},
        {"id": "low-fit-thing", "title": "低契合", "kind": "rule", "layer": "foundation", "summary": "x", "problem": "y", "fit_rationale": "z",
         "evidence": [{"session": "aaaa1111", "turns": ["T1"]}],
         "scores": {"fit": 2, "reuse": 5, "leverage": 5, "maturity": 5},
         "dedupe": {"action": "merge", "target": "existing-skill"}, "packaging": {"form": "rule-snippet"}}]}


class TestCandidates(Env):
    def test_validate_catches_errors(self):
        rd = self.digest()
        bad = good_candidates(rd.name)
        bad["candidates"][0]["evidence"][0]["turns"] = ["T99"]
        bad["candidates"][0]["scores"]["fit"] = 7
        bad["candidates"][1]["id"] = "Bad_ID"
        bad["candidates"][1]["dedupe"] = {"action": "merge"}
        sd.write_json(rd / "candidates.json", bad)
        rc, out, last = run("validate")
        self.assertEqual(rc, 1)
        for frag in ("T99", "scores.fit", "kebab-case", "dedupe.target"):
            self.assertIn(frag, out)

    def test_layers_forms_and_composition(self):
        rd = self.digest()
        c = good_candidates(rd.name)
        c["candidates"].append(
            {"id": "line3-changeover", "title": "产线换型表", "kind": "rule", "layer": "project", "summary": "s",
             "problem": "p", "fit_rationale": "f", "evidence": [{"session": "aaaa1111", "turns": ["T1"]}],
             "scores": {"fit": 5, "reuse": 5, "leverage": 5, "maturity": 5}, "dedupe": {"action": "new"},
             "packaging": {"form": "skill"}, "builds_on": ["ghost-skill"]})
        c["candidates"].append(
            {"id": "po-intake-dialogue", "title": "单据类需求的协作方式", "kind": "interaction", "layer": "foundation",
             "summary": "先给样例单据，再确认字段映射，最后跑样例", "problem": "每个场景重新摸索怎么和 Agent 配合",
             "fit_rationale": "交互流程沉淀", "evidence": [{"session": "aaaa1111", "turns": ["T3"]}, {"session": "bbbb2222", "turns": ["T1"]}],
             "scores": {"fit": 5, "reuse": 4, "leverage": 3, "maturity": 3}, "dedupe": {"action": "new"},
             "packaging": {"form": "rule-snippet", "triggers": ["新单据场景开工时"]}, "builds_on": ["purchase-doc-normalizer"]})
        sd.write_json(rd / "candidates.json", c)
        rc, out, last = run("validate")
        self.assertEqual(rc, 0, out)
        self.assertIn("project-layer asset stays", out)
        self.assertIn("ghost-skill", out)
        self.assertNotIn("purchase-doc-normalizer` is neither", out)
        run("report")
        rep_md = (rd / "report.md").read_text(encoding="utf-8")
        row = next(l for l in rep_md.splitlines() if "line3-changeover" in l and l.startswith("|"))
        self.assertIn("| C |", row)  # project layer forced to C despite perfect scores
        self.assertIn("项目资产", row)
        self.assertIn("interaction → memory", rep_md)  # rule-snippet alias normalised
        run("decide", rd.name, "po-intake-dialogue", "accept")
        rc, out, last = run("scaffold", rd.name, "po-intake-dialogue")
        self.assertEqual(rc, 0, out)
        mem = Path(self.env["SD_HOME"]) / "memory-drafts" / "po-intake-dialogue.md"
        self.assertIn("type: feedback", mem.read_text(encoding="utf-8"))
        run("decide", rd.name, "purchase-doc-normalizer", "accept")
        run("scaffold", rd.name, "purchase-doc-normalizer")
        hub_yaml = (self.hub / "skills" / "purchase-doc-normalizer" / "hub.yaml").read_text(encoding="utf-8")
        self.assertIn("layer-industry", hub_yaml)
        self.assertIn("`existing-skill`", (self.hub / "skills" / "purchase-doc-normalizer" / "SKILL.md").read_text(encoding="utf-8"))

    def test_layer_required(self):
        rd = self.digest()
        c = good_candidates(rd.name)
        del c["candidates"][0]["layer"]
        sd.write_json(rd / "candidates.json", c)
        rc, out, last = run("validate")
        self.assertEqual(rc, 1)
        self.assertIn("missing `layer`", out)

    def test_empty_candidates_need_reason(self):
        rd = self.digest()
        sd.write_json(rd / "candidates.json", {"run": rd.name, "candidates": []})
        rc, out, last = run("validate")
        self.assertEqual(rc, 1)
        self.assertIn("none_reason", out)
        sd.write_json(rd / "candidates.json", {"run": rd.name, "candidates": [], "none_reason": "都是一次性数据"})
        rc, out, last = run("report")
        self.assertEqual(rc, 0, out)
        self.assertIn("都是一次性数据", (rd / "report.md").read_text(encoding="utf-8"))

    def test_reuse_warning_single_session(self):
        rd = self.digest()
        c = good_candidates(rd.name)
        c["candidates"][0]["evidence"] = c["candidates"][0]["evidence"][:1]
        sd.write_json(rd / "candidates.json", c)
        rc, out, last = run("validate")
        self.assertEqual(rc, 0)
        self.assertIn("WARN", out)

    def test_report_decide_scaffold_close(self):
        rd = self.digest()
        sd.write_json(rd / "candidates.json", good_candidates(rd.name))
        rc, out, last = run("report")
        self.assertEqual(rc, 0, out)
        self.assertIn("A=1", last)
        rep = (rd / "report.md").read_text(encoding="utf-8")
        self.assertLess(rep.index("purchase-doc-normalizer"), rep.index("low-fit-thing"))
        self.assertIn("| 2 | C |", rep)  # fit<3 forces C
        # scaffold refuses before acceptance
        rc, _, last = run("scaffold", rd.name, "purchase-doc-normalizer")
        self.assertIn("E_NOT_ACCEPTED", last)
        run("decide", rd.name, "purchase-doc-normalizer", "accept", "--reason", "核心组件")
        run("decide", rd.name, "low-fit-thing", "reject", "--reason", "不在画像内")
        rc, out, last = run("scaffold", rd.name, "purchase-doc-normalizer")
        self.assertEqual(rc, 0, out)
        dest = self.hub / "skills" / "purchase-doc-normalizer"
        skill_md = (dest / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(skill_md.startswith("---\nname: purchase-doc-normalizer\ndescription: "))
        self.assertIn("github.com/D-Tony2020/skill-hub", skill_md)
        self.assertIn("status: draft", (dest / "hub.yaml").read_text(encoding="utf-8"))
        ev = (dest / "references" / "evidence.md").read_text(encoding="utf-8")
        self.assertIn("### T3", ev)
        self.assertNotIn(fixtures.PHONE, ev)
        self.assertTrue((dest / "evals" / "basic-usage" / "graders" / "01-expected-output.md").exists())
        rc, _, last = run("scaffold", rd.name, "purchase-doc-normalizer")
        self.assertIn("E_EXISTS", last)
        run("close")
        led = sd.load_ledger()
        self.assertEqual(len(led["sessions"]), 2)
        self.assertEqual(led["candidates"]["low-fit-thing"]["decision"], "reject")
        # next run warns when a rejected candidate is proposed again
        rd2 = self.digest("--all")
        sd.write_json(rd2 / "candidates.json", good_candidates(rd2.name))
        rc, out, last = run("validate", rd2.name)
        self.assertIn("rejected before", out)
        self.assertIn("low-fit-thing", (rd2 / "catalog.md").read_text(encoding="utf-8"))

    def test_scaffold_passes_hub_validator(self):
        node = shutil.which("node")
        hub_tools = SKILL.parent.parent / "tools" / "hub" / "cli.mjs"
        if not node or not hub_tools.exists() or not (SKILL.parent.parent / "node_modules").exists():
            self.skipTest("skill-hub node tooling not available")
        rd = self.digest()
        sd.write_json(rd / "candidates.json", good_candidates(rd.name))
        run("report")
        run("decide", rd.name, "purchase-doc-normalizer", "accept")
        run("scaffold", rd.name, "purchase-doc-normalizer")
        shutil.copytree(SKILL.parent.parent / "tools", self.hub / "tools")
        os.symlink(SKILL.parent.parent / "node_modules", self.hub / "node_modules")
        shutil.copy(SKILL.parent.parent / "package.json", self.hub / "package.json")
        shutil.rmtree(self.hub / "skills" / "existing-skill")
        r = subprocess.run([node, "tools/hub/cli.mjs", "validate"], cwd=self.hub, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class TestExtract(Env):
    def test_files_and_replay(self):
        rc, out, last = run("files", "aaaa")
        self.assertIn("clean_po.py", out)
        outdir = self.tmp / "out"
        rc, out, last = run("extract", "aaaa", "clean_po", "--out", str(outdir))
        self.assertEqual(rc, 0, out)
        code = (outdir / "clean_po.py").read_text(encoding="utf-8")
        self.assertIn("df['qty'] * df['uom_factor']", code)  # both edits replayed in order
        self.assertIn("edits_applied=2", out)

    def test_extract_missing(self):
        rc, _, last = run("extract", "aaaa", "nope.py", "--out", str(self.tmp / "o"))
        self.assertIn("E_NO_FILE", last)


class TestVersioning(unittest.TestCase):
    def test_version_sources_agree(self):
        import re
        v = (SKILL / "VERSION").read_text(encoding="utf-8").strip()
        ch = re.search(r"^## (\S+)", (SKILL / "CHANGELOG.md").read_text(encoding="utf-8"), re.M).group(1)
        hub = re.search(r"^version:\s*(\S+)", (SKILL / "hub.yaml").read_text(encoding="utf-8"), re.M).group(1)
        self.assertEqual(v, ch)
        self.assertEqual(v, hub)


class TestInstall(Env):
    def test_install_local_and_version(self):
        dest = self.tmp / "skills"
        r = subprocess.run([sys.executable, str(SKILL / "scripts" / "install_local.py"), "--dest", str(dest)],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        inst = dest / "session-distiller"
        self.assertTrue((inst / "SKILL.md").exists())
        self.assertTrue((inst / "SOURCE").exists())
        self.assertFalse((inst / "tests").exists())
        r = subprocess.run([sys.executable, str(inst / "scripts" / "sd.py"), "version"], capture_output=True, text=True,
                           env={**os.environ})
        self.assertIn("RESULT ok version", r.stdout)
        self.assertIn("source.path=skills/session-distiller", r.stdout)

    def test_init_with_preset_profile(self):
        rc, _, last = run("init", "--profile", "blacklake-fde")
        self.assertIn("E_EXISTS", last)  # template already copied in setUp
        rc, _, last = run("init", "--profile", "blacklake-fde", "--force")
        self.assertEqual(rc, 0, last)
        prof = (Path(self.env["SD_HOME"]) / "profile.md").read_text(encoding="utf-8")
        self.assertIn("资产分层", prof)
        self.assertNotIn("TODO", prof)
        rc, _, last = run("init", "--profile", "nope")
        self.assertIn("E_ARGS", last)

    def test_doctor_and_status(self):
        rc, out, last = run("doctor")
        self.assertEqual(rc, 0, out)
        self.assertIn("profile: has TODO", out)
        rc, out, last = run("status")
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
