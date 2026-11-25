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
