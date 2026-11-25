#!/bin/bash
# blacklake-auto-git — Mac airlock installer (idempotent; re-run to update).
#
# Run ON THE INTRANET MAC by a human admin:
#     sudo bash blacklake-airlock-installer.sh            # install / update
#     sudo bash blacklake-airlock-installer.sh --check    # health report only
#     sudo bash blacklake-airlock-installer.sh --rotate-token
#     sudo bash blacklake-airlock-installer.sh --add-key "ssh-ed25519 AAAA... name"
#     sudo bash blacklake-airlock-installer.sh --uninstall
#
# What it does (nothing else):
#   * creates a hidden, password-less macOS user "airlock" whose ONLY ssh
#     capability is the forced command `airlock.py gate` (git on one repo +
#     a few read-only status commands); no shell, no tty, no port forwarding
#   * stores the GitLab token readable only by that user (typed here, never
#     sent to the Agent machine)
#   * creates the airlock bare repo, a pre-receive policy hook and a launchd
#     job that fetches GitLab every 2 minutes
#   * enables Remote Login restricted to the airlock user
#
# Compatible with macOS /bin/bash 3.2. The Python payload (airlock.py) is
# appended to this file by `bag.sh bundle`; read it before running if unsure.
set -u

VERSION="__BAG_VERSION__"
DEF_GITLAB_URL="__BAG_GITLAB_URL__"
DEF_PREFIX="__BAG_PREFIX__"
DEF_TARGET="__BAG_TARGET__"
DEF_PUBKEY="__BAG_PUBKEY__"

AUSER="airlock"
AHOME_USER="/Users/$AUSER"
APP="/usr/local/blacklake-airlock"
DATA="$AHOME_USER/airlock-data"
CONF="$APP/airlock.conf.json"
PLIST="/Library/LaunchDaemons/com.blacklake.airlock.sync.plist"
DROPIN="/etc/ssh/sshd_config.d/100-blacklake-airlock.conf"
PY="/usr/bin/python3"
SELF="$0"

c_ok()   { printf '\033[32m[ OK ]\033[0m %s\n' "$*"; }
c_info() { printf '\033[36m[INFO]\033[0m %s\n' "$*"; }
c_warn() { printf '\033[33m[WARN]\033[0m %s\n' "$*"; }
c_err()  { printf '\033[31m[FAIL]\033[0m %s\n' "$*"; }
die()    { c_err "$*"; exit 1; }
as_airlock() { sudo -u "$AUSER" -H env AIRLOCK_HOME="$APP" AIRLOCK_CONF="$CONF" "$@"; }

placeholder() { case "$1" in __BAG_*__) return 0;; esac; return 1; }

# ------------------------------------------------------------------ preflight
preflight() {
  [ "$(uname -s)" = "Darwin" ] || die "This installer is for macOS only."
  [ "$(id -u)" = "0" ] || die "Run with sudo: sudo bash $SELF"
  if ! xcode-select -p >/dev/null 2>&1 || ! /usr/bin/git --version >/dev/null 2>&1; then
    c_warn "Command Line Tools (git, python3) are missing. Starting the installer..."
    xcode-select --install >/dev/null 2>&1 || true
    die "Finish the 'Command Line Tools' install dialog, then run this script again."
  fi
  "$PY" -c 'import sys; assert sys.version_info >= (3, 8)' 2>/dev/null || die "/usr/bin/python3 >= 3.8 required."
  c_ok "macOS $(sw_vers -productVersion), $(/usr/bin/git --version), python $("$PY" -c 'import platform;print(platform.python_version())')"
}

extract_payload() {
  # payload = everything between the markers at the end of this file
  awk '/^__AIRLOCK_PY_BEGIN__$/{f=1;next} /^__AIRLOCK_PY_END__$/{f=0} f' "$SELF"
}

# ------------------------------------------------------------------ user
ensure_user() {
  if id "$AUSER" >/dev/null 2>&1; then
    c_ok "user $AUSER exists"
  else
    local pw
    pw="$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 40)"
    sysadminctl -addUser "$AUSER" -fullName "Blacklake Airlock" -shell /bin/zsh \
      -home "$AHOME_USER" -password "$pw" >/dev/null 2>&1 || die "could not create user $AUSER"
    unset pw
    createhomedir -c -u "$AUSER" >/dev/null 2>&1 || true
    dscl . create "/Users/$AUSER" IsHidden 1 || true
    c_ok "created hidden user $AUSER (random password, password login disabled for ssh)"
  fi
  [ -d "$AHOME_USER" ] || { mkdir -p "$AHOME_USER"; chown "$AUSER":staff "$AHOME_USER"; }
}

