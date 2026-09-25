#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH='' cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(CDPATH='' cd -- "${SCRIPT_DIR}/../.." && pwd)"

SOURCE_REF="${SROVA_ARM64_SOURCE_REF:-HEAD}"
SOURCE_COMMIT=""
VERSION="2.0-1"
ARCH="$(dpkg --print-architecture)"

WORK_ROOT="${SROVA_ARM64_WORK_ROOT:-$HOME/SROVA_PACKAGING/SROVA_ARM64/v2_0}"
PYTHON_SITE="${SROVA_ARM64_PYTHON_SITE:-}"

RUN_ID="$(date +%Y%m%d_%H%M%S)"
RUN_ROOT="${WORK_ROOT}/run_${RUN_ID}"
EXPORT_ROOT="${RUN_ROOT}/source_export"
TREE_ROOT="${RUN_ROOT}/build_deb"
ARTIFACT_ROOT="${RUN_ROOT}/artifacts"
LOG_ROOT="${RUN_ROOT}/logs"
INSPECT_ROOT="${RUN_ROOT}/inspect"

NAME="srova_${VERSION}_${ARCH}"
TREE="${TREE_ROOT}/${NAME}"
APP="${TREE}/opt/srova"
OUT="${ARTIFACT_ROOT}/${NAME}.deb"
RUST_SHA_FILE="${LOG_ROOT}/librust_audio_core.sha256"
RUST_RUNTIME_DIR_REL="src_rust/rust_audio_core/target"
RUST_RUNTIME_RELEASE_DIR_REL="${RUST_RUNTIME_DIR_REL}/release"
RUST_RUNTIME_SO_REL="${RUST_RUNTIME_RELEASE_DIR_REL}/librust_audio_core.so"

ICON_SIZES=(16 24 32 48 64 72 96 128 144 192 256 512)

err() {
  echo "ERROR: $*" >&2
  exit 1
}

is_allowed_target_dir() {
  case "$1" in
    "$APP/$RUST_RUNTIME_DIR_REL"|"$APP/$RUST_RUNTIME_RELEASE_DIR_REL")
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

validate_runtime_target_tree() {
  local root="$1"
  local runtime_target_dir="${root}/${RUST_RUNTIME_DIR_REL}"
  local runtime_release_dir="${root}/${RUST_RUNTIME_RELEASE_DIR_REL}"
  local runtime_so="${root}/${RUST_RUNTIME_SO_REL}"
  local old_runtime_so="${root}/src_rust/librust_audio_core.so"
  local entry

  [ -d "$runtime_target_dir" ] || err "missing runtime target directory: $runtime_target_dir"
  [ -d "$runtime_release_dir" ] || err "missing runtime release directory: $runtime_release_dir"
  [ -f "$runtime_so" ] || err "missing runtime Rust library: $runtime_so"
  [ ! -e "$old_runtime_so" ] || err "duplicate legacy Rust library path must be absent: $old_runtime_so"

  while IFS= read -r entry; do
    case "${entry#"$root"/}" in
      "$RUST_RUNTIME_DIR_REL"|"$RUST_RUNTIME_RELEASE_DIR_REL"|"$RUST_RUNTIME_SO_REL")
        ;;
      *)
        err "unexpected runtime target tree entry: $entry"
        ;;
    esac
  done < <(find "$runtime_target_dir" -mindepth 0 | LC_ALL=C sort)
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || err "required command not found: $1"
}

verify_source_ref() {
  local source_version

  SOURCE_COMMIT="$(
    git -C "$REPO_ROOT" rev-parse "${SOURCE_REF}^{commit}" 2>/dev/null
  )" || err "source ref does not resolve to a commit: $SOURCE_REF"

  source_version="$(
    git -C "$REPO_ROOT" show "${SOURCE_COMMIT}:version.txt" 2>/dev/null |
      tr -d '\r\n'
  )" || err "source ref does not contain version.txt: $SOURCE_REF"

  [ "$source_version" = "$VERSION" ] || \
    err "source version is $source_version, expected $VERSION"

  echo "SOURCE_REF:      $SOURCE_REF"
  echo "SOURCE_COMMIT:   $SOURCE_COMMIT"
  echo "SOURCE_VERSION:  $source_version"
}

copy_dep() {
  local item="$1"
  if [ -e "${PYTHON_SITE}/${item}" ]; then
    cp -a "${PYTHON_SITE}/${item}" "${APP}/libs/"
  else
    echo "WARN: dependency bundle is missing ${item}" >&2
  fi
}

