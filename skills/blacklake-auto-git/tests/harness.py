# -*- coding: utf-8 -*-
"""Simulated three-party environment for end-to-end tests (no network, no sshd).

    dev clone  --GIT_SSH_COMMAND=fake_ssh.py-->  airlock gate  --> airlock repo
    airlock pre-receive --file path--> fake GitLab bare repo (+ post-receive that
    mimics GitLab's "View merge request" output) and a fake GitLab REST API.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlsplit, parse_qs, unquote

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
AIRLOCK_PY = os.path.join(SKILL, "scripts", "mac", "airlock.py")
BAG_SH = os.path.join(SKILL, "scripts", "bag.sh")
TOKEN = "glpat-TESTTOKENtesttoken1234"

FAKE_GITLAB_POST_RECEIVE = r'''#!/usr/bin/env python3
import json, os, sys
mrs_path = os.environ.get("FAKE_MRS") or os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "..", "mrs.json")
opts = {}
for i in range(int(os.environ.get("GIT_PUSH_OPTION_COUNT", "0") or 0)):
    v = os.environ["GIT_PUSH_OPTION_%d" % i]
    k, _, val = v.partition("=")
    opts[k] = val
try:
    mrs = json.load(open(mrs_path))
except Exception:
    mrs = []
for line in sys.stdin:
    old, new, ref = line.split()
    br = ref[len("refs/heads/"):]
    if "merge_request.create" in opts and not any(m["source_branch"] == br and m["state"] == "opened" for m in mrs):
        iid = len(mrs) + 1
        mrs.append({"iid": iid, "source_branch": br, "target_branch": opts.get("merge_request.target", "main"),
                    "title": opts.get("merge_request.title", br), "description": opts.get("merge_request.description", ""),
                    "state": "opened", "draft": opts.get("merge_request.title", "").startswith("Draft:"),
                    "remove_source_branch": "merge_request.remove_source_branch" in opts,
                    "web_url": "https://gitlab.test/grp/proj/-/merge_requests/%d" % iid, "notes": []})
    for m in mrs:
        if m["source_branch"] == br and m["state"] == "opened":
            sys.stderr.write("\nView merge request for %s:\n  %s\n" % (br, m["web_url"]))
json.dump(mrs, open(mrs_path, "w"))
'''

FAKE_SSH = r'''#!/usr/bin/env python3
# Mimics `ssh [opts] host command` hitting a ForceCommand: runs airlock gate locally.
import os, sys
args = sys.argv[1:]
i = 0
while i < len(args) and args[i].startswith("-"):
    i += 2 if args[i] in ("-o", "-p", "-i", "-F", "-l") else 1
host, cmd = args[i], " ".join(args[i + 1:])
if os.environ.get("FAKE_SSH_DOWN") == "1":
    sys.stderr.write("ssh: connect to host %s port 22: Connection timed out\n" % host)
    sys.exit(255)
env = dict(os.environ, SSH_ORIGINAL_COMMAND=cmd)
os.execvpe(sys.executable, [sys.executable, os.environ["AIRLOCK_PY"], "gate"], env)
'''


class FakeApi(BaseHTTPRequestHandler):
    mrs_path = None

    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.headers.get("PRIVATE-TOKEN") != TOKEN:
            return self._send(401, {"message": "401 Unauthorized"})
        u = urlsplit(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        parts = [unquote(p) for p in u.path.split("/") if p]
        try:
            mrs = json.load(open(self.mrs_path))
        except Exception:
            mrs = []
        if parts[:3] == ["api", "v4", "personal_access_tokens"]:
            return self._send(200, {"active": True, "revoked": False, "expires_at": "2099-01-01",
                                    "scopes": ["api", "write_repository"]})
        if parts[:3] == ["api", "v4", "projects"] and len(parts) == 4:
            return self._send(200, {"id": 1, "path_with_namespace": parts[3]})
        if parts[:3] == ["api", "v4", "projects"] and len(parts) >= 5 and parts[4] == "merge_requests":
            if len(parts) == 5:
                res = [m for m in mrs if m["source_branch"] == q.get("source_branch")
                       and q.get("state", "all") in ("all", m["state"])]
                return self._send(200, res[::-1])
            iid = int(parts[5])
            m = [x for x in mrs if x["iid"] == iid]
            if not m:
                return self._send(404, {"message": "404 Not found"})
            if len(parts) == 7 and parts[6] == "discussions":
                return self._send(200, [{"id": "d1", "notes": m[0]["notes"]}])
            return self._send(200, dict(m[0], head_pipeline={"status": "success", "web_url": "x"},
                                        detailed_merge_status="mergeable"))
        return self._send(404, {"message": "404 Not found"})


def sh(cmd, cwd=None, env=None, check=True, inp=None):
    p = subprocess.run(cmd, cwd=cwd, env=env, input=inp, capture_output=True, text=True, shell=isinstance(cmd, str))
    if check and p.returncode != 0:
        raise AssertionError("cmd failed (%s): %s\nstdout:%s\nstderr:%s" % (p.returncode, cmd, p.stdout, p.stderr))
    return p


class Env(object):
    def __init__(self, conf_overrides=None):
        self.root = tempfile.mkdtemp(prefix="bag-test-")
        r = self.root
        self.gitlab = os.path.join(r, "gitlab.git")
        self.mrs = os.path.join(r, "mrs.json")
        self.home = os.path.join(r, "airlock-home")
        self.data = os.path.join(r, "airlock-data")
        self.dev = os.path.join(r, "dev")
        self.winhome = os.path.join(r, "winhome")
        for d in (self.home, self.data, os.path.join(self.home, "hooks"), self.winhome):
            os.makedirs(d)
        # --- fake gitlab
        sh(["git", "init", "-q", "--bare", "-b", "main", self.gitlab])
        sh(["git", "--git-dir", self.gitlab, "config", "receive.advertisePushOptions", "true"])
        hook = os.path.join(self.gitlab, "hooks", "post-receive")
        open(hook, "w").write(FAKE_GITLAB_POST_RECEIVE)
        os.chmod(hook, 0o755)
        seed = os.path.join(r, "seed")
        sh(["git", "init", "-q", "-b", "main", seed])
        self.git_ident(seed)
        open(os.path.join(seed, "README.md"), "w").write("hello\n")
        sh("git add . && git commit -qm init && git push -q %s main" % self.gitlab, cwd=seed)
        sh(["git", "checkout", "-q", "-b", "feature/human"], cwd=seed)
        sh("git push -q %s feature/human" % self.gitlab, cwd=seed)
        self.seed = seed
        # --- fake api
        FakeApi.mrs_path = self.mrs
        self.httpd = HTTPServer(("127.0.0.1", 0), FakeApi)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        api_base = "http://127.0.0.1:%d" % self.httpd.server_port
        # --- airlock
        shutil.copy(AIRLOCK_PY, os.path.join(self.home, "airlock.py"))
        conf = {"gitlab_repo_url": self.gitlab, "gitlab_api_base": api_base, "project_path": "grp/proj",
                "data_dir": self.data, "target_branch": "main", "branch_prefix": "deans-cc/",
                "max_push_mb": 1, "max_file_mb": 0.5}
        conf.update(conf_overrides or {})
        self.conf_path = os.path.join(self.home, "airlock.conf.json")
        json.dump(conf, open(self.conf_path, "w"))
        open(os.path.join(self.data, "gitlab-token"), "w").write(TOKEN + "\n")
        shim = os.path.join(self.home, "hooks", "pre-receive")
        open(shim, "w").write('#!/bin/sh\nexec "%s" "%s" pre-receive\n' % (sys.executable,
                                                                          os.path.join(self.home, "airlock.py")))
        os.chmod(shim, 0o755)
        self.fake_ssh = os.path.join(r, "fake_ssh.py")
        open(self.fake_ssh, "w").write(FAKE_SSH)
        os.chmod(self.fake_ssh, 0o755)
        self.env = dict(os.environ, AIRLOCK_HOME=self.home, AIRLOCK_CONF=self.conf_path,
                        AIRLOCK_PY=os.path.join(self.home, "airlock.py"), FAKE_MRS=self.mrs,
                        GIT_SSH_COMMAND="%s %s" % (sys.executable, self.fake_ssh),
                        GIT_AUTHOR_NAME="agent", GIT_AUTHOR_EMAIL="agent@x", GIT_COMMITTER_NAME="agent",
                        GIT_COMMITTER_EMAIL="agent@x")
        self.env.pop("GIT_CONFIG_COUNT", None)
        for k in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY"):
            self.env.pop(k, None)
        sh([sys.executable, os.path.join(self.home, "airlock.py"), "init-repo"], env=self.env)
        sh([sys.executable, os.path.join(self.home, "airlock.py"), "sync"], env=self.env)

    @staticmethod
    def git_ident(repo):
        sh(["git", "config", "user.name", "t"], cwd=repo)
        sh(["git", "config", "user.email", "t@x"], cwd=repo)

    def airlock(self, *args, **kw):
        return sh([sys.executable, os.path.join(self.home, "airlock.py")] + list(args), env=self.env, **kw)

    def gate(self, command, check=False):
        env = dict(self.env, SSH_ORIGINAL_COMMAND=command)
        return sh([sys.executable, os.path.join(self.home, "airlock.py"), "gate"], env=env, check=check)

    def clone(self):
        sh(["git", "clone", "-q", "airlock:repo.git", self.dev], env=self.env)
        return self.dev

    def commit(self, path, content, msg, cwd=None):
        cwd = cwd or self.dev
        full = os.path.join(cwd, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        mode = "wb" if isinstance(content, bytes) else "w"
        open(full, mode).write(content)
        sh(["git", "add", "-A"], cwd=cwd, env=self.env)
        sh(["git", "commit", "-qm", msg], cwd=cwd, env=self.env)

    def push(self, *args, cwd=None):
        return sh(["git", "push"] + list(args), cwd=cwd or self.dev, env=self.env, check=False)

    def gitlab_ref(self, branch):
        p = sh(["git", "--git-dir", self.gitlab, "rev-parse", "--verify", "-q", "refs/heads/" + branch], check=False)
        return p.stdout.strip() or None

    def airlock_ref(self, branch):
        p = sh(["git", "--git-dir", os.path.join(self.data, "repo.git"), "rev-parse", "--verify", "-q",
                "refs/heads/" + branch], check=False)
        return p.stdout.strip() or None

    def load_mrs(self):
        try:
            return json.load(open(self.mrs))
        except Exception:
            return []

    def save_mrs(self, mrs):
        json.dump(mrs, open(self.mrs, "w"))

    def close(self):
        self.httpd.shutdown()
        shutil.rmtree(self.root, ignore_errors=True)
