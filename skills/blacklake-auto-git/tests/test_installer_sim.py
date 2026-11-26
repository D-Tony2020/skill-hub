# -*- coding: utf-8 -*-
"""Smoke test of the Mac installer on a disposable Linux container.

macOS-only tools (sysadminctl, dscl, launchctl, systemsetup, ...) are stubbed,
everything else is real: the installer writes /usr/local/blacklake-airlock,
/Users/airlock, /etc/ssh/sshd_config.d/100-blacklake-airlock.conf, a real sshd
is started with the system config, and bag.sh pairs, clones and pushes through
the installed policy. It MODIFIES THE SYSTEM, so it only runs when
BAG_ALLOW_SYSTEM_TESTS=1 (CI containers), as root, on Linux.
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Env, sh, BAG_SH  # noqa: E402

ENABLED = (os.environ.get("BAG_ALLOW_SYSTEM_TESTS") == "1" and os.geteuid() == 0
           and sys.platform.startswith("linux") and shutil.which("sshd"))

STUBS = {
    "uname": '#!/bin/sh\n[ "$1" = "-s" ] && { echo Darwin; exit 0; }\nexec /usr/bin/uname "$@"\n',
    "sw_vers": "#!/bin/sh\necho 14.5\n",
    "xcode-select": "#!/bin/sh\necho /Library/Developer/CommandLineTools\n",
    "sysadminctl": '#!/bin/sh\n[ "$1" = "-deleteUser" ] && { userdel airlock 2>/dev/null; exit 0; }\nid airlock >/dev/null 2>&1 || useradd -m -d /Users/airlock -s /bin/sh airlock; usermod -p "*" airlock\n',
    "createhomedir": "#!/bin/sh\nexit 0\n",
    "dscl": "#!/bin/sh\nexit 0\n",
    "dseditgroup": '#!/bin/sh\n[ "$2" = "read" ] && exit 1\nexit 0\n',
    "systemsetup": '#!/bin/sh\necho "Remote Login: On"\n',
    "launchctl": "#!/bin/sh\nexit 0\n",
    "scutil": "#!/bin/sh\necho testmac\n",
    "ipconfig": "#!/bin/sh\necho 127.0.0.1\n",
    "pmset": "#!/bin/sh\nexit 0\n",
    "nc": '#!/bin/sh\nshift 3\nexec /usr/bin/nc -z -w 2 "$@"\n',
}


@unittest.skipUnless(ENABLED, "set BAG_ALLOW_SYSTEM_TESTS=1 in a disposable root Linux container")
class InstallerSimTest(unittest.TestCase):
    def test_install_pair_push_check_uninstall(self):
        # start from a clean slate (previous runs / other tests may have left an airlock user)
        sh("userdel -r airlock 2>/dev/null; rm -rf /Users/airlock /usr/local/blacklake-airlock "
           "/etc/ssh/sshd_config.d/100-blacklake-airlock.conf", check=False)
        e = Env()
        try:
            stub = os.path.join(e.root, "stubs")
            os.makedirs(stub)
            for n, body in STUBS.items():
                open(os.path.join(stub, n), "w").write(body)
                os.chmod(os.path.join(stub, n), 0o755)
            sh("getent group wheel || groupadd wheel")
            if not os.path.isdir("/Users"):
                os.makedirs("/Users")
            bag_home = os.path.join(e.root, "baghome")
            env = dict(e.env, BAG_HOME=bag_home, HOME=e.winhome)
            env.pop("GIT_SSH_COMMAND", None)
            sh(["bash", BAG_SH, "init"], env=env)
            sh(["bash", BAG_SH, "bundle", "--gitlab-url", "https://gitlab.invalid/grp/proj.git"], env=env)
            inst = os.path.join(bag_home, "bundle", "blacklake-airlock-installer.sh")
            ienv = dict(os.environ, PATH=stub + ":" + os.environ["PATH"])
            p = subprocess.run(["bash", inst, "--yes"], input="glpat-TESTTOKENtesttoken1234\n", env=ienv,
                               capture_output=True, text=True, timeout=300)
            out = p.stdout + p.stderr
            self.assertEqual(p.returncode, 0, out)
            for must in ("created hidden user airlock", "token stored", "authorized agent key",
                         "sshd policy installed", "launchd job", "BAG-PAIR v=1.1.0 host=testmac.local ip=127.0.0.1"):
                self.assertIn(must, out)
            self.assertIn("first sync failed", out)  # gitlab.invalid is unreachable, handled gracefully
            # file modes / ownership
            self.assertEqual(oct(os.stat("/Users/airlock/airlock-data/gitlab-token").st_mode & 0o777), "0o600")
            self.assertEqual(os.stat("/usr/local/blacklake-airlock/airlock.py").st_uid, 0)
            ak = open("/Users/airlock/.ssh/authorized_keys").read()
            self.assertTrue(ak.startswith('restrict,command="/usr/bin/python3 /usr/local/blacklake-airlock/airlock.py gate" ssh-ed25519 '))
            # re-run is idempotent (no duplicate key, token kept)
            p2 = subprocess.run(["bash", inst, "--yes"], input="", env=ienv, capture_output=True, text=True, timeout=300)
            self.assertEqual(p2.returncode, 0, p2.stdout + p2.stderr)
            self.assertIn("GitLab token present", p2.stdout)
            self.assertEqual(open("/Users/airlock/.ssh/authorized_keys").read().count("ssh-ed25519"), 1)
            # point the installed airlock at the fake GitLab, then use it through real sshd
            conf = json.load(open("/usr/local/blacklake-airlock/airlock.conf.json"))
            conf.update({"gitlab_repo_url": e.gitlab, "gitlab_api_base": json.load(open(e.conf_path))["gitlab_api_base"],
                         "project_path": "grp/proj"})
            json.dump(conf, open("/usr/local/blacklake-airlock/airlock.conf.json", "w"))
            sh(["chown", "-R", "airlock", e.gitlab, e.root])
            os.makedirs("/run/sshd", exist_ok=True)
            sshd = subprocess.Popen(["/usr/sbin/sshd", "-D", "-e", "-o", "UsePAM=no"],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(1)
            try:
                pair = [l for l in out.splitlines() if l.startswith("BAG-PAIR")][0]
                p = sh(["bash", BAG_SH, "pair", pair], env=env, check=False)
                self.assertIn("RESULT ok pair", p.stdout, p.stdout + p.stderr)
                d = os.path.join(e.winhome, "proj")
                sh(["bash", BAG_SH, "clone", d], env=env)
                sh(["bash", BAG_SH, "start", "from installer"], env=env)
                open(os.path.join(d, "i.txt"), "w").write("i\n")
                sh("git add . && git commit -qm 'installer path'", cwd=d, env=env)
                p = sh(["bash", BAG_SH, "push"], env=dict(env, FAKE_MRS=e.mrs), check=False)
                self.assertIn("RESULT ok push branch=zhangsan-cc/from-installer", p.stdout, p.stdout + p.stderr)
                p = sh(["bash", BAG_SH, "doctor"], env=env, check=False)
                self.assertIn("RESULT ok doctor", p.stdout, p.stdout)
                # the admin's own account cannot log in through this policy (password auth off for airlock only,
                # and airlock cannot get a shell)
                r = subprocess.run(["ssh", "-F", os.path.join(bag_home, "ssh_config"), "bag-airlock", "id"],
                                   capture_output=True, text=True, env=env)
                self.assertNotIn("uid=", r.stdout)
                p = subprocess.run(["bash", inst, "--check"], env=ienv, capture_output=True, text=True, timeout=120)
                self.assertIn('"version": "1.1.0"', p.stdout)
            finally:
                sshd.send_signal(signal.SIGTERM)
            p = subprocess.run(["bash", inst, "--uninstall"], input="y\n", env=ienv, capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertFalse(os.path.exists("/usr/local/blacklake-airlock"))
            self.assertFalse(os.path.exists("/etc/ssh/sshd_config.d/100-blacklake-airlock.conf"))
        finally:
            e.close()


if __name__ == "__main__":
    unittest.main()
