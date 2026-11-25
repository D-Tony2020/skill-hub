# -*- coding: utf-8 -*-
"""Tests of the Agent-side CLI (bag.sh) against the simulated airlock."""
import os
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Env, sh, BAG_SH, SKILL  # noqa: E402


def last_line(p):
    lines = [l for l in p.stdout.splitlines() if l.strip()]
    return lines[-1] if lines else ""


class BagTest(unittest.TestCase):
    def setUp(self):
        self.e = Env()
        self.bag_home = os.path.join(self.e.root, "baghome")
        self.env = dict(self.e.env, BAG_HOME=self.bag_home, HOME=self.e.winhome,
                        BAG_SSH="%s %s" % (sys.executable, self.e.fake_ssh))

    def tearDown(self):
        self.e.close()

    def bag(self, *args, check=True):
        p = subprocess.run(["bash", BAG_SH] + list(args), env=self.env, capture_output=True, text=True)
        if check and p.returncode != 0:
            raise AssertionError("bag %s failed:\n%s\n%s" % (args, p.stdout, p.stderr))
        return p

    def clone(self):
        p = self.bag("clone", os.path.join(self.e.winhome, "work", "proj"))
        self.assertIn("RESULT ok clone", last_line(p))
        return os.path.join(self.e.winhome, "work", "proj")

    def test_full_cycle(self):
        d = self.clone()
        p = self.bag("start", "Fix Login Timeout!")
        self.assertEqual(last_line(p), "RESULT ok start branch=deans-cc/fix-login-timeout")
        open(os.path.join(d, "a.txt"), "w").write("x\n")
        sh("git add . && git commit -qm 'fix: login timeout'", cwd=d, env=self.env)
        p = self.bag("push", "--title", "修复登录超时", "--desc", "line1\nline2")
        self.assertIn("RESULT ok push branch=deans-cc/fix-login-timeout mr=https://gitlab.test/grp/proj/-/merge_requests/1",
                      last_line(p))
        mr = self.e.load_mrs()[0]
        self.assertEqual(mr["title"], "Draft: 修复登录超时")
        self.assertIn("line1 line2", mr["description"])
        p = self.bag("mr")
        self.assertIn('"iid": 1', p.stdout)
        p = self.bag("notes")
        self.assertIn('"notes": []', p.stdout)
        # nothing new -> still reports MR
        p = self.bag("push")
        self.assertIn("mr=https://gitlab.test/grp/proj/-/merge_requests/1", last_line(p))

    def test_push_requires_prefix_branch(self):
        d = self.clone()
        sh("git switch -q -c feature/x", cwd=d, env=self.env)
        p = self.bag("push", check=False)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("RESULT fail code=E_POLICY_PREFIX", last_line(p))

    def test_push_rejection_code_is_surfaced(self):
        d = self.clone()
        self.bag("start", "secret")
        open(os.path.join(d, "k.pem"), "w").write("-----BEGIN RSA PRIVATE KEY-----\nabc\n")
        sh("git add . && git commit -qm key", cwd=d, env=self.env)
        p = self.bag("push", check=False)
        self.assertIn("RESULT fail code=E_POLICY_SECRET", last_line(p))
        self.assertIn("AIRLOCK HINT", p.stdout)

    def test_start_refuses_dirty_tree(self):
        d = self.clone()
        open(os.path.join(d, "dirty.txt"), "w").write("x")
        p = self.bag("start", "t", check=False)
        self.assertIn("RESULT fail code=E_DIRTY", last_line(p))

    def test_unreachable_mac(self):
        self.clone()
        self.env["FAKE_SSH_DOWN"] = "1"
        p = self.bag("sync", check=False)
        self.assertIn("RESULT fail code=E_MAC_UNREACHABLE", last_line(p))

    def test_not_cloned(self):
        p = self.bag("sync", check=False)
        self.assertIn("RESULT fail code=E_REPO_MISSING", last_line(p))

    def test_learn_and_history(self):
        p = self.bag("learn", "hotspot changed -> Mac got new IP -> doctor rediscovered")
        self.assertIn("RESULT ok learned", last_line(p))
        self.assertIn("hotspot changed", open(os.path.join(self.bag_home, "learnings.md")).read())

    def test_bundle_embeds_payload_and_params(self):
        os.makedirs(self.bag_home, exist_ok=True)
        if shutil.which("ssh-keygen"):
            self.bag("init")
        else:
            open(os.path.join(self.bag_home, "id_ed25519.pub"), "w").write("ssh-ed25519 AAAATEST agent\n")
            open(os.path.join(self.bag_home, "id_ed25519"), "w").write("x")
        p = self.bag("bundle", "--gitlab-url", "https://git.corp.local/grp/sub/proj.git?a=1&b=2", "--prefix", "deans-cc")
        self.assertIn("RESULT ok bundle", last_line(p))
        f = os.path.join(self.bag_home, "bundle", "blacklake-airlock-installer.sh")
        body = open(f).read()
        self.assertIn('DEF_GITLAB_URL="https://git.corp.local/grp/sub/proj.git?a=1&b=2"', body)
        self.assertIn('DEF_PREFIX="deans-cc/"', body)
        self.assertNotIn("__BAG_PUBKEY__", body.split("__AIRLOCK_PY_BEGIN__")[0].replace('placeholder()', ''))
        self.assertEqual(subprocess.run(["bash", "-n", f]).returncode, 0)
        # payload extraction == airlock.py
        payload = subprocess.run(["awk", '/^__AIRLOCK_PY_BEGIN__$/{f=1;next} /^__AIRLOCK_PY_END__$/{f=0} f', f],
                                 capture_output=True, text=True).stdout
        self.assertEqual(payload, open(os.path.join(SKILL, "scripts", "mac", "airlock.py")).read())