main() {
  require_command git
  require_command tar
  require_command rsync
  require_command cargo
  require_command dpkg-deb
  require_command file
  require_command sha256sum
  require_command apt-get
  require_command node
  require_command python3

  [ "$ARCH" = "arm64" ] || err "this V2.0 builder must run on Debian arm64, got: $ARCH"
  [ -d "$REPO_ROOT/.git" ] || err "repository root does not look like a git checkout: $REPO_ROOT"
  [ -n "$PYTHON_SITE" ] ||     err "SROVA_ARM64_PYTHON_SITE must point to the prepared dependency bundle"
  [ -d "$PYTHON_SITE" ] ||     err "missing external Python dependency bundle: $PYTHON_SITE"

  verify_source_ref

  mkdir -p "$EXPORT_ROOT" "$TREE_ROOT" "$ARTIFACT_ROOT" "$LOG_ROOT" "$INSPECT_ROOT"

  echo "=== SROVA V2.0 ARM64 Debian build ==="
  echo "REPO_ROOT:    $REPO_ROOT"
  echo "WORK_ROOT:    $WORK_ROOT"
  echo "RUN_ROOT:     $RUN_ROOT"
  echo "EXPORT_ROOT:  $EXPORT_ROOT"
  echo "TREE:         $TREE"
  echo "OUT:          $OUT"
  echo "PYTHON_SITE:  $PYTHON_SITE"
  echo "SOURCE_REF:   $SOURCE_REF"

  echo
  echo "=== Export source ref ==="
  git -C "$REPO_ROOT" archive --format=tar "$SOURCE_COMMIT" | tar -xf - -C "$EXPORT_ROOT"
  [ -f "$EXPORT_ROOT/src/main_headless.py" ] || err "tag export is missing src/main_headless.py"
  [ -f "$EXPORT_ROOT/src/ui_web/index.html" ] || err "tag export is missing src/ui_web/index.html"
  [ -f "$EXPORT_ROOT/src_rust/rust_audio_core/Cargo.toml" ] || err "tag export is missing Rust audio core manifest"

  echo
  echo "=== Build Rust audio core from tagged export ==="
  cargo build --locked --manifest-path "$EXPORT_ROOT/src_rust/rust_audio_core/Cargo.toml" --release
  local_rust_so="$EXPORT_ROOT/src_rust/rust_audio_core/target/release/librust_audio_core.so"
  [ -f "$local_rust_so" ] || err "Rust build did not produce $local_rust_so"
  file "$local_rust_so"
  case "$(file -b "$local_rust_so")" in
    *"ARM aarch64"*) ;;
    *) err "Rust audio core is not ARM aarch64: $local_rust_so" ;;
  esac
  sha256sum "$local_rust_so" | tee "$RUST_SHA_FILE"

  echo
  echo "=== Prepare fresh package tree ==="
  mkdir -p \
    "$APP/libs" \
    "$APP/src_rust" \
    "$TREE/DEBIAN" \
    "$TREE/usr/bin" \
    "$TREE/usr/lib/systemd/system" \
    "$TREE/usr/lib/srova" \
    "$TREE/etc/sudoers.d" \
    "$TREE/etc/srova" \
    "$TREE/etc/srova/network-credentials" \
    "$TREE/mnt/srova-network" \
    "$TREE/usr/share/doc/srova" \
    "$TREE/usr/share/applications" \
    "$TREE/usr/share/metainfo" \
    "$TREE/usr/share/pixmaps"

  echo
  echo "=== Copy tagged source into package tree ==="
  rsync -a \
    --exclude='OLD Backup Files/' \
    --exclude='*backup*/' \
    --exclude='*backup*' \
    --exclude='*bkup*' \
    --exclude='test*_apply_inline_backup_*/' \
    --exclude='srcOLD/' \
    --exclude='.codex/' \
    --exclude='.claude/' \
    --exclude='.git/' \
    --exclude='.pytest_cache/' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='*.pyo' \
    --exclude='*.bak' \
    --exclude='*.bak_*' \
    --exclude='*.bak-*' \
    --exclude='*.backup*' \
    --exclude='*.pre_*' \
    --exclude='*.pre-*' \
    --exclude='*.old' \
    --exclude='*.old_*' \
    --exclude='*.old-*' \
    --exclude='*.before_*' \
    --exclude='*.orig' \
    --exclude='*~' \
    --exclude='*.sqlite' \
    --exclude='*.sqlite3' \
    --exclude='*.db' \
    --exclude='*.log' \
    --exclude='.env' \
    --exclude='*.env' \
    --exclude='*.crdownload' \
    --exclude='.xdp-*' \
    --exclude='index[0-9]*.html' \
    --exclude='srova[0-9]*.css' \
    "$EXPORT_ROOT/src/" "$APP/"

  install -m 0644 "$EXPORT_ROOT/version.txt" "$APP/version.txt"

  mkdir -p "$APP/$RUST_RUNTIME_RELEASE_DIR_REL"
  install -m 0644 "$local_rust_so" "$APP/$RUST_RUNTIME_SO_REL"

  echo
  echo "=== Bundle Python deps into /opt/srova/libs ==="
  for item in \
    tidalapi ratelimit mpegdash pyaes \
    requests urllib3 certifi charset_normalizer idna \
    dateutil isodate typing_extensions.py six.py
  do
    copy_dep "$item"
  done

  find "$PYTHON_SITE" -maxdepth 1 \( \
    -iname 'tidalapi*.dist-info' \
    -o -iname 'ratelimit*.dist-info' \
    -o -iname 'mpegdash*.dist-info' \
    -o -iname 'pyaes*.dist-info' \
    -o -iname 'requests*.dist-info' \
    -o -iname 'urllib3*.dist-info' \
    -o -iname 'certifi*.dist-info' \
    -o -iname 'charset_normalizer*.dist-info' \
    -o -iname 'idna*.dist-info' \
    -o -iname 'python_dateutil*.dist-info' \
    -o -iname 'isodate*.dist-info' \
    -o -iname 'typing_extensions*.dist-info' \
    -o -iname 'six*.dist-info' \
  \) -exec cp -a {} "$APP/libs/" \;

  echo
  echo "=== Bundle helper GUI/auth deps from Debian package payloads ==="
  deb_tmp="${RUN_ROOT}/build_deps/helper_extract"
  rm -rf "$deb_tmp"
  mkdir -p "$deb_tmp/downloads" "$deb_tmp/root"
  (
    cd "$deb_tmp/downloads"
    apt-get download python3-qrcode python3-pystray python3-xlib python3-pil python3-isodate python3-six >/dev/null
    for deb in ./*.deb; do
      dpkg-deb -x "$deb" "$deb_tmp/root"
    done
  )

  dist_site="${deb_tmp}/root/usr/lib/python3/dist-packages"
  for item in qrcode pystray Xlib PIL; do
    if [ -e "${dist_site}/${item}" ]; then
      cp -a "${dist_site}/${item}" "$APP/libs/"
    elif [ -e "/usr/lib/python3/dist-packages/${item}" ]; then
      cp -a "/usr/lib/python3/dist-packages/${item}" "$APP/libs/"
    else
      echo "WARN: helper dep not found for bundle: ${item}" >&2
    fi
  done

  find "$dist_site" -maxdepth 1 \( \
    -iname 'qrcode*dist-info' \
    -o -iname 'pystray*dist-info' \
    -o -iname 'python_xlib*dist-info' \
    -o -iname 'pillow*dist-info' \
    -o -iname 'Pillow*dist-info' \
  \) -exec cp -a {} "$APP/libs/" \; 2>/dev/null || true

  echo
  echo "=== Write runtime helpers and metadata ==="
  cat > "$TREE/usr/lib/srova/srova-server" <<'EOF'
#!/bin/sh
set -eu

APP_DIR="/opt/srova"

export PYTHONDONTWRITEBYTECODE=1
export PYTHONUNBUFFERED=1
export PYTHONPATH="$APP_DIR/libs:$APP_DIR${PYTHONPATH:+:$PYTHONPATH}"

cd "$APP_DIR"
exec /usr/bin/python3 "$APP_DIR/main_headless.py" "$@"
EOF
  chmod 0755 "$TREE/usr/lib/srova/srova-server"

  install -m 0755 \
    "$EXPORT_ROOT/packaging/network/srova-network-mount-helper" \
    "$TREE/usr/lib/srova/srova-network-mount-helper"

  install -m 0755 \
    "$EXPORT_ROOT/packaging/network/srova-spotify-firewall-helper" \
    "$TREE/usr/lib/srova/srova-spotify-firewall-helper"

  install -m 0644 \
    "$EXPORT_ROOT/packaging/network/srova-network-mounts.service" \
    "$TREE/usr/lib/systemd/system/srova-network-mounts.service"

  cat > "$TREE/etc/sudoers.d/srova-network-mount" <<'EOF'
srova ALL=(root) NOPASSWD: /usr/lib/srova/srova-network-mount-helper
EOF

  cat > "$TREE/etc/sudoers.d/srova-spotify-firewall" <<'EOF'
srova ALL=(root) NOPASSWD: /usr/lib/srova/srova-spotify-firewall-helper
EOF

  chmod 0440 "$TREE/etc/sudoers.d/srova-network-mount"
  chmod 0440 "$TREE/etc/sudoers.d/srova-spotify-firewall"
  chmod 0700 "$TREE/etc/srova/network-credentials"
  chmod 0755 "$TREE/mnt/srova-network"

  cat > "$TREE/usr/bin/srova-open" <<'EOF'
#!/usr/bin/env bash
set -u

APP_NAME="SROVA"

detect_port() {
  if [ -r /var/lib/srova/srova.env ]; then
    local configured_port
    configured_port="$(
      sed -nE 's/^[[:space:]]*SROVA_PORT[[:space:]]*=[[:space:]]*([0-9]+).*$/\1/p' \
        /var/lib/srova/srova.env | tail -n1
    )"

    if [ -n "${configured_port:-}" ]; then
      echo "$configured_port"
      return
    fi
  fi

  echo 8081
}

detect_lan_ip() {
  hostname -I 2>/dev/null |
    tr ' ' '\n' |
    grep -E '^[0-9]+\.' |
    grep -v '^127\.' |
    head -n1
}

PORT="$(detect_port)"
LAN_IP="$(detect_lan_ip || true)"
LOCAL_URL="http://127.0.0.1:${PORT}"
LAN_URL=""

if [ -n "${LAN_IP:-}" ]; then
  LAN_URL="http://${LAN_IP}:${PORT}"
fi

if systemctl is-active --quiet srova.service 2>/dev/null; then
  STATUS="SROVA is running and ready to use."
else
  STATUS="SROVA is installed, but the service does not appear to be running."
fi

MSG="${STATUS}

Open SROVA in a browser at:

${LOCAL_URL}"

if [ -n "$LAN_URL" ]; then
  MSG="${MSG}

From another device on this network:

${LAN_URL}"
fi

MSG="${MSG}

Tip: SROVA starts automatically after installation and after each reboot."

if command -v zenity >/dev/null 2>&1 && [ -n "${DISPLAY:-}" ]; then
  zenity --info --title="$APP_NAME" --width=520 --text="$MSG"
elif command -v kdialog >/dev/null 2>&1 && [ -n "${DISPLAY:-}" ]; then
  kdialog --title "$APP_NAME" --msgbox "$MSG"
elif command -v xmessage >/dev/null 2>&1 && [ -n "${DISPLAY:-}" ]; then
  xmessage -center -title "$APP_NAME" "$MSG"
elif command -v notify-send >/dev/null 2>&1 && [ -n "${DISPLAY:-}" ]; then
  notify-send "$APP_NAME" "$MSG"
  printf '%s\n' "$MSG"
else
  printf '%s\n' "$MSG"
fi
EOF
  chmod 0755 "$TREE/usr/bin/srova-open"

  cat > "$TREE/usr/bin/srova" <<'EOF'
#!/usr/bin/env bash
exec /usr/bin/srova-open "$@"
EOF
  chmod 0755 "$TREE/usr/bin/srova"

  cat > "$TREE/usr/lib/systemd/system/srova.service" <<'EOF'
[Unit]
Description=SROVA Headless Music Server
After=network-online.target srova-network-mounts.service sound.target
Wants=network-online.target srova-network-mounts.service

[Service]
Type=simple
User=srova
Group=srova
SupplementaryGroups=audio
WorkingDirectory=/opt/srova
Environment=SROVA_HOST=0.0.0.0
Environment=SROVA_PORT=8081
Environment=SROVA_LOG_LEVEL=INFO
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONDONTWRITEBYTECODE=1
Environment=HOME=/var/lib/srova
Environment=XDG_DATA_HOME=/var/lib/srova/.local/share
Environment=XDG_CONFIG_HOME=/var/lib/srova/.config
Environment=XDG_CACHE_HOME=/var/cache/srova
EnvironmentFile=-/var/lib/srova/srova.env
ExecStartPre=/bin/sleep 8
ExecStartPre=/usr/lib/srova/srova-wait-dns.sh
ExecStart=/usr/lib/srova/srova-server --host ${SROVA_HOST} --port ${SROVA_PORT} --log-level ${SROVA_LOG_LEVEL}
Restart=on-failure
RestartSec=10
StateDirectory=srova
CacheDirectory=srova
RuntimeDirectory=srova
RuntimeDirectoryMode=0755
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

  cat > "$TREE/usr/lib/srova/srova-wait-dns.sh" <<'EOF'
#!/bin/sh

HOSTS="${SROVA_STARTUP_DNS_HOSTS:-api.tidal.com link.tidal.com}"
TRIES="${SROVA_STARTUP_DNS_TRIES:-30}"
SLEEP_SECS="${SROVA_STARTUP_DNS_SLEEP:-2}"

i=1
while [ "$i" -le "$TRIES" ]; do
  ok=1

  for host in $HOSTS; do
    if ! getent hosts "$host" >/dev/null 2>&1; then
      ok=0
      break
    fi
  done

  if [ "$ok" -eq 1 ]; then
    logger -t srova-wait-dns "DNS ready after attempt $i/$TRIES for: $HOSTS"
    exit 0
  fi

  logger -t srova-wait-dns "DNS not ready attempt $i/$TRIES for: $HOSTS"
  sleep "$SLEEP_SECS"
  i=$((i + 1))
done

logger -t srova-wait-dns "DNS wait timed out after $TRIES attempts; continuing SROVA startup anyway"
exit 0
EOF
  chmod 0755 "$TREE/usr/lib/srova/srova-wait-dns.sh"

  cat > "$TREE/etc/srova/srova.env.example" <<'EOF'
# SROVA service environment example
# Runtime settings are saved by SROVA under /var/lib/srova/srova.env.

SROVA_HOST=0.0.0.0
SROVA_PORT=8081
SROVA_LOG_LEVEL=INFO

# Raspberry Pi local music example:
# SROVA_LOCAL_TEST_ROOTS=/mnt/music
# SROVA_LOCAL_BROWSE_ROOTS=/mnt:/media:/srv:/DATA
EOF

  cat > "$TREE/usr/share/doc/srova/README.Debian" <<'EOF'
SROVA Debian package notes

SROVA installs as a system service:

  sudo systemctl status srova.service
  sudo systemctl restart srova.service

Default web UI:

  http://<device-ip>:8081

Optional service overrides may be placed in:

  /var/lib/srova/srova.env

Local Music roots are device-local. For Raspberry Pi systems, a common
mount is /mnt/music configured through a systemd service override or
/var/lib/srova/srova.env.
EOF

  cat > "$TREE/usr/share/applications/com.srova.player.desktop" <<'EOF'
[Desktop Entry]
Name=SROVA
Comment=SROVA headless audiophile player with bit-perfect output support.
Exec=/usr/bin/srova-open
Icon=srova
Terminal=false
Type=Application
Categories=AudioVideo;Audio;Player;Music;
StartupWMClass=SROVA
StartupNotify=false
EOF
  chmod 0644 "$TREE/usr/share/applications/com.srova.player.desktop"

  install -m 0644     "$EXPORT_ROOT/flatpak/com.srova.player.metainfo.xml"     "$TREE/usr/share/metainfo/com.srova.player.metainfo.xml"

  echo
  echo "=== Install committed SROVA desktop icons ==="
  for size in "${ICON_SIZES[@]}"; do
    icon_src="${EXPORT_ROOT}/packaging_assets/srova_desktop_icon/hicolor/${size}x${size}/apps/srova.png"
    icon_dir="${TREE}/usr/share/icons/hicolor/${size}x${size}/apps"
    [ -f "$icon_src" ] || err "missing committed icon asset: $icon_src"
    mkdir -p "$icon_dir"
    install -m 0644 "$icon_src" "${icon_dir}/srova.png"
    install -m 0644 "$icon_src" "${icon_dir}/com.srova.player.png"
  done
  install -m 0644 \
    "${EXPORT_ROOT}/packaging_assets/srova_desktop_icon/hicolor/512x512/apps/srova.png" \
    "$TREE/usr/share/pixmaps/srova.png"

  echo
  echo "=== Write Debian metadata ==="
  cat > "$TREE/DEBIAN/control" <<EOF
Package: srova
Version: $VERSION
Section: sound
Priority: optional
Architecture: arm64
Maintainer: SROVA Team <support@srova.music>
Homepage: https://srova.music/
Depends: python3, python3-gi, python3-requests, python3-numpy, python3-mutagen, python3-cairo, python3-pil, python3-charset-normalizer, python3-qrcode, python3-pystray, python3-xlib, python3-dateutil, python3-isodate, python3-six, gir1.2-glib-2.0, gir1.2-gstreamer-1.0, gir1.2-gst-plugins-base-1.0, gir1.2-gdkpixbuf-2.0, gir1.2-gtk-3.0, gir1.2-gtk-4.0, gir1.2-adw-1, gstreamer1.0-tools, gstreamer1.0-alsa, gstreamer1.0-plugins-base, gstreamer1.0-plugins-good, gstreamer1.0-plugins-bad, pipewire-bin, wireplumber, adduser, sudo, nfs-common, cifs-utils, smbclient, iproute2, liblilv-0-0, libasound2 | libasound2t64
Description: SROVA headless audiophile player with bit-perfect output support.
 SROVA is a headless audiophile player for Local Music, TIDAL, Qobuz, and Internet Radio.
EOF

  cat > "$TREE/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e

if ! getent group srova >/dev/null; then
  addgroup --system srova >/dev/null
fi

if ! getent passwd srova >/dev/null; then
  adduser --system \
    --home /var/lib/srova \
    --ingroup srova \
    --disabled-password \
    --gecos "SROVA service user" \
    srova >/dev/null
fi

if getent group audio >/dev/null; then
  usermod -aG audio srova || true
fi

mkdir -p \
  /etc/srova \
  /etc/srova/network-credentials \
  /var/lib/srova \
  /var/cache/srova \
  /mnt/srova-network

chmod 0700 /etc/srova/network-credentials
chmod 0755 /mnt/srova-network

chown -R srova:srova /var/lib/srova /var/cache/srova
chmod 0755 /var/lib/srova /var/cache/srova

if [ -d /opt/srova ]; then
  find /opt/srova -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
  find /opt/srova -type d -name 'target' ! -path '/opt/srova/src_rust/rust_audio_core/target' -prune -exec rm -rf {} + 2>/dev/null || true
  find /opt/srova -type f \( \
    -name '*.pyc' \
    -o -name '*.pyo' \
    -o -name '*.bak' \
    -o -name '*.bak_*' \
    -o -name '*.bak-*' \
    -o -name '*.backup*' \
    -o -name '*.pre_*' \
    -o -name '*.pre-*' \
    -o -name '*.old' \
    -o -name '*.old_*' \
    -o -name '*.old-*' \
    -o -name '*.before_*' \
    -o -name '*.orig' \
    -o -name '*~' \
    -o -name '*.sqlite' \
    -o -name '*.sqlite3' \
    -o -name '*.db' \
    -o -name '*.log' \
    -o -name '.env' \
    -o -name '*.env' \
    -o -name '*.crdownload' \
    -o -name '.xdp-*' \
    -o -name 'index[0-9]*.html' \
    -o -name 'srova[0-9]*.css' \
  \) -delete 2>/dev/null || true
fi

systemctl daemon-reload >/dev/null 2>&1 || true
systemctl enable srova-network-mounts.service >/dev/null 2>&1 || true
systemctl enable srova.service >/dev/null 2>&1 || true
systemctl restart srova.service >/dev/null 2>&1 || systemctl start srova.service >/dev/null 2>&1 || true

exit 0
EOF
  chmod 0755 "$TREE/DEBIAN/postinst"

  cat > "$TREE/DEBIAN/prerm" <<'EOF'
#!/bin/sh
set -e

if [ "$1" = "remove" ] || [ "$1" = "deconfigure" ]; then
  systemctl stop srova.service >/dev/null 2>&1 || true

  if [ -x /usr/lib/srova/srova-network-mount-helper ]; then
    /usr/lib/srova/srova-network-mount-helper unmount-all </dev/null || \
      echo "WARNING: one or more SROVA network mounts could not be unmounted; continuing removal." >&2
  fi
fi

exit 0
EOF
  chmod 0755 "$TREE/DEBIAN/prerm"

  cat > "$TREE/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e

if [ "$1" = "purge" ]; then
  systemctl disable srova-network-mounts.service >/dev/null 2>&1 || true
  systemctl disable srova.service >/dev/null 2>&1 || true

  rm -f /etc/srova/network-mounts.json >/dev/null 2>&1 || true
  rm -rf /etc/srova/network-credentials >/dev/null 2>&1 || true

  for managed_dir in /mnt/srova-network/nfs-* /mnt/srova-network/smb-*; do
    [ -d "$managed_dir" ] || continue
    rmdir "$managed_dir" >/dev/null 2>&1 || true
  done

  rmdir /mnt/srova-network >/dev/null 2>&1 || true
fi

systemctl daemon-reload >/dev/null 2>&1 || true
exit 0
EOF
  chmod 0755 "$TREE/DEBIAN/postrm"

  echo
  echo "=== Clean generated artifacts inside build tree ==="
  while IFS= read -r target_dir; do
    if ! is_allowed_target_dir "$target_dir"; then
      rm -rf "$target_dir"
    fi
  done < <(find "$APP" -type d -name 'target')
  find "$APP" -type d \( \
    -name '__pycache__' \
    -o -iname '*backup*' \
    -o -iname '*bkup*' \
    -o -name 'srcOLD' \
    -o -name '.codex' \
    -o -name '.claude' \
    -o -name '.git' \
    -o -name '.pytest_cache' \
  \) -prune -exec rm -rf {} +
  find "$APP" -type f \( \
    -name '*.pyc' \
    -o -name '*.pyo' \
    -o -name '*.bak' \
    -o -name '*.bak_*' \
    -o -name '*.bak-*' \
    -o -name '*.backup*' \
    -o -name '*.pre_*' \
    -o -name '*.pre-*' \
    -o -name '*.old' \
    -o -name '*.old_*' \
    -o -name '*.old-*' \
    -o -name '*.before_*' \
    -o -name '*.orig' \
    -o -name '*~' \
    -o -name '*.sqlite' \
    -o -name '*.sqlite3' \
    -o -name '*.db' \
    -o -name '*.log' \
    -o -name '.env' \
    -o -name '*.env' \
    -o -name '*.crdownload' \
    -o -name '.xdp-*' \
    -o -name 'index[0-9]*.html' \
    -o -name 'srova[0-9]*.css' \
  \) -delete

  echo
  echo "=== Pre-build validation gates ==="
  PYTHONPATH="$APP/libs:$APP" PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile \
    "$APP/main_headless.py" \
    "$APP/local_library.py" \
    "$APP/backend/tidal.py" \
    "$APP/_rust/audio.py"

  node --check "$APP/ui_web/ui.js"
  bash -n "$TREE/usr/lib/srova/srova-server"
  bash -n "$TREE/usr/bin/srova-open"
  bash -n "$TREE/usr/bin/srova"

  python3 - "$TREE/usr/share/metainfo/com.srova.player.metainfo.xml" <<'PYXML'
import sys
import xml.etree.ElementTree as ET

ET.parse(sys.argv[1])
print("AppStream XML parse: OK")
PYXML

  PYTHONPATH="$APP/libs:$APP" PYTHONDONTWRITEBYTECODE=1 python3 - <<'PY'
import importlib.util

mods = [
    "tidalapi", "ratelimit", "mpegdash", "pyaes",
    "requests", "urllib3", "certifi", "charset_normalizer", "idna",
    "dateutil", "isodate", "typing_extensions", "six",
    "qrcode", "pystray", "Xlib", "PIL",
]
missing = []
for mod in mods:
    spec = importlib.util.find_spec(mod)
    print(f"{mod}: {spec.origin if spec else 'MISSING'}")
    if spec is None:
        missing.append(mod)
if missing:
    raise SystemExit("Missing bundled/importable deps: " + ", ".join(missing))
PY

  echo
  echo "=== Clean bytecode from validation ==="
  find "$APP" -type d -name '__pycache__' -prune -exec rm -rf {} +
  find "$APP" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete

  echo
  echo "=== Required path checks ==="
  for path in \
    "$APP/main_headless.py" \
    "$APP/local_library.py" \
    "$APP/backend/tidal.py" \
    "$APP/libs/tidalapi" \
    "$APP/libs/ratelimit" \
    "$APP/$RUST_RUNTIME_DIR_REL" \
    "$APP/$RUST_RUNTIME_RELEASE_DIR_REL" \
    "$APP/$RUST_RUNTIME_SO_REL" \
    "$TREE/usr/bin/srova" \
    "$TREE/usr/bin/srova-open" \
    "$TREE/usr/lib/srova/srova-server" \
    "$TREE/usr/lib/srova/srova-network-mount-helper" \
    "$TREE/usr/lib/srova/srova-spotify-firewall-helper" \
    "$TREE/usr/lib/srova/srova-wait-dns.sh" \
    "$TREE/usr/lib/systemd/system/srova.service" \
    "$TREE/usr/lib/systemd/system/srova-network-mounts.service" \
    "$TREE/etc/sudoers.d/srova-network-mount" \
    "$TREE/etc/sudoers.d/srova-spotify-firewall" \
    "$TREE/usr/share/applications/com.srova.player.desktop" \
    "$TREE/usr/share/metainfo/com.srova.player.metainfo.xml" \
    "$TREE/usr/share/icons/hicolor/512x512/apps/srova.png" \
    "$TREE/usr/share/icons/hicolor/512x512/apps/com.srova.player.png" \
    "$TREE/usr/share/pixmaps/srova.png" \
    "$TREE/etc/srova/srova.env.example" \
    "$TREE/usr/share/doc/srova/README.Debian"
  do
    [ -e "$path" ] || err "missing required path: $path"
    ls -ld "$path"
  done
  [ ! -e "$APP/src_rust/librust_audio_core.so" ] || err "legacy flat Rust library path must be absent: $APP/src_rust/librust_audio_core.so"
  validate_runtime_target_tree "$APP"

  echo
  echo "=== Reject forbidden artifacts in build tree ==="
  certifi_cacert="${APP}/libs/certifi/cacert.pem"
  [ -f "$certifi_cacert" ] || err "missing required Certifi CA bundle: $certifi_cacert"
  bad_paths="$(
    find "$APP" \( \
      -name '__pycache__' \
      -o -iname '*backup*' \
      -o -iname '*bkup*' \
      -o -name 'srcOLD' \
      -o -name '.codex' \
      -o -name '.claude' \
      -o -name '.git' \
      -o -name '.pytest_cache' \
      -o -name '*.pyc' \
      -o -name '*.pyo' \
      -o -name '*.bak' \
      -o -name '*.bak_*' \
      -o -name '*.bak-*' \
      -o -name '*.backup*' \
      -o -name '*.pre_*' \
      -o -name '*.pre-*' \
      -o -name '*.old' \
      -o -name '*.old_*' \
      -o -name '*.old-*' \
      -o -name '*.before_*' \
      -o -name '*.orig' \
      -o -name '*~' \
      -o -name '*.sqlite' \
      -o -name '*.sqlite3' \
      -o -name '*.db' \
      -o -name '*.db-*' \
      -o -name '*.log' \
      -o -name '.env' \
      -o -name '*.env' \
      -o -name '*.session' \
      -o -name 'session.json' \
      -o -name 'sessions.json' \
      -o -name 'token.json' \
      -o -name 'tokens.json' \
      -o -name 'credentials.json' \
      -o -name 'oauth.json' \
      -o -name 'oauth_token*' \
      -o -name '*.pem' \
      -o -name '*.key' \
      -o -name '*.crdownload' \
      -o -name '.xdp-*' \
      -o -name 'index[0-9]*.html' \
      -o -name 'srova[0-9]*.css' \
    \) ! -path "$certifi_cacert" -print
  )"
  target_dirs="$(
    find "$APP" -type d -name 'target' -print
  )"
  if [ -n "$target_dirs" ]; then
    while IFS= read -r target_dir; do
      if ! is_allowed_target_dir "$target_dir"; then
        printf '%s\n' "$target_dir"
        err "forbidden target directory found in packaged app tree"
      fi
    done <<< "$target_dirs"
  fi
  if [ -n "$bad_paths" ]; then
    printf '%s\n' "$bad_paths"
    err "forbidden artifacts found in packaged app tree"
  fi
  validate_runtime_target_tree "$APP"

  echo
  echo "=== Build .deb with root ownership ==="

  [ -f "$TREE/usr/lib/srova/srova-network-mount-helper" ] || \
    err "network mount helper is missing"

  [ -f "$TREE/usr/lib/systemd/system/srova-network-mounts.service" ] || \
    err "network restore service is missing"

  [ -f "$TREE/usr/lib/srova/srova-spotify-firewall-helper" ] || \
    err "Spotify firewall helper is missing"

  [ -f "$TREE/etc/sudoers.d/srova-network-mount" ] || \
    err "network sudoers file is missing"

  [ -f "$TREE/etc/sudoers.d/srova-spotify-firewall" ] || \
    err "Spotify firewall sudoers file is missing"

  [ "$(stat -c '%a' "$TREE/usr/lib/srova/srova-network-mount-helper")" = "755" ] || \
    err "network helper mode must be 0755"

  [ "$(stat -c '%a' "$TREE/usr/lib/srova/srova-spotify-firewall-helper")" = "755" ] || \
    err "Spotify firewall helper mode must be 0755"

  [ "$(stat -c '%a' "$TREE/usr/lib/systemd/system/srova-network-mounts.service")" = "644" ] || \
    err "restore service mode must be 0644"

  [ "$(stat -c '%a' "$TREE/etc/sudoers.d/srova-network-mount")" = "440" ] || \
    err "sudoers mode must be 0440"

  [ "$(stat -c '%a' "$TREE/etc/sudoers.d/srova-spotify-firewall")" = "440" ] || \
    err "Spotify firewall sudoers mode must be 0440"

  [ "$(cat "$TREE/etc/sudoers.d/srova-spotify-firewall")" = \
    "srova ALL=(root) NOPASSWD: /usr/lib/srova/srova-spotify-firewall-helper" ] || \
    err "Spotify firewall sudoers authorization is not exact"

  [ "$(stat -c '%a' "$TREE/etc/srova/network-credentials")" = "700" ] || \
    err "network credential directory mode must be 0700"

  if command -v visudo >/dev/null 2>&1; then
    visudo -cf "$TREE/etc/sudoers.d/srova-network-mount"
    visudo -cf "$TREE/etc/sudoers.d/srova-spotify-firewall"
  fi

  dpkg-deb --root-owner-group --build "$TREE" "$OUT"

  echo
  echo "=== Verify package metadata ==="
  pkg_arch="$(dpkg-deb -f "$OUT" Architecture)"
  pkg_version="$(dpkg-deb -f "$OUT" Version)"
  [ "$pkg_arch" = "arm64" ] || err "package metadata Architecture is $pkg_arch, expected arm64"
  [ "$pkg_version" = "$VERSION" ] || err "package metadata Version is $pkg_version, expected $VERSION"
  dpkg-deb -I "$OUT"

  echo
  echo "=== Inspect packaged Rust library ==="
  rm -rf "$INSPECT_ROOT"
  mkdir -p "$INSPECT_ROOT"
  dpkg-deb -x "$OUT" "$INSPECT_ROOT"
  validate_runtime_target_tree "${INSPECT_ROOT}/opt/srova"
  packaged_rust_so="${INSPECT_ROOT}/opt/srova/${RUST_RUNTIME_SO_REL}"
  [ -f "$packaged_rust_so" ] || err "packaged Rust library missing from .deb"
  file "$packaged_rust_so"
  case "$(file -b "$packaged_rust_so")" in
    *"ARM aarch64"*) ;;
    *) err "packaged Rust library is not ARM aarch64" ;;
  esac

  echo
  echo "=== Package content quick checks ==="
  dpkg-deb -c "$OUT" | grep -E '(/usr/bin/srova$|/usr/bin/srova-open|/usr/lib/srova/srova-server|/usr/lib/srova/srova-network-mount-helper|/usr/lib/srova/srova-spotify-firewall-helper|/usr/lib/srova/srova-wait-dns.sh|/usr/lib/systemd/system/srova.service|/usr/lib/systemd/system/srova-network-mounts.service|/etc/sudoers.d/srova-network-mount|/etc/sudoers.d/srova-spotify-firewall|/usr/share/applications/com.srova.player.desktop|/usr/share/metainfo/com.srova.player.metainfo.xml|/usr/share/icons/hicolor/.*/apps/srova.png|/usr/share/pixmaps/srova.png|/opt/srova/main_headless.py|/opt/srova/backend/tidal.py|/opt/srova/libs/tidalapi|/opt/srova/libs/ratelimit|/opt/srova/src_rust/rust_audio_core/target/release/librust_audio_core.so|/etc/srova/srova.env.example|/usr/share/doc/srova/README.Debian)' || true

  echo
  echo "=== Final artifact ==="
  echo "Path:   $OUT"
  echo "Bytes:  $(stat -c '%s' "$OUT")"
  echo "SHA256: $(sha256sum "$OUT" | awk '{print $1}')"
}

main "$@"
