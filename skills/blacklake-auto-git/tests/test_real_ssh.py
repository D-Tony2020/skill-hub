# -*- coding: utf-8 -*-
"""Integration test with a REAL sshd using the same policy the Mac installer writes.

Needs root + openssh-server (Linux CI container). Verifies the security model:
the airlock user can only reach the gate (no shell, no tty, no forwarding,
no scp/sftp), and that bag.sh pair/discover/clone/push work over real ssh.
"""
import os
import pwd
import shutil
import signal
import socket
import subprocess
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Env, sh, BAG_SH  # noqa: E402

CAN_RUN = os.geteuid() == 0 and shutil.which("sshd") and shutil.which("ssh-keygen") and sys.platform.startswith("linux")


def port_free(p):
    s = socket.socket()
    try:
        s.bind(("0.0.0.0", p))
        return True
    except OSError:
        return False
    finally:
        s.close()


@unittest.skipUnless(CAN_RUN, "needs root + openssh-server on Linux")
class RealSshTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.e = e = Env()
        cls.port = 22 if port_free(22) else 2222
        try:
            pwd.getpwnam("airlock")
        except KeyError:
            sh(["useradd", "-m", "-s", "/bin/sh", "airlock"])
        sh(["passwd", "-d", "airlock"], check=False)
        # airlock user must own the data dir and be able to read the code
        for path in (e.root,):
            os.chmod(path, 0o755)
        sh(["chown", "-R", "airlock", e.data, e.gitlab])
        sh(["chmod", "-R", "a+rX", e.home])
        cls.hostkey = os.path.join(e.root, "ssh_host_ed25519_key")
        sh(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", cls.hostkey])
        os.chmod(cls.hostkey, 0o600)
        gate = "/usr/bin/env AIRLOCK_HOME=%s AIRLOCK_CONF=%s %s %s/airlock.py gate" % (
            e.home, e.conf_path, sys.executable, e.home)
        # hook shim must also see the env (installer bakes it into the shim)
        open(os.path.join(e.home, "hooks", "pre-receive"), "w").write(
            '#!/bin/sh\nexec /usr/bin/env AIRLOCK_HOME=%s AIRLOCK_CONF=%s FAKE_MRS=%s %s %s/airlock.py pre-receive\n'
            % (e.home, e.conf_path, e.mrs, sys.executable, e.home))
        cls.bag_home = os.path.join(e.root, "baghome")
        cls.env = dict(e.env, BAG_HOME=cls.bag_home, HOME=e.winhome)
        cls.env.pop("GIT_SSH_COMMAND", None)
        cls.env.pop("BAG_SSH", None)
        p = sh(["bash", BAG_SH, "init"], env=cls.env)
        pub = open(os.path.join(cls.bag_home, "id_ed25519.pub")).read().strip()
        sshdir = os.path.expanduser("~airlock/.ssh")
        os.makedirs(sshdir, exist_ok=True)
        open(os.path.join(sshdir, "authorized_keys"), "w").write('restrict,command="%s" %s\n' % (gate, pub))
        sh(["chown", "-R", "airlock", sshdir])
        os.chmod(sshdir, 0o700)
        os.chmod(os.path.join(sshdir, "authorized_keys"), 0o600)
        cfg = os.path.join(e.root, "sshd_config")
        open(cfg, "w").write("""Port {port}
HostKey {hk}
PidFile {root}/sshd.pid
UsePAM no
PermitRootLogin no
AllowUsers airlock
Match User airlock
    PasswordAuthentication no
    KbdInteractiveAuthentication no
    PubkeyAuthentication yes
    AuthenticationMethods publickey
    PermitTTY no
    AllowTcpForwarding no
    AllowStreamLocalForwarding no
    AllowAgentForwarding no
    X11Forwarding no
    PermitTunnel no
    PermitUserRC no
    ForceCommand {gate}
""".format(port=cls.port, hk=cls.hostkey, root=e.root, gate=gate))
        os.makedirs("/run/sshd", exist_ok=True)
        sh(["/usr/sbin/sshd", "-t", "-f", cfg])
        cls.sshd = subprocess.Popen(["/usr/sbin/sshd", "-D", "-e", "-f", cfg],
                                    stdout=subprocess.DEVNULL, stderr=open(os.path.join(e.root, "sshd.log"), "w"))
        time.sleep(1)
        fp = sh(["ssh-keygen", "-lf", cls.hostkey + ".pub"]).stdout.split()[1]
        cls.fp = fp
        host = "127.0.0.1" if cls.port == 22 else "127.0.0.1"
        cls.pair = "BAG-PAIR v=1.0.0 host=nonexistent-mac.local ip=%s fp=%s user=airlock" % (host, fp)

    @classmethod
    def tearDownClass(cls):
        cls.sshd.send_signal(signal.SIGTERM)
        cls.e.close()

    def bag(self, *args, check=True):
        p = subprocess.run(["bash", BAG_SH] + list(args), env=self.env, capture_output=True, text=True, timeout=600)
        if check and p.returncode != 0:
            raise AssertionError("bag %s failed:\n%s\n%s" % (args, p.stdout, p.stderr))
        return p

    def ssh(self, *args):
        return subprocess.run(["ssh", "-F", os.path.join(self.bag_home, "ssh_config")] + list(args),
                              env=self.env, capture_output=True, text=True, timeout=60)

    def test_1_pair_clone_push(self):
        if self.port != 22:
            # pair uses port 22; point the alias at the custom port afterwards
            self.skipTest("port 22 busy")
        p = self.bag("pair", self.pair)
        self.assertIn("RESULT ok pair host=127.0.0.1", p.stdout)
        d = os.path.join(self.e.winhome, "w", "proj")
        self.bag("clone", d)
        self.bag("start", "real ssh")
        open(os.path.join(d, "r.txt"), "w").write("r\n")
        sh("git add . && git commit -qm 'real ssh change'", cwd=d, env=self.env)
        p = self.bag("push")
        self.assertIn("RESULT ok push branch=deans-cc/real-ssh mr=https://gitlab.test", p.stdout)
        self.assertEqual(self.e.gitlab_ref("deans-cc/real-ssh"),
                         sh(["git", "rev-parse", "HEAD"], cwd=d).stdout.strip())
        p = self.bag("doctor")
        self.assertIn("RESULT ok doctor", p.stdout)

    def test_2_security_model(self):
        if not os.path.exists(os.path.join(self.bag_home, "ssh_config")):
            self.skipTest("needs pairing")
        # no shell
        r = self.ssh("bag-airlock", "id")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("uid=", r.stdout)
        r = self.ssh("bag-airlock", "/bin/sh", "-c", "id")
        self.assertNotIn("uid=", r.stdout)
        # interactive login just prints help
        r = self.ssh("-T", "bag-airlock")
        self.assertIn("Allowed over ssh", r.stdout)
        # tty refused
        r = self.ssh("-tt", "bag-airlock", "help")
        self.assertNotIn("uid=", r.stdout)
        # port forwarding refused: the local listener opens, but the server refuses the channel
        fwd = subprocess.Popen(["ssh", "-F", os.path.join(self.bag_home, "ssh_config"), "-N",
                                "-L", "18022:127.0.0.1:22", "bag-airlock"], env=self.env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        time.sleep(1.5)
        banner = b""
        try:
            s = socket.create_connection(("127.0.0.1", 18022), timeout=3)
            s.settimeout(3)
            try:
                banner = s.recv(64)
            except OSError:
                pass
            s.close()
        except OSError:
            pass
        fwd.terminate()
        self.assertNotIn(b"SSH-", banner)
        # sftp / scp refused
        r = subprocess.run(["sftp", "-F", os.path.join(self.bag_home, "ssh_config"), "-b", "-", "bag-airlock"],
                           input="ls\n", env=self.env, capture_output=True, text=True, timeout=60)
        self.assertNotEqual(r.returncode, 0)
        r = subprocess.run(["scp", "-F", os.path.join(self.bag_home, "ssh_config"), "bag-airlock:/etc/passwd",
                            os.path.join(self.e.root, "x")], env=self.env, capture_output=True, text=True, timeout=60)
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(self.e.root, "x")))
        # other repo paths refused
        r = subprocess.run(["git", "ls-remote", "bag-airlock:/etc"], env=dict(
            self.env, GIT_SSH_COMMAND='ssh -F "%s"' % os.path.join(self.bag_home, "ssh_config")),
            capture_output=True, text=True, timeout=60)
        self.assertNotEqual(r.returncode, 0)

    def test_3_rediscover_after_ip_change(self):
        if not os.path.exists(os.path.join(self.bag_home, "ssh_config")):
            self.skipTest("needs pairing")
        # simulate the hotspot handing the Mac a new address: stale HostName
        cfg = os.path.join(self.bag_home, "ssh_config")
        s = open(cfg).read().replace("HostName 127.0.0.1", "HostName 192.0.2.254")
        open(cfg, "w").write(s)
        st = os.path.join(self.bag_home, "state.env")
        txt = open(st).read().replace("IP=127.0.0.1", "IP=192.0.2.254")
        open(st, "w").write(txt)
        p = self.bag("doctor", check=False)
        self.assertIn("airlock moved: now at", p.stdout + p.stderr)
        self.assertIn("RESULT ok doctor", p.stdout)


if __name__ == "__main__":
    unittest.main()