# ------------------------------------------------------------------ files
write_conf() {
  local url="$1" prefix="$2" target="$3"
  mkdir -p "$APP/hooks"
  "$PY" - "$CONF" "$url" "$prefix" "$target" "$DATA" <<'PYEOF'
import json, sys
path, url, prefix, target, data = sys.argv[1:6]
try:
    conf = json.load(open(path))
except Exception:
    conf = {}
conf.update({"gitlab_repo_url": url, "branch_prefix": prefix, "target_branch": target, "data_dir": data})
prot = conf.get("protected_branches") or ["main", "master", "develop", "release/*"]
if target not in prot:
    prot.insert(0, target)
conf["protected_branches"] = prot
json.dump(conf, open(path, "w"), indent=1)
PYEOF
  chmod 644 "$CONF"
}

install_files() {
  mkdir -p "$APP/hooks"
  extract_payload > "$APP/airlock.py.new" || die "payload extraction failed"
  [ -s "$APP/airlock.py.new" ] || die "payload is empty (was this file built by bag.sh bundle?)"
  "$PY" -c "import ast,sys;ast.parse(open('$APP/airlock.py.new').read())" || die "payload is not valid python"
  mv "$APP/airlock.py.new" "$APP/airlock.py"
  cat > "$APP/hooks/pre-receive" <<EOF
#!/bin/sh
exec /usr/bin/env AIRLOCK_HOME="$APP" AIRLOCK_CONF="$CONF" $PY $APP/airlock.py pre-receive
EOF
  chown -R root:wheel "$APP"
  chmod 755 "$APP" "$APP/hooks" "$APP/hooks/pre-receive"
  chmod 644 "$APP/airlock.py"
  mkdir -p "$DATA"
  chown "$AUSER":staff "$DATA"
  chmod 700 "$DATA"
  c_ok "installed $APP (root-owned, not writable by $AUSER) and $DATA"
}

# ------------------------------------------------------------------ token
token_file() { echo "$DATA/gitlab-token"; }

prompt_token() {
  local tok=""
  echo
  echo "Paste the GitLab token for THIS ONE PROJECT (Project Access Token preferred:"
  echo "  GitLab -> project -> Settings -> Access Tokens, role Developer,"
  echo "  scopes: api + write_repository). Input is hidden; it never leaves this Mac."
  printf 'GitLab token: '
  read -r -s tok
  echo
  [ -n "$tok" ] || die "empty token"
  printf '%s\n' "$tok" > "$(token_file)"
  unset tok
  chown "$AUSER":staff "$(token_file)"
  chmod 600 "$(token_file)"
  c_ok "token stored at $(token_file) (mode 600, owner $AUSER)"
}

ensure_token() {
  if [ -s "$(token_file)" ] && [ "${ROTATE:-0}" != "1" ]; then
    c_ok "GitLab token present"
  else
    prompt_token
  fi
}

# ------------------------------------------------------------------ ssh
add_key() {
  local key="$1" ak="$AHOME_USER/.ssh/authorized_keys"
  case "$key" in ssh-ed25519\ *|ssh-rsa\ *|ecdsa-sha2-*) ;; *) die "not an ssh public key: ${key:0:30}...";; esac
  mkdir -p "$AHOME_USER/.ssh"
  touch "$ak"
  local body
  body="$(echo "$key" | awk '{print $2}')"
  if grep -q "$body" "$ak" 2>/dev/null; then
    c_ok "agent public key already authorized"
  else
    printf 'restrict,command="%s %s/airlock.py gate" %s\n' "$PY" "$APP" "$key" >> "$ak"
    c_ok "authorized agent key: $(echo "$key" | awk '{print $1, $3}')"
  fi
  chown -R "$AUSER":staff "$AHOME_USER/.ssh"
  chmod 700 "$AHOME_USER/.ssh"
  chmod 600 "$ak"
}

