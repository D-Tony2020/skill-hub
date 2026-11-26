#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""blacklake-auto-git airlock (Mac side).

Runs on the intranet Mac. One bare repo ("airlock") sits between the
Agent's dev machine and the company GitLab:

    dev machine --(ssh, forced command = `airlock.py gate`)--> airlock repo
    airlock repo --(pre-receive: validate + relay + create MR)--> GitLab
    GitLab --(launchd: `airlock.py sync`)--> airlock repo

Subcommands:
    gate          ForceCommand entry point. Reads $SSH_ORIGINAL_COMMAND.
    pre-receive   Git hook entry point (stdin: "<old> <new> <ref>" lines).
    sync          Fetch all branches from GitLab into the airlock repo.
    status        Health report as JSON.
    selftest      Local checks without network (used by the installer).

Compatible with the macOS system python (3.9). Standard library only.
"""
from __future__ import print_function

import base64
import fcntl
import json
import os
import re
import shlex
import ssl
import subprocess
import sys
import time
from urllib import parse as urlparse
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

VERSION = "1.1.0"
ZERO = "0" * 40

AIRLOCK_HOME = os.environ.get("AIRLOCK_HOME", "/usr/local/blacklake-airlock")
CONF_PATH = os.environ.get("AIRLOCK_CONF", os.path.join(AIRLOCK_HOME, "airlock.conf.json"))

DEFAULT_CONF = {
    "gitlab_repo_url": "",          # https://gitlab.example.com/group/project.git
    "gitlab_api_base": "",          # optional override, default = scheme://host of gitlab_repo_url
    "project_path": "",             # optional override, default = path of gitlab_repo_url
    "target_branch": "main",
    "branch_prefix": "",            # chosen with the user at install time, e.g. zhangsan-cc/; empty = nothing may be pushed
    "protected_branches": ["main", "master", "develop", "release/*"],
    "mr_draft": True,
    "remove_source_branch": True,
    "allow_force": False,
    "allow_delete": False,
    "max_push_mb": 50,
    "max_file_mb": 20,
    "secret_scan": "block",         # block | warn | off
    "ssl_verify": True,
    "ca_file": "",
    "http_proxy": "",               # e.g. http://127.0.0.1:1080 when the VPN client is proxy-based
    "data_dir": "/Users/airlock/airlock-data",
    "git_timeout_sec": 180,
}

SECRET_PATTERNS = [
    ("private_key", re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA |PGP |ENCRYPTED )?PRIVATE KEY-----")),
    ("gitlab_token", re.compile(r"\bglpat-[0-9A-Za-z_\-]{20,}")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}")),
]


# --------------------------------------------------------------------------
# config / paths
# --------------------------------------------------------------------------
def load_conf():
    conf = dict(DEFAULT_CONF)
    try:
        with open(CONF_PATH) as f:
            conf.update(json.load(f))
    except IOError:
        pass
    if os.environ.get("AIRLOCK_DATA"):
        conf["data_dir"] = os.environ["AIRLOCK_DATA"]
    return conf


def paths(conf):
    d = conf["data_dir"]
    return {
        "repo": os.path.join(d, "repo.git"),
        "token": os.path.join(d, "gitlab-token"),
        "state": os.path.join(d, "state.json"),
        "log": os.path.join(d, "airlock.log"),
        "lock": os.path.join(d, "airlock.lock"),
    }


def read_token(conf):
    try:
        with open(paths(conf)["token"]) as f:
            return f.read().strip()
    except IOError:
        return ""


def log_event(conf, event, **fields):
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "event": event}
    rec.update(fields)
    try:
        with open(paths(conf)["log"], "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except IOError:
        pass


def load_state(conf):
    try:
        with open(paths(conf)["state"]) as f:
            return json.load(f)
    except (IOError, ValueError):
        return {}


def save_state(conf, state):
    p = paths(conf)["state"]
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    os.rename(tmp, p)


class Lock(object):
    def __init__(self, conf):
        self.path = paths(conf)["lock"]
        self.fh = None

    def __enter__(self):
        self.fh = open(self.path, "a")
        fcntl.flock(self.fh, fcntl.LOCK_EX)
        return self

    def __exit__(self, *a):
        fcntl.flock(self.fh, fcntl.LOCK_UN)
        self.fh.close()


# --------------------------------------------------------------------------
# GitLab helpers
# --------------------------------------------------------------------------
def gitlab_parts(conf):
    """-> (base_url, project_path) from https://host[:port]/group/sub/proj.git"""
    url = conf["gitlab_repo_url"]
    u = urlparse.urlsplit(url)
    path = u.path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    base = "%s://%s" % (u.scheme, u.netloc)
    return (conf.get("gitlab_api_base") or base).rstrip("/"), (conf.get("project_path") or path)


