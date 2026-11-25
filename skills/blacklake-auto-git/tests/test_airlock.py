# -*- coding: utf-8 -*-
"""End-to-end tests of the Mac-side airlock: gate, policy, relay, MR, sync."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Env, sh, TOKEN  # noqa: E402


class AirlockTest(unittest.TestCase):
    def setUp(self):
        self.e = Env()
        self.e.clone()

    def tearDown(self):
        self.e.close()

    # ---------------- happy path
    def test_clone_checks_out_main(self):
        p = sh(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=self.e.dev)
        self.assertEqual(p.stdout.strip(), "main")

    def test_push_agent_branch_creates_draft_mr(self):
        e = self.e
        sh(["git", "checkout", "-q", "-b", "deans-cc/fix-timeout"], cwd=e.dev)
        e.commit("src/a.txt", "x\n", "Fix login timeout")
        p = e.push("-u", "origin", "deans-cc/fix-timeout")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("AIRLOCK OK branch=deans-cc/fix-timeout mr=https://gitlab.test/grp/proj/-/merge_requests/1",
                      p.stderr)
        self.assertEqual(e.gitlab_ref("deans-cc/fix-timeout"), e.airlock_ref("deans-cc/fix-timeout"))
        mr = e.load_mrs()[0]
        self.assertEqual(mr["title"], "Draft: Fix login timeout")
        self.assertEqual(mr["target_branch"], "main")
        self.assertTrue(mr["remove_source_branch"])

    def test_second_push_updates_same_mr_and_keeps_title(self):
        e = self.e
        sh(["git", "checkout", "-q", "-b", "deans-cc/t"], cwd=e.dev)
        e.commit("a.txt", "1\n", "first")
        self.assertEqual(e.push("-u", "origin", "deans-cc/t").returncode, 0)
        mrs = e.load_mrs()
        mrs[0]["title"] = "Draft: renamed by Dean"
        e.save_mrs(mrs)
        e.commit("a.txt", "2\n", "second")
        p = e.push()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(e.load_mrs()), 1)
        self.assertEqual(e.load_mrs()[0]["title"], "Draft: renamed by Dean")
        self.assertIn("merge_requests/1", p.stderr)

    def test_push_options_title_description_ready(self):
        e = self.e
        sh(["git", "checkout", "-q", "-b", "deans-cc/opt"], cwd=e.dev)
        e.commit("a.txt", "1\n", "subject")
        p = e.push("-o", "mr.title=Better title", "-o", "mr.description=Why: because", "-o", "mr.ready",
                   "-u", "origin", "deans-cc/opt")
        self.assertEqual(p.returncode, 0, p.stderr)
        mr = e.load_mrs()[0]
        self.assertEqual(mr["title"], "Better title")
        self.assertIn("Why: because", mr["description"])

    # ---------------- policy
    def _expect_reject(self, p, code):
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("AIRLOCK REJECT code=%s" % code, p.stderr)

    def test_reject_push_to_main(self):
        e = self.e
        e.commit("a.txt", "1\n", "direct to main")
        self._expect_reject(e.push("origin", "main"), "E_POLICY_PROTECTED")
        self.assertNotEqual(e.gitlab_ref("main"), sh(["git", "rev-parse", "HEAD"], cwd=e.dev).stdout.strip())

    def test_reject_wrong_prefix(self):
        e = self.e
        sh(["git", "checkout", "-q", "-b", "feature/x"], cwd=e.dev)
        e.commit("a.txt", "1\n", "c")
        self._expect_reject(e.push("origin", "feature/x"), "E_POLICY_PREFIX")
        self.assertIsNone(e.gitlab_ref("feature/x"))

    def test_reject_tag(self):
        e = self.e
        sh(["git", "tag", "v1"], cwd=e.dev)
        self._expect_reject(e.push("origin", "v1"), "E_POLICY_REF")

    def test_reject_force_push(self):
        e = self.e
        sh(["git", "checkout", "-q", "-b", "deans-cc/f"], cwd=e.dev)
        e.commit("a.txt", "1\n", "c1")
        self.assertEqual(e.push("-u", "origin", "deans-cc/f").returncode, 0)
        sh(["git", "commit", "-q", "--amend", "-m", "c1 amended"], cwd=e.dev, env=e.env)
        self._expect_reject(e.push("-f", "origin", "deans-cc/f"), "E_POLICY_FORCE")

    def test_reject_delete(self):
        e = self.e
        sh(["git", "checkout", "-q", "-b", "deans-cc/d"], cwd=e.dev)
        e.commit("a.txt", "1\n", "c1")
        e.push("-u", "origin", "deans-cc/d")
        self._expect_reject(e.push("origin", "--delete", "deans-cc/d"), "E_POLICY_DELETE")
        self.assertIsNotNone(e.gitlab_ref("deans-cc/d"))

    def test_reject_secret(self):
        e = self.e
        sh(["git", "checkout", "-q", "-b", "deans-cc/s"], cwd=e.dev)
        e.commit("conf.py", "KEY = 'AKIAABCDEFGHIJKLMNOP'\n", "add conf")
        self._expect_reject(e.push("origin", "deans-cc/s"), "E_POLICY_SECRET")
        self.assertIsNone(e.gitlab_ref("deans-cc/s"))

    def test_reject_airlock_token_leak(self):
        e = self.e
        sh(["git", "checkout", "-q", "-b", "deans-cc/s2"], cwd=e.dev)
        e.commit("x.txt", "t=%s\n" % TOKEN, "oops")
        p = e.push("origin", "deans-cc/s2")
        self._expect_reject(p, "E_POLICY_SECRET")
        self.assertNotIn(TOKEN, p.stderr)

    def test_reject_big_file(self):
        e = self.e
        sh(["git", "checkout", "-q", "-b", "deans-cc/big"], cwd=e.dev)
        e.commit("blob.bin", os.urandom(700 * 1024), "big")
        self._expect_reject(e.push("origin", "deans-cc/big"), "E_POLICY_FILE_SIZE")

    def test_upstream_diverged_is_rejected_with_hint(self):
        e = self.e
        sh(["git", "checkout", "-q", "-b", "deans-cc/div"], cwd=e.dev)
        e.commit("a.txt", "1\n", "c1")
        e.push("-u", "origin", "deans-cc/div")
        # Dean edits the branch on GitLab (web IDE) -> GitLab moves ahead
        sh("git fetch -q %s deans-cc/div && git checkout -q -b tmp FETCH_HEAD" % e.gitlab, cwd=e.seed)
        open(os.path.join(e.seed, "web.txt"), "w").write("web edit\n")
        sh("git add . && git commit -qm web && git push -q %s tmp:deans-cc/div" % e.gitlab, cwd=e.seed)
        e.commit("a.txt", "2\n", "c2")
        p = e.push()
        self._expect_reject(p, "E_UPSTREAM_DIVERGED")
        self.assertIn("AIRLOCK HINT", p.stderr)
        # recover: sync + pull + push
        e.gate("sync", check=True)
        sh(["git", "pull", "-q", "--no-rebase", "--no-edit", "origin", "deans-cc/div"], cwd=e.dev, env=e.env)
        p = e.push()
        self.assertEqual(p.returncode, 0, p.stderr)

    # ---------------- sync
    def test_sync_brings_upstream_changes_and_prunes(self):
        e = self.e
        sh(["git", "checkout", "-q", "main"], cwd=e.seed)
        open(os.path.join(e.seed, "new.txt"), "w").write("n\n")
        sh("git add . && git commit -qm upstream && git push -q %s main" % e.gitlab, cwd=e.seed)
        sh("git push -q %s --delete feature/human" % e.gitlab, cwd=e.seed)
        r = json.loads(e.gate("sync", check=True).stdout)
        self.assertTrue(r["ok"])
        self.assertEqual(e.airlock_ref("main"), e.gitlab_ref("main"))
        self.assertIsNone(e.airlock_ref("feature/human"))

    def test_sync_failure_is_classified(self):
        e = self.e
        conf = json.load(open(e.conf_path))
        conf["gitlab_repo_url"] = "https://nonexistent-host.invalid/grp/proj.git"
        json.dump(conf, open(e.conf_path, "w"))
        p = e.gate("sync")
        r = json.loads(p.stdout)
        self.assertFalse(r["ok"])
        self.assertIn(r["error_code"], ("E_GITLAB_DNS", "E_GITLAB_UNREACHABLE"))
        st = json.loads(e.gate("status --fast", check=True).stdout)
        self.assertTrue(any(x.startswith("W_LAST_SYNC_FAILED") for x in st["problems"]))

    # ---------------- gate
    def test_gate_denies_shell_and_other_paths(self):
        e = self.e
        for cmd in ("bash", "sh -c id", "git-upload-pack '/etc'", "git-receive-pack '../repo.git'",
                    "git-upload-pack 'repo.git' extra", "rm -rf /", "scp -t /tmp", "internal-sftp",
                    "mr ../../x", "git-upload-archive 'repo.git'"):
            p = e.gate(cmd)
            self.assertEqual(p.returncode, 2, cmd)
            self.assertIn("denied", p.stderr, cmd)

    def test_gate_empty_command_shows_help(self):
        p = self.e.gate("")
        self.assertEqual(p.returncode, 1)
        self.assertIn("Allowed over ssh", p.stdout)

    def test_gate_status_mr_notes(self):
        e = self.e
        st = json.loads(e.gate("status", check=True).stdout)
        self.assertTrue(st["ok"], st)
        self.assertTrue(st["gitlab"]["reachable"])
        self.assertTrue(st["token"]["valid"])
        self.assertNotIn(TOKEN, json.dumps(st))
        sh(["git", "checkout", "-q", "-b", "deans-cc/n"], cwd=e.dev)
        e.commit("a.txt", "1\n", "c")
        e.push("-u", "origin", "deans-cc/n")
        mrs = e.load_mrs()
        mrs[0]["notes"] = [{"system": False, "author": {"username": "dean"}, "body": "rename var",
                            "resolvable": True, "resolved": False,
                            "position": {"new_path": "a.txt", "new_line": 1}},
                           {"system": True, "body": "added 1 commit"}]
        e.save_mrs(mrs)
        mr = json.loads(e.gate("mr deans-cc/n", check=True).stdout)
        self.assertEqual(mr["iid"], 1)
        self.assertTrue(mr["draft"])
        notes = json.loads(e.gate("notes deans-cc/n", check=True).stdout)
        self.assertEqual(len(notes["notes"]), 1)
        self.assertEqual(notes["notes"][0]["file"], "a.txt")
        none = json.loads(e.gate("mr deans-cc/none", check=True).stdout)
        self.assertFalse(none["found"])

    def test_bad_token_reported(self):
        e = self.e
        open(os.path.join(e.data, "gitlab-token"), "w").write("glpat-wrongwrongwrongwrong\n")
        st = json.loads(e.gate("status").stdout)
        self.assertFalse(st["token"]["valid"])
        self.assertIn("E_GITLAB_AUTH", st["problems"])


if __name__ == "__main__":
    unittest.main()