ensure_sshd() {
  mkdir -p /etc/ssh/sshd_config.d
  if ! grep -Eq '^[[:space:]]*Include[[:space:]]+/etc/ssh/sshd_config.d/\*' /etc/ssh/sshd_config; then
    c_warn "/etc/ssh/sshd_config has no Include for sshd_config.d; adding it at the top"
    local bak
    bak="/etc/ssh/sshd_config.bak.$(date +%s)"
    cp /etc/ssh/sshd_config "$bak"
    { echo "Include /etc/ssh/sshd_config.d/*"; cat "$bak"; } > /etc/ssh/sshd_config.tmp \
      && mv /etc/ssh/sshd_config.tmp /etc/ssh/sshd_config
  fi
  cat > "$DROPIN" <<EOF
# blacklake-auto-git airlock: the $AUSER user can only run the airlock gate.
Match User $AUSER
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
    ForceCommand $PY $APP/airlock.py gate
EOF
  chmod 644 "$DROPIN"
  if /usr/sbin/sshd -t 2>/tmp/bag-sshd-t.err; then
    c_ok "sshd policy installed ($DROPIN)"
  else
    c_err "sshd config test failed: $(cat /tmp/bag-sshd-t.err)"
    rm -f "$DROPIN"
    die "reverted $DROPIN"
  fi
  # Restrict who may use Remote Login. If the group does not exist, Remote Login
  # currently allows ALL users; creating it with only $AUSER locks everyone else out of ssh.
  if ! dseditgroup -o read com.apple.access_ssh >/dev/null 2>&1; then
    dseditgroup -o create -q com.apple.access_ssh >/dev/null 2>&1 || true
    c_info "Remote Login restricted to explicitly allowed users"
  else
    local members
    members="$(dscl . -read /Groups/com.apple.access_ssh GroupMembership 2>/dev/null | cut -d: -f2-)"
    [ -n "${members// /}" ] && c_warn "Remote Login is also allowed for:${members} (left unchanged)"
  fi
  dseditgroup -o edit -a "$AUSER" -t user com.apple.access_ssh >/dev/null 2>&1 || true
  if systemsetup -getremotelogin 2>/dev/null | grep -qi ': on'; then
    c_ok "Remote Login is on"
  else
    systemsetup -f -setremotelogin on >/dev/null 2>&1 || true
    launchctl enable system/com.openssh.sshd >/dev/null 2>&1 || true
    launchctl bootstrap system /System/Library/LaunchDaemons/ssh.plist >/dev/null 2>&1 || true
    if nc -z -G 2 127.0.0.1 22 >/dev/null 2>&1; then
      c_ok "Remote Login enabled"
    else
      c_warn "Could not enable Remote Login automatically (macOS needs Full Disk Access for that)."
      echo "      Do it once by hand: System Settings > General > Sharing > Remote Login: ON"
      echo "      ('Allow access for' may stay as it is; only '$AUSER' is in the allowed group)."
      echo "      Then run: sudo bash $SELF --check"
    fi
  fi
}

# ------------------------------------------------------------------ repo + launchd
ensure_repo() {
  as_airlock "$PY" "$APP/airlock.py" init-repo || die "init-repo failed"
  c_info "first sync from GitLab (needs the company VPN on this Mac)..."
  local out
  out="$(as_airlock "$PY" "$APP/airlock.py" sync 2>&1)"
  if echo "$out" | grep -q '"ok": true'; then
    c_ok "airlock repo synced from GitLab"
  else
    c_warn "first sync failed: $out"
    c_warn "fix the cause (VPN / token / URL), then: sudo bash $SELF --check"
  fi
}

ensure_launchd() {
  cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.blacklake.airlock.sync</string>
  <key>UserName</key><string>$AUSER</string>
  <key>ProgramArguments</key><array><string>$PY</string><string>$APP/airlock.py</string><string>sync</string></array>
  <key>EnvironmentVariables</key><dict>
    <key>AIRLOCK_HOME</key><string>$APP</string><key>AIRLOCK_CONF</key><string>$CONF</string></dict>
  <key>StartInterval</key><integer>120</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$DATA/launchd.out</string>
  <key>StandardErrorPath</key><string>$DATA/launchd.err</string>
</dict></plist>
EOF
  chown root:wheel "$PLIST"; chmod 644 "$PLIST"
  launchctl bootout system "$PLIST" >/dev/null 2>&1 || true
  launchctl bootstrap system "$PLIST" || c_warn "launchctl bootstrap failed; sync will only run on demand"
  c_ok "launchd job com.blacklake.airlock.sync (every 120s)"
}