def git_auth_env(conf):
    """Pass the token to git through GIT_CONFIG_* (never on argv / in URLs)."""
    env = dict(os.environ)
    # Never let the pushed content or a user config influence relay behaviour.
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    kv = []
    token = read_token(conf)
    if token:
        basic = base64.b64encode(("oauth2:" + token).encode()).decode()
        kv.append(("http.extraHeader", "Authorization: Basic " + basic))
    if not conf.get("ssl_verify", True):
        kv.append(("http.sslVerify", "false"))
    if conf.get("ca_file"):
        kv.append(("http.sslCAInfo", conf["ca_file"]))
    if conf.get("http_proxy"):
        kv.append(("http.proxy", conf["http_proxy"]))
    kv.append(("credential.helper", ""))
    n = int(env.get("GIT_CONFIG_COUNT", "0") or 0)
    for k, v in kv:
        env["GIT_CONFIG_KEY_%d" % n] = k
        env["GIT_CONFIG_VALUE_%d" % n] = v
        n += 1
    env["GIT_CONFIG_COUNT"] = str(n)
    return env


def ssl_context(conf):
    if not conf.get("ssl_verify", True):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    if conf.get("ca_file"):
        return ssl.create_default_context(cafile=conf["ca_file"])
    return ssl.create_default_context()


def api(conf, method, path, query=None, timeout=15):
    base, _ = gitlab_parts(conf)
    url = base + "/api/v4" + path
    if query:
        url += "?" + urlparse.urlencode(query)
    req = urlrequest.Request(url, method=method)
    req.add_header("PRIVATE-TOKEN", read_token(conf))
    proxies = {"http": conf["http_proxy"], "https": conf["http_proxy"]} if conf.get("http_proxy") else {}
    opener = urlrequest.build_opener(urlrequest.ProxyHandler(proxies),
                                     urlrequest.HTTPSHandler(context=ssl_context(conf)))
    try:
        resp = opener.open(req, timeout=timeout)
        return resp.status, json.loads(resp.read().decode("utf-8") or "null")
    except HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:500]
        return e.code, {"error": body}
    except URLError as e:
        return 0, {"error": str(e.reason)}
    except Exception as e:  # noqa
        return 0, {"error": repr(e)}


def project_id(conf):
    _, p = gitlab_parts(conf)
    return urlparse.quote(p, safe="")


def classify(text):
    """Map git/curl error text to a stable error code the Agent can act on.

    Patterns are deliberately specific: branch names and SHAs appear in the
    same text, so bare words such as "timeout" or "403" must not be matched.
    """
    t = (text or "").lower()
    m = re.search(r"returned error: (\d{3})", t) or re.search(r"\bhttp (\d{3})\b", t)
    http = m.group(1) if m else None
    rules = [
        ("E_GITLAB_DNS", [r"could not resolve host", r"nodename nor servname", r"name or service not known",
                          r"temporary failure in name resolution"]),
        ("E_GITLAB_TLS", [r"ssl certificate problem", r"certificate verify failed", r"self[- ]signed certificate",
                          r"unable to get local issuer", r"server certificate verification failed"]),
        ("E_GITLAB_UNREACHABLE", [r"(connection|operation) timed out", r"connection refused", r"network is unreachable",
                                  r"no route to host", r"failed to connect to", r"connection reset"]),
        ("E_GITLAB_AUTH", [r"http basic: access denied", r"authentication failed for", r"invalid username or password"]),
        ("E_GITLAB_PROTECTED", [r"protected branch", r"pre-receive hook declined", r"push rule"]),
        ("E_GITLAB_FORBIDDEN", [r"you are not allowed to push", r"not allowed to push code", r"you are not allowed"]),
        ("E_GITLAB_NOT_FOUND", [r"repository not found", r"could not be found", r"does not appear to be a git repository",
                                r"project you were looking for could not be found"]),
        ("E_UPSTREAM_DIVERGED", [r"non-fast-forward", r"\(fetch first\)", r"stale info", r"\[rejected\]"]),
    ]
    for code, pats in rules:
        for pat in pats:
            if re.search(pat, t):
                return code
    if http == "401":
        return "E_GITLAB_AUTH"
    if http == "403":
        return "E_GITLAB_FORBIDDEN"
    if http == "404":
        return "E_GITLAB_NOT_FOUND"
    if http and http.startswith("5"):
        return "E_GITLAB_SERVER"
    return "E_UNKNOWN"