class UpdateTest(unittest.TestCase):
    """bag.sh update: pulls the skill from its source repo and reinstalls it, recording provenance."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        t = self.tmp
        self.genv = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@x", GIT_COMMITTER_NAME="t",
                         GIT_COMMITTER_EMAIL="t@x")
        # a fake "skill-hub" remote containing this skill
        work = os.path.join(t, "author")
        os.makedirs(os.path.join(work, "skills"))
        shutil.copytree(SKILL, os.path.join(work, "skills", "blacklake-auto-git"),
                        ignore=shutil.ignore_patterns("__pycache__"))
        sh("git init -q -b main && git add -A && git commit -qm init", cwd=work, env=self.genv)
        self.remote = os.path.join(t, "remote.git")
        sh(["git", "clone", "-q", "--bare", work, self.remote])
        self.author = os.path.join(t, "author2")
        sh(["git", "clone", "-q", self.remote, self.author])
        # Dean's machine: clone + install
        self.clone = os.path.join(t, "skill-hub")
        sh(["git", "clone", "-q", self.remote, self.clone])
        self.skills = os.path.join(t, "skills")
        self.env = dict(self.genv, HOME=os.path.join(t, "home"), BAG_HOME=os.path.join(t, "bag"),
                        BAG_SRC=self.clone, BAG_SRC_URL=self.remote, CLAUDE_SKILLS_DIR=self.skills)
        os.makedirs(self.env["HOME"])
        sh(["bash", os.path.join(self.clone, "skills/blacklake-auto-git/scripts/install_local.sh")], env=self.env)
        self.installed = os.path.join(self.skills, "blacklake-auto-git")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_bag(self, *args):
        return subprocess.run(["bash", os.path.join(self.installed, "scripts", "bag.sh")] + list(args),
                              env=self.env, capture_output=True, text=True)

    def publish(self, rel, content, msg):
        open(os.path.join(self.author, "skills/blacklake-auto-git", rel), "w").write(content)
        sh("git add -A && git commit -qm '%s' && git push -q origin main" % msg, cwd=self.author, env=self.genv)

    def test_version_reports_source(self):
        p = self.run_bag("version")
        self.assertIn("source.repo=" + self.remote, p.stdout)
        self.assertIn("source.commit=", p.stdout)
        self.assertIn("source.path=skills/blacklake-auto-git", p.stdout)

    def test_version_falls_back_to_metadata_version(self):
        # a copy installed from SkillHub has no VERSION file; the publisher writes metadata.version
        os.remove(os.path.join(self.installed, "VERSION"))
        md = os.path.join(self.installed, "SKILL.md")
        text = open(md).read()
        open(md, "w").write(text.replace("\n---\n", "\nmetadata:\n  version: 7.7.7\n---\n", 1))
        self.assertIn("skill=7.7.7", self.run_bag("version").stdout)

    def test_update_pulls_and_reinstalls(self):
        self.assertIn("already_latest", last_line(self.run_bag("update")))
        self.publish("VERSION", "9.9.9\n", "bump")
        p = self.run_bag("update")
        self.assertIn("RESULT ok update version=", last_line(p), p.stdout + p.stderr)
        self.assertIn("->9.9.9", last_line(p))
        self.assertNotIn("mac_upgrade_needed", last_line(p))
        self.assertEqual(open(os.path.join(self.installed, "VERSION")).read().strip(), "9.9.9")
        new = sh(["git", "rev-parse", "--short", "HEAD"], cwd=self.author).stdout.strip()
        self.assertIn("commit=" + new, open(os.path.join(self.installed, "SOURCE")).read())

    def test_update_flags_mac_upgrade(self):
        p = os.path.join(self.author, "skills/blacklake-auto-git/scripts/mac/airlock.py")
        body = open(p).read().replace('VERSION = "', 'VERSION = "8', 1)
        self.publish("scripts/mac/airlock.py", body, "airlock change")
        p = self.run_bag("update")
        self.assertIn("mac_upgrade_needed=yes", last_line(p), p.stdout + p.stderr)

    def test_update_refuses_downgrade(self):
        # installed copy is newer than main (e.g. installed from an unmerged PR branch)
        open(os.path.join(self.installed, "VERSION"), "w").write("99.0.0\n")
        self.publish("README.extra", "x", "unrelated change on main")
        p = self.run_bag("update")
        self.assertIn("RESULT fail code=E_SRC_DOWNGRADE", last_line(p), p.stdout + p.stderr)
        self.assertEqual(open(os.path.join(self.installed, "VERSION")).read().strip(), "99.0.0")
        p = self.run_bag("update", "--allow-downgrade")
        self.assertIn("RESULT ok update", last_line(p), p.stdout + p.stderr)

    def test_version_compare_is_numeric(self):
        p = subprocess.run(["bash", "-c", 'source <(sed -n "/^version_lt()/,/^}/p" "%s"); '
                            'version_lt 1.9.0 1.10.0 && ! version_lt 1.10.0 1.9.0 && ! version_lt 1.1.0 1.1.0 && echo yes'
                            % os.path.join(SKILL, "scripts", "bag.sh")], capture_output=True, text=True)
        self.assertEqual(p.stdout.strip(), "yes", p.stderr)

    def test_update_refuses_dirty_source(self):
        open(os.path.join(self.clone, "skills/blacklake-auto-git/SKILL.md"), "a").write("local edit\n")
        p = self.run_bag("update")
        self.assertIn("RESULT fail code=E_SRC_DIRTY", last_line(p))


class CrlfTest(unittest.TestCase):
    def test_bundle_from_crlf_checkout_is_lf(self):
        """Git for Windows (autocrlf) may check files out with CRLF; the Mac installer must still be LF."""
        import tempfile
        tmp = tempfile.mkdtemp()
        try:
            skill = os.path.join(tmp, "skill")
            shutil.copytree(SKILL, skill, ignore=shutil.ignore_patterns("__pycache__"))
            for rel in ("scripts/mac/install.sh", "scripts/mac/airlock.py"):
                p = os.path.join(skill, rel)
                data = open(p, "rb").read().replace(b"\n", b"\r\n")
                open(p, "wb").write(data)
            home = os.path.join(tmp, "home")
            os.makedirs(home)
            open(os.path.join(home, "id_ed25519.pub"), "w").write("ssh-ed25519 AAAATEST agent\n")
            open(os.path.join(home, "id_ed25519"), "w").write("x")
            env = dict(os.environ, BAG_HOME=home)
            p = subprocess.run(["bash", os.path.join(skill, "scripts", "bag.sh"), "bundle", "--gitlab-url",
                                "https://g.example/a/b.git"], env=env, capture_output=True, text=True)
            self.assertIn("RESULT ok bundle", p.stdout, p.stdout + p.stderr)
            body = open(os.path.join(home, "bundle", "blacklake-airlock-installer.sh"), "rb").read()
            self.assertNotIn(b"\r", body)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