# ------------------------------------------------------------------ report
pair_line() {
  local name ip fp ifc
  name="$(scutil --get LocalHostName 2>/dev/null).local"
  ip=""
  for ifc in en0 en1 en2 bridge100; do
    ip="$(ipconfig getifaddr "$ifc" 2>/dev/null)"; [ -n "$ip" ] && break
  done
  fp="$(ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub 2>/dev/null | awk '{print $2}')"
  echo "BAG-PAIR v=$VERSION host=$name ip=${ip:-unknown} fp=$fp user=$AUSER"
}

do_check() {
  c_info "airlock status (as $AUSER):"
  as_airlock "$PY" "$APP/airlock.py" status || true
  echo
  nc -z -G 2 127.0.0.1 22 >/dev/null 2>&1 && c_ok "sshd listening on :22" || c_err "sshd not listening (Remote Login off?)"
  launchctl print system/com.blacklake.airlock.sync >/dev/null 2>&1 && c_ok "launchd sync job loaded" || c_warn "launchd sync job not loaded"
  echo
  echo "Give this line to the Agent (paste it into the Claude Code chat):"
  echo
  pair_line
  echo
}

do_uninstall() {
  printf 'Remove the airlock user, repo, token and sshd policy? [y/N] '
  read -r a; [ "$a" = "y" ] || [ "$a" = "Y" ] || exit 0
  launchctl bootout system "$PLIST" >/dev/null 2>&1 || true
  rm -f "$PLIST" "$DROPIN"
  dseditgroup -o edit -d "$AUSER" -t user com.apple.access_ssh >/dev/null 2>&1 || true
  sysadminctl -deleteUser "$AUSER" >/dev/null 2>&1 || true
  rm -rf "$APP" "$AHOME_USER"
  c_ok "uninstalled. (Remote Login itself was left as is; turn it off in System Settings if unused.)"
}

maybe_power() {
  [ "${YES:-0}" = "1" ] && return 0
  printf 'Keep this Mac awake while on power so the Agent can reach it? (pmset -c sleep 0) [y/N] '
  read -r a
  if [ "$a" = "y" ] || [ "$a" = "Y" ]; then pmset -c sleep 0 && c_ok "sleep disabled on AC power"; fi
}

# ------------------------------------------------------------------ main
main() {
  local action="install" url="" prefix="" target="" key=""
  ROTATE=0; YES=0
  while [ $# -gt 0 ]; do
    case "$1" in
      --check) action="check";;
      --uninstall) action="uninstall";;
      --rotate-token) action="rotate";;
      --add-key) action="addkey"; key="${2:-}"; shift;;
      --gitlab-url) url="${2:-}"; shift;;
      --prefix) prefix="${2:-}"; shift;;
      --target) target="${2:-}"; shift;;
      --yes|-y) YES=1;;
      -h|--help) sed -n '2,25p' "$SELF"; exit 0;;
      *) die "unknown option $1";;
    esac
    shift
  done
  preflight
  case "$action" in
    check) do_check; exit 0;;
    uninstall) do_uninstall; exit 0;;
    rotate) ROTATE=1; ensure_token; do_check; exit 0;;
    addkey) add_key "$key"; exit 0;;
  esac

  placeholder "$DEF_GITLAB_URL" && DEF_GITLAB_URL=""
  placeholder "$DEF_PREFIX" && DEF_PREFIX="deans-cc/"
  placeholder "$DEF_TARGET" && DEF_TARGET="main"
  placeholder "$DEF_PUBKEY" && DEF_PUBKEY=""
  [ -n "$url" ] || url="$DEF_GITLAB_URL"
  if [ -z "$url" ]; then
    printf 'GitLab HTTPS clone URL of the project (https://.../group/project.git): '
    read -r url
  fi
  case "$url" in https://*|http://*) ;; *) die "need the HTTPS clone URL (got '$url')";; esac
  [ -n "$prefix" ] || prefix="$DEF_PREFIX"
  [ -n "$target" ] || target="$DEF_TARGET"
  [ -n "$DEF_PUBKEY" ] || die "no agent public key embedded; rebuild the installer with bag.sh bundle"

  c_info "installing blacklake-auto-git airlock $VERSION"
  c_info "GitLab: $url   target: $target   agent branches: ${prefix}*"
  ensure_user
  write_conf "$url" "$prefix" "$target"
  install_files
  ensure_token
  add_key "$DEF_PUBKEY"
  ensure_sshd
  ensure_repo
  ensure_launchd
  maybe_power
  echo
  c_ok "done."
  do_check
}

main "$@"
exit $?