def run(cmd, env=None, cwd=None, inp=None, timeout=None):
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE if inp is not None else None,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=cwd)
    try:
        out, err = p.communicate(inp.encode() if inp is not None else None, timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill()
        out, err = p.communicate()
        return 124, out.decode("utf-8", "replace"), err.decode("utf-8", "replace") + "\ntimeout"
    return p.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


def git(conf, args, env=None, inp=None, timeout=None):
    return run(["git", "--git-dir", paths(conf)["repo"]] + args, env=env, inp=inp, timeout=timeout)


# --------------------------------------------------------------------------
# sync: GitLab -> airlock
# --------------------------------------------------------------------------
def do_sync(conf, quiet=False):
    t0 = time.time()
    with Lock(conf):
        rc, out, err = git(conf, ["fetch", "--prune", "--no-tags", conf["gitlab_repo_url"],
                                  "+refs/heads/*:refs/heads/*"],
                           env=git_auth_env(conf), timeout=conf["git_timeout_sec"])
        # keep HEAD pointing at the target branch so clones check it out
        git(conf, ["symbolic-ref", "HEAD", "refs/heads/" + conf["target_branch"]])
    res = {"ok": rc == 0, "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
           "duration_ms": int((time.time() - t0) * 1000)}
    if rc != 0:
        res["error_code"] = classify(err)
        res["error"] = scrub(err.strip()[-800:], conf)
    state = load_state(conf)
    state["last_sync"] = res
    if rc == 0:
        state["last_sync_ok_at"] = res["at"]
    save_state(conf, state)
    log_event(conf, "sync", **res)
    return res


def scrub(text, conf):
    tok = read_token(conf)
    if tok:
        text = text.replace(tok, "***")
    return re.sub(r"Authorization: Basic [A-Za-z0-9+/=]+", "Authorization: ***", text)


# --------------------------------------------------------------------------
# pre-receive: validate, relay, create MR
# --------------------------------------------------------------------------
def fnmatch_any(name, patterns):
    import fnmatch
    return any(fnmatch.fnmatchcase(name, p) for p in patterns)


def new_commits(conf, new):
    rc, out, _ = git(conf, ["rev-list", new, "--not", "--all"])
    return [c for c in out.split() if c] if rc == 0 else []


def push_size(conf, new):
    rc, out, _ = git(conf, ["rev-list", "--objects", new, "--not", "--all"])
    if rc != 0:
        return 0, 0, None
    objs = "\n".join(line.split(" ", 1)[0] for line in out.splitlines() if line.strip())
    if not objs:
        return 0, 0, None
    rc, out2, _ = git(conf, ["cat-file", "--batch-check=%(objecttype) %(objectsize) %(objectname)"], inp=objs + "\n")
    total, biggest, biggest_name = 0, 0, None
    names = {}
    for line in out.splitlines():
        parts = line.split(" ", 1)
        if len(parts) == 2:
            names[parts[0]] = parts[1]
    for line in out2.splitlines():
        parts = line.split()
        if len(parts) != 3:
            continue
        typ, size, oid = parts[0], int(parts[1]), parts[2]
        total += size
        if typ == "blob" and size > biggest:
            biggest, biggest_name = size, names.get(oid, oid)
    return total, biggest, biggest_name


def secret_findings(conf, commits):
    findings = []
    token = read_token(conf)
    for c in commits[:200]:
        rc, out, _ = git(conf, ["show", "--format=", "--unified=0", "--no-color", "--no-ext-diff", c])
        if rc != 0:
            continue
        cur_file = None
        for line in out.splitlines():
            if line.startswith("+++ b/"):
                cur_file = line[6:]
                continue
            if not line.startswith("+") or line.startswith("+++"):
                continue
            if token and token in line:
                findings.append({"commit": c[:10], "file": cur_file, "kind": "airlock_gitlab_token"})
                continue
            for kind, rx in SECRET_PATTERNS:
                if rx.search(line):
                    findings.append({"commit": c[:10], "file": cur_file, "kind": kind})
                    break
    return findings


def push_options():
    opts = {}
    n = int(os.environ.get("GIT_PUSH_OPTION_COUNT", "0") or 0)
    for i in range(n):
        v = os.environ.get("GIT_PUSH_OPTION_%d" % i, "")
        if "=" in v:
            k, val = v.split("=", 1)
            opts[k.strip()] = val
        else:
            opts[v.strip()] = "1"
    return opts


def say(msg):
    sys.stderr.write(msg.rstrip("\n") + "\n")
    sys.stderr.flush()


def reject(code, msg, hint=None):
    say("AIRLOCK REJECT code=%s" % code)
    say("AIRLOCK REASON %s" % msg)
    if hint:
        say("AIRLOCK HINT %s" % hint)
    return 1


def remote_branch_exists(conf, branch):
    rc, out, err = run(["git", "ls-remote", "--heads", conf["gitlab_repo_url"], "refs/heads/" + branch],
                       env=git_auth_env(conf), timeout=60)
    if rc != 0:
        return None, err
    return bool(out.strip()), ""


def commit_subject(conf, sha):
    rc, out, _ = git(conf, ["log", "-1", "--format=%s", sha])
    return out.strip() if rc == 0 else ""


def validate_ref(conf, old, new, ref):
    """Return (code, reason, hint) for a rejected ref, or None if acceptable."""
    if not ref.startswith("refs/heads/"):
        return ("E_POLICY_REF", "only branches can be pushed (got %s)" % ref,
                "push a branch named %s<topic>" % conf["branch_prefix"])
    branch = ref[len("refs/heads/"):]
    if not conf.get("branch_prefix"):
        return ("E_POLICY_PREFIX", "no branch prefix is configured on the airlock, so no branch may be pushed",
                "on the Mac: sudo bash blacklake-airlock-installer.sh (it asks for the prefix agreed with the user)")
    if branch == conf["target_branch"] or fnmatch_any(branch, conf["protected_branches"]):
        return ("E_POLICY_PROTECTED", "branch %s is protected; the Agent never writes to it" % branch,
                "create %s<topic> from origin/%s and push that" % (conf["branch_prefix"], conf["target_branch"]))
    if not branch.startswith(conf["branch_prefix"]):
        return ("E_POLICY_PREFIX", "branch must start with %s (got %s)" % (conf["branch_prefix"], branch),
                "git branch -m %s%s" % (conf["branch_prefix"], branch.split("/")[-1]))
    rc, _, _ = run(["git", "check-ref-format", ref])
    if rc != 0 or len(branch) > 200:
        return ("E_POLICY_NAME", "invalid branch name %s" % branch, "use [a-z0-9._-/] only")
    if new == ZERO:
        if not conf["allow_delete"]:
            return ("E_POLICY_DELETE", "deleting branches is disabled",
                    "leave the branch; GitLab removes it after merge")
        return None
    if old != ZERO:
        rc, _, _ = git(conf, ["merge-base", "--is-ancestor", old, new])
        if rc != 0 and not conf["allow_force"]:
            return ("E_POLICY_FORCE", "non-fast-forward (force) pushes are disabled",
                    "bag.sh sync && git rebase origin/%s is not allowed for pushed branches; "
                    "use git merge origin/%s or push a new branch" % (conf["target_branch"], conf["target_branch"]))
    total, biggest, biggest_name = push_size(conf, new)
    if total > conf["max_push_mb"] * 1024 * 1024:
        return ("E_POLICY_SIZE", "push adds %.1f MB (> %s MB)" % (total / 1048576.0, conf["max_push_mb"]),
                "remove build artifacts / large binaries from the commits")
    if biggest > conf["max_file_mb"] * 1024 * 1024:
        return ("E_POLICY_FILE_SIZE", "file %s is %.1f MB (> %s MB)" % (biggest_name, biggest / 1048576.0,
                                                                         conf["max_file_mb"]),
                "remove it from history (git reset / commit --amend) and add it to .gitignore")
    if conf["secret_scan"] != "off":
        found = secret_findings(conf, new_commits(conf, new))
        if found:
            desc = "; ".join("%s in %s@%s" % (f["kind"], f["file"], f["commit"]) for f in found[:5])
            if conf["secret_scan"] == "block":
                return ("E_POLICY_SECRET", "possible secret: " + desc,
                        "remove the secret from every commit (rewrite local history before first push)")
            say("AIRLOCK WARN possible secret: " + desc)
    return None


def relay(conf, old, new, branch, opts):
    exists, err = remote_branch_exists(conf, branch)
    if exists is None:
        return {"ok": False, "code": classify(err), "error": scrub(err.strip()[-600:], conf)}
    cmd = ["git", "--git-dir", paths(conf)["repo"], "push", "--porcelain", conf["gitlab_repo_url"]]
    if new == ZERO:
        cmd.append(":refs/heads/" + branch)
    else:
        spec = "%s:refs/heads/%s" % (new, branch)
        if old != ZERO and conf["allow_force"]:
            spec = "+" + spec
        cmd.append(spec)
        if not exists:
            title = opts.get("mr.title") or commit_subject(conf, new) or branch
            draft = conf["mr_draft"] and opts.get("mr.ready") != "1" or opts.get("mr.draft") == "1"
            if draft and not re.match(r"(?i)^(draft:|\[draft\]|wip:)", title):
                title = "Draft: " + title
            desc = opts.get("mr.description", "")
            # git push options cannot contain newlines; keep it one line.
            desc = (re.sub(r"\s*[\r\n]+\s*", " ", desc).strip() + " " if desc else "") + \
                "(Pushed by an Agent through the blacklake-auto-git airlock.)"
            mr_opts = ["merge_request.create", "merge_request.target=" + conf["target_branch"],
                       "merge_request.title=" + title, "merge_request.description=" + desc]
            if conf["remove_source_branch"]:
                mr_opts.append("merge_request.remove_source_branch")
            for o in mr_opts:
                cmd += ["-o", o]
    env = git_auth_env(conf)
    # We run inside the receive quarantine: keep GIT_OBJECT_DIRECTORY so the new
    # objects are visible to this push, but do not leak the quarantine marker
    # (it would make a local receiving repo refuse ref updates).
    env.pop("GIT_QUARANTINE_PATH", None)
    rc, out, err = run(cmd, env=env, timeout=conf["git_timeout_sec"])
    text = out + "\n" + err
    mr = None
    m = re.findall(r"(https?://\S+/merge_requests/\d+)", text)
    if m:
        mr = m[-1]
    res = {"ok": rc == 0, "created_branch": exists is False, "mr_url": mr}
    if rc != 0:
        res["code"] = classify(text)
        res["error"] = scrub(text.strip()[-800:], conf)
    return res


def lookup_mr_url(conf, branch):
    code, data = api(conf, "GET", "/projects/%s/merge_requests" % project_id(conf),
                     {"source_branch": branch, "state": "opened", "per_page": 1})
    if code == 200 and data:
        return data[0].get("web_url")
    return None


def cmd_pre_receive(conf):
    opts = push_options()
    lines = [l.split() for l in sys.stdin.read().splitlines() if l.strip()]
    if not lines:
        return 0
    for old, new, ref in lines:
        bad = validate_ref(conf, old, new, ref)
        if bad:
            log_event(conf, "reject", ref=ref, code=bad[0], reason=bad[1])
            return reject(*bad)
    results = []
    with Lock(conf):
        for old, new, ref in lines:
            branch = ref[len("refs/heads/"):]
            say("AIRLOCK relaying %s -> GitLab ..." % branch)
            res = relay(conf, old, new, branch, opts)
            if not res["ok"]:
                log_event(conf, "relay_failed", branch=branch, **res)
                hint = {
                    "E_UPSTREAM_DIVERGED": "the branch changed on GitLab (e.g. web edit). Run: bag.sh sync, "
                                           "then git pull --no-rebase origin %s, then push again" % branch,
                    "E_GITLAB_DNS": "Mac cannot resolve GitLab: company VPN on the Mac is probably disconnected",
                    "E_GITLAB_UNREACHABLE": "Mac cannot reach GitLab: check the Mac's VPN",
                    "E_GITLAB_AUTH": "GitLab token on the Mac is invalid/expired: the airlock admin must rotate it on the Mac (re-run the installer with --rotate-token)",
                    "E_GITLAB_FORBIDDEN": "token lacks write_repository or the role cannot push",
                    "E_GITLAB_PROTECTED": "GitLab-side branch protection/push rule refused the branch",
                    "E_GITLAB_TLS": "TLS problem talking to GitLab: see troubleshooting E_GITLAB_TLS",
                }.get(res.get("code"), "see AIRLOCK DETAIL; run `bag.sh doctor`")
                say("AIRLOCK DETAIL " + (res.get("error") or "").replace("\n", " | ")[:700])
                return reject(res.get("code", "E_UNKNOWN"), "relay to GitLab failed for %s" % branch, hint)
            if not res.get("mr_url") and new != ZERO:
                res["mr_url"] = lookup_mr_url(conf, branch)
            results.append((branch, res))
            log_event(conf, "relayed", branch=branch, new=new, **res)
    state = load_state(conf)
    for branch, res in results:
        state.setdefault("branches", {})[branch] = {"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                                                    "mr_url": res.get("mr_url")}
        say("AIRLOCK OK branch=%s mr=%s" % (branch, res.get("mr_url") or "unknown"))
    save_state(conf, state)
    return 0


# --------------------------------------------------------------------------
# read-only queries exposed through the gate
# --------------------------------------------------------------------------
def mr_for_branch(conf, branch):
    code, data = api(conf, "GET", "/projects/%s/merge_requests" % project_id(conf),
                     {"source_branch": branch, "state": "all", "order_by": "updated_at", "per_page": 1})
    if code != 200:
        return {"ok": False, "code": "E_GITLAB_API_%s" % code, "error": data}
    if not data:
        return {"ok": True, "found": False, "branch": branch}
    iid = data[0]["iid"]
    code, mr = api(conf, "GET", "/projects/%s/merge_requests/%s" % (project_id(conf), iid))
    if code != 200:
        mr = data[0]
    pipe = mr.get("head_pipeline") or {}
    return {
        "ok": True, "found": True, "branch": branch, "iid": iid, "web_url": mr.get("web_url"),
        "title": mr.get("title"), "state": mr.get("state"),
        "draft": mr.get("draft", mr.get("work_in_progress")),
        "merge_status": mr.get("detailed_merge_status") or mr.get("merge_status"),
        "has_conflicts": mr.get("has_conflicts"), "target_branch": mr.get("target_branch"),
        "pipeline": pipe.get("status"), "pipeline_url": pipe.get("web_url"),
        "user_notes_count": mr.get("user_notes_count"), "updated_at": mr.get("updated_at"),
        "merged_at": mr.get("merged_at"),
    }


def notes_for_branch(conf, branch):
    info = mr_for_branch(conf, branch)
    if not info.get("found"):
        return info
    code, data = api(conf, "GET", "/projects/%s/merge_requests/%s/discussions" % (project_id(conf), info["iid"]),
                     {"per_page": 100})
    if code != 200:
        return {"ok": False, "code": "E_GITLAB_API_%s" % code, "error": data}
    out = []
    for d in data:
        for n in d.get("notes", []):
            if n.get("system"):
                continue
            pos = n.get("position") or {}
            out.append({
                "discussion_id": d.get("id"), "author": (n.get("author") or {}).get("username"),
                "created_at": n.get("created_at"), "body": n.get("body"),
                "resolvable": n.get("resolvable"), "resolved": n.get("resolved"),
                "file": pos.get("new_path") or pos.get("old_path"), "line": pos.get("new_line") or pos.get("old_line"),
            })
    return {"ok": True, "branch": branch, "mr": info["web_url"], "state": info["state"], "notes": out}


def token_info(conf):
    if not read_token(conf):
        return {"valid": False, "code": "E_TOKEN_MISSING"}
    code, data = api(conf, "GET", "/personal_access_tokens/self")
    if code == 200:
        return {"valid": bool(data.get("active", True)) and not data.get("revoked"),
                "expires_at": data.get("expires_at"), "scopes": data.get("scopes")}
    code2, data2 = api(conf, "GET", "/projects/%s" % project_id(conf))
    if code2 == 200:
        return {"valid": True, "expires_at": None, "scopes": None, "note": "token self-info unavailable"}
    if code2 in (401,):
        return {"valid": False, "code": "E_GITLAB_AUTH"}
    if code2 == 404:
        return {"valid": False, "code": "E_GITLAB_NOT_FOUND"}
    if code2 == 0:
        return {"valid": None, "code": classify(str(data2.get("error"))), "error": data2.get("error")}
    return {"valid": None, "code": "E_GITLAB_API_%s" % code2}


def status(conf, deep=True):
    p = paths(conf)
    st = load_state(conf)
    rep = {
        "ok": True, "version": VERSION, "host": os.uname()[1],
        "config": {k: conf[k] for k in ("gitlab_repo_url", "target_branch", "branch_prefix", "mr_draft",
                                        "allow_force", "allow_delete", "max_push_mb", "max_file_mb",
                                        "secret_scan", "ssl_verify")},
        "repo": {"exists": os.path.isdir(p["repo"])},
        "last_sync": st.get("last_sync"), "last_sync_ok_at": st.get("last_sync_ok_at"),
        "problems": [],
    }
    if rep["repo"]["exists"]:
        rc, out, _ = git(conf, ["for-each-ref", "--format=%(refname:short)", "refs/heads/"])
        rep["repo"]["branches"] = len(out.split())
        rc, out, _ = git(conf, ["rev-parse", "refs/heads/" + conf["target_branch"]])
        rep["repo"]["target_head"] = out.strip()[:12] if rc == 0 else None
        if rc != 0:
            rep["problems"].append("E_TARGET_MISSING")
    else:
        rep["problems"].append("E_REPO_MISSING")
    if not read_token(conf):
        rep["problems"].append("E_TOKEN_MISSING")
    if deep:
        t0 = time.time()
        rc, out, err = run(["git", "ls-remote", "--heads", conf["gitlab_repo_url"],
                            "refs/heads/" + conf["target_branch"]], env=git_auth_env(conf), timeout=25)
        rep["gitlab"] = {"reachable": rc == 0, "latency_ms": int((time.time() - t0) * 1000)}
        if rc != 0:
            rep["gitlab"]["code"] = classify(err)
            rep["gitlab"]["error"] = scrub(err.strip()[-400:], conf)
            rep["problems"].append(rep["gitlab"]["code"])
        else:
            rep["token"] = token_info(conf)
            if rep["token"].get("valid") is False:
                rep["problems"].append(rep["token"].get("code", "E_GITLAB_AUTH"))
            exp = rep["token"].get("expires_at")
            if exp:
                rep["token"]["days_left"] = days_until(exp)
                if rep["token"]["days_left"] is not None and rep["token"]["days_left"] <= 7:
                    rep["problems"].append("W_TOKEN_EXPIRING")
    ls = st.get("last_sync") or {}
    if ls and not ls.get("ok"):
        rep["problems"].append("W_LAST_SYNC_FAILED:" + str(ls.get("error_code")))
    rep["ok"] = not [x for x in rep["problems"] if x.startswith("E_")]
    return rep


def to_kv(obj, prefix=""):
    """Flatten JSON into `a.b=value` lines so shell scripts need no jq."""
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.append(to_kv(v, prefix + k + "."))
        return "".join(out)
    if isinstance(obj, list):
        if prefix == "problems.":
            return "".join("problem=%s\n" % x for x in obj)
        return "%s=%s\n" % (prefix[:-1], ",".join(str(x) for x in obj))
    if isinstance(obj, bool):
        obj = "true" if obj else "false"
    elif obj is None:
        obj = ""
    return "%s=%s\n" % (prefix[:-1], str(obj).replace("\n", " "))


def days_until(datestr):
    try:
        t = time.mktime(time.strptime(datestr[:10], "%Y-%m-%d"))
        return int((t - time.time()) // 86400) + 1
    except Exception:  # noqa
        return None


# --------------------------------------------------------------------------
# gate (ForceCommand)
# --------------------------------------------------------------------------
GATE_HELP = """blacklake-auto-git airlock %s
Allowed over ssh (anything else is denied):
  git clone/fetch/push against  repo.git
  status            health of the airlock (JSON)
  sync              fetch latest branches from GitLab now (JSON)
  mr <branch>       merge request of a branch (JSON)
  notes <branch>    review comments on that MR (JSON)
  log [n]           last n airlock events (JSON lines, default 20)
  version | help
""" % VERSION


def normalize_repo_arg(arg):
    a = arg.strip().strip("'\"")
    for pre in ("~/", "/~/", "/"):
        if a.startswith(pre):
            a = a[len(pre):]
    if a.endswith("/"):
        a = a[:-1]
    return a


def valid_branch_arg(b):
    return bool(re.match(r"^[A-Za-z0-9][A-Za-z0-9._/\-]{0,199}$", b)) and ".." not in b and "//" not in b


def cmd_gate(conf):
    raw = os.environ.get("SSH_ORIGINAL_COMMAND", "").strip()
    if not raw:
        sys.stdout.write(GATE_HELP)
        return 1
    try:
        argv = shlex.split(raw)
    except ValueError:
        say("airlock: denied (unparsable command)")
        return 2
    if argv and argv[0] == "git" and len(argv) >= 2:
        argv = ["git-" + argv[1]] + argv[2:]
    if not argv:
        return 2
    verb = argv[0]
    if verb in ("git-upload-pack", "git-receive-pack"):
        if len(argv) != 2 or normalize_repo_arg(argv[1]) not in ("repo.git", "repo"):
            say("airlock: denied (only repo.git is served)")
            log_event(conf, "gate_denied", command=raw[:200])
            return 2
        repo = paths(conf)["repo"]
        os.execvp("git", ["git", verb[4:], repo])
    if verb == "status":
        rep = status(conf, deep="--fast" not in argv)
        if "--kv" in argv:
            sys.stdout.write(to_kv(rep))
        else:
            print(json.dumps(rep, ensure_ascii=False, indent=1))
        return 0
    if verb == "sync":
        r = do_sync(conf)
        print(json.dumps(r, ensure_ascii=False))
        return 0 if r["ok"] else 1
    if verb in ("mr", "notes") and len(argv) == 2 and valid_branch_arg(argv[1]):
        r = mr_for_branch(conf, argv[1]) if verb == "mr" else notes_for_branch(conf, argv[1])
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0 if r.get("ok") else 1
    if verb == "log":
        n = 20
        if len(argv) == 2 and argv[1].isdigit():
            n = min(int(argv[1]), 500)
        try:
            with open(paths(conf)["log"]) as f:
                sys.stdout.write("".join(f.readlines()[-n:]))
        except IOError:
            pass
        return 0
    if verb == "version":
        print(VERSION)
        return 0
    if verb == "help":
        sys.stdout.write(GATE_HELP)
        return 0
    say("airlock: denied (%s)" % verb[:40])
    log_event(conf, "gate_denied", command=raw[:200])
    return 2


# --------------------------------------------------------------------------
# init / selftest (used by the installer, run as the airlock user)
# --------------------------------------------------------------------------
def cmd_init_repo(conf):
    p = paths(conf)
    if not os.path.isdir(p["repo"]):
        rc, out, err = run(["git", "init", "--bare", p["repo"]])
        if rc != 0:
            say(err)
            return 1
    hooks = os.path.join(AIRLOCK_HOME, "hooks")
    for k, v in (("core.hooksPath", hooks), ("receive.advertisePushOptions", "true"),
                 ("receive.denyDeletes", "false"), ("receive.denyNonFastForwards", "false"),
                 ("receive.fsckObjects", "true"), ("uploadpack.allowFilter", "true"),
                 ("gc.auto", "256")):
        git(conf, ["config", k, v])
    git(conf, ["symbolic-ref", "HEAD", "refs/heads/" + conf["target_branch"]])
    return 0


def cmd_selftest(conf):
    rep = {"version": VERSION, "python": sys.version.split()[0], "conf": CONF_PATH}
    rc, out, _ = run(["git", "--version"])
    rep["git"] = out.strip()
    rep["repo_exists"] = os.path.isdir(paths(conf)["repo"])
    rep["token_present"] = bool(read_token(conf))
    rep["gitlab_repo_url_set"] = bool(conf["gitlab_repo_url"])
    print(json.dumps(rep, ensure_ascii=False))
    return 0 if rep["repo_exists"] and rep["gitlab_repo_url_set"] else 1


def main(argv):
    conf = load_conf()
    if len(argv) < 2:
        sys.stdout.write(__doc__)
        return 1
    cmd = argv[1]
    if cmd == "gate":
        return cmd_gate(conf)
    if cmd == "pre-receive":
        return cmd_pre_receive(conf)
    if cmd == "sync":
        r = do_sync(conf)
        print(json.dumps(r, ensure_ascii=False))
        return 0 if r["ok"] else 1
    if cmd == "status":
        print(json.dumps(status(conf, deep="--fast" not in argv), ensure_ascii=False, indent=1))
        return 0
    if cmd == "init-repo":
        return cmd_init_repo(conf)
    if cmd == "selftest":
        return cmd_selftest(conf)
    if cmd == "version":
        print(VERSION)
        return 0
    sys.stdout.write(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
