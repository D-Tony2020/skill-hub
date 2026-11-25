#!/usr/bin/env bash
# Run every test layer that this machine can run. Usage: bash tests/run_all.sh
set -u
cd "$(dirname "$0")/.."
rc=0
echo "== lint"
if command -v shellcheck >/dev/null; then shellcheck -S warning scripts/bag.sh scripts/mac/install.sh || rc=1; else echo "shellcheck not installed, skipped"; fi
bash -n scripts/mac/install.sh || rc=1
python3 -c "import ast;ast.parse(open('scripts/mac/airlock.py').read())" || rc=1
v="$(cat VERSION)"
grep -q "^VERSION = \"$v\"" scripts/mac/airlock.py || { echo "VERSION mismatch: airlock.py vs VERSION ($v)"; rc=1; }
echo "== unit/e2e (simulated)"
python3 -W ignore -m unittest tests.test_airlock tests.test_bag || rc=1
echo "== real sshd (needs root + openssh-server; skipped otherwise)"
python3 -W ignore -m unittest tests.test_real_ssh || rc=1
echo "== installer simulation (needs BAG_ALLOW_SYSTEM_TESTS=1 in a disposable root container)"
python3 -W ignore -m unittest tests.test_installer_sim || rc=1
[ $rc -eq 0 ] && echo "ALL GREEN" || echo "FAILURES"
exit $rc
