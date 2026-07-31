#!/bin/bash
set -euo pipefail

# ================= Configuration =================
APP_NAME="srova"
APP_ID="com.srova.player"  # Legacy desktop/Flatpak id; do not rename without migration
DISPLAY_NAME="SROVA"
MAINTAINER="SROVA Team <support@srova.music>"
DESCRIPTION="SROVA headless audiophile player with bit-perfect output support."
LICENSE="GPL-3.0"
URL="https://srova.music"
# ===========================================

TYPE="${1:-}"
VERSION="${2:-}"
USE_PY_BINARY="${HIRESTI_PY_BINARY:-0}"

# Compute DEB architecture string (e.g. amd64, arm64)
if command -v dpkg-deb &>/dev/null; then
    DEB_ARCH="$(dpkg --print-architecture)"
else
    DEB_ARCH="$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')"
fi

if [ -z "$TYPE" ] || [ -z "$VERSION" ]; then
    echo "Usage: ./package.sh [deb|rpm|rpm-fedora|rpm-el9|arch|flatpak|all] [version]  (note: 'all' skips flatpak)"
    echo "Example: ./package.sh all 1.0.0"
    exit 1
fi

if [[ "$TYPE" == "deb" || "$TYPE" == "all" ]] && ! command -v dpkg-deb &> /dev/null; then
    echo "Error: 'dpkg-deb' is required."
    exit 1
fi

if [[ "$TYPE" == "rpm" || "$TYPE" == "rpm-fedora" || "$TYPE" == "rpm-el9" || "$TYPE" == "all" ]] && ! command -v rpmbuild &> /dev/null; then
    echo "Error: 'rpmbuild' is required."
    exit 1
fi

if [[ "$TYPE" == "arch" || "$TYPE" == "all" ]] && ! command -v zstd &> /dev/null; then
    echo "Error: 'zstd' is required for Arch package build."
    exit 1
fi

if [[ "$TYPE" == "flatpak" ]] && ! command -v flatpak-builder &> /dev/null; then
    echo "Error: 'flatpak-builder' is required for Flatpak build."
    exit 1
fi

echo "🚀 Starting build process for $APP_NAME v$VERSION ($TYPE)..."

clean_package_payload() {
    echo "🧹 Cleaning package payload..."

    # Remove Python bytecode/cache from copied app and bundled libs.
    find "$BUILD_ROOT" -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
    find "$BUILD_ROOT" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete 2>/dev/null || true

    # Remove development/backup/state artifacts from final package payload.
    find "$BUILD_ROOT" -type d \( \
        -iname 'OLD Backup Files' -o \
        -iname '*backup*' \
    \) -prune -exec rm -rf {} + 2>/dev/null || true

    find "$BUILD_ROOT" -type f \( \
        -name '*.bak' -o \
        -name '*.bak_*' -o \
        -name '*.bak-*' -o \
        -name '*.backup*' -o \
        -name '*.before_*' -o \
        -name '*.orig' -o \
        -name '*~' -o \
        -name '*.log' -o \
        -name '*.sqlite' -o \
        -name '*.sqlite3' -o \
        -name '*.db' -o \
        -name '.env' \
    \) -delete 2>/dev/null || true

    # Avoid collisions with the separate upstream hiresti desktop package
    # and other shared icon names. Keep only SROVA app icons in the
    # system icon tree. App-internal assets under /opt/srova are untouched.
    if [ -d "$BUILD_ROOT/usr/share/icons" ]; then
        find "$BUILD_ROOT/usr/share/icons" -type f ! \( \
            -path "$BUILD_ROOT/usr/share/icons/hicolor/*/apps/srova.png" \
        \) -delete 2>/dev/null || true
        find "$BUILD_ROOT/usr/share/icons" -type d -empty -delete 2>/dev/null || true
    fi
    audit_svg_tree "$BUILD_ROOT" "staged package payload"
}

audit_svg_tree() {
    local root="$1"
    local label="$2"
    local svg
    local size
    local base

    [ -e "$root" ] || return 0

    while IFS= read -r -d '' svg; do
        base="$(basename "$svg")"
        size="$(stat -c '%s' "$svg")"

        case "$base" in
            hiresti.svg|srova.svg)
                echo "ERROR: forbidden legacy/application SVG in $label: $svg"
                return 1
                ;;
        esac

        if [ "$size" -gt 262144 ]; then
            echo "ERROR: oversized SVG in $label: $svg ($size bytes; maximum 262144)"
            return 1
        fi

        if LC_ALL=C grep -aEiq 'data:image/[^;[:space:]]+;base64|base64,' "$svg"; then
            echo "ERROR: embedded Base64 image data found in SVG in $label: $svg"
            return 1
        fi
    done < <(find "$root" -type f -name '*.svg' -print0)

    return 0
}

if [ "$USE_PY_BINARY" == "1" ]; then
    echo "🧱 Python app bundling: enabled (PyInstaller)"
else
    echo "🧱 Python app bundling: disabled (source mode)"
fi

# Keep a canonical version file in repo root based on build argument.
echo "$VERSION" > version.txt
echo "🧾 Version file updated: version.txt -> $VERSION"

sync_flatpak_metainfo_release() {
    local meta_file="flatpak/com.srova.player.metainfo.xml"
    if [ ! -f "$meta_file" ]; then
        return 0
    fi

    local release_date
    release_date="$(
        python3 - "$VERSION" CHANGELOG.md <<'PY_RELEASE_DATE'
from pathlib import Path
import re
import sys

version = sys.argv[1]
path = Path(sys.argv[2])
text = path.read_text(encoding="utf-8", errors="replace")

for line in text.splitlines():
    if not line.startswith("## "):
        continue
    if version not in line:
        continue

    match = re.search(r"\b(20[0-9]{2}-[0-9]{2}-[0-9]{2})\b", line)
    if match:
        print(match.group(1))
        break
PY_RELEASE_DATE
    )"
    if [ -z "$release_date" ]; then
        echo "ERROR: release date for $VERSION not found in CHANGELOG.md" >&2
        return 1
    fi

    local tmp_file
    tmp_file="$(mktemp)"
    awk -v version="$VERSION" -v date="$release_date" '
        /<releases>/ && !inserted {
            print
            print "    <release version=\"" version "\" date=\"" date "\"/>"
            inserted = 1
            next
        }
        {
            if (index($0, "<release version=\"" version "\"") > 0) {
                next
            }
            print
        }
    ' "$meta_file" > "$tmp_file"
    mv "$tmp_file" "$meta_file"
    chmod 0644 "$meta_file"
    echo "🧾 Flatpak metainfo synced: $VERSION ($release_date)"
}

sync_flatpak_metainfo_release

# Preflight checks
for required in src/main.py src/ui src/actions src/viz icons/hicolor; do
    if [ ! -e "$required" ]; then
        echo "Error: required path missing: $required"
        exit 1
    fi
done

for svg_root in src icons css packaging_assets; do
    audit_svg_tree "$svg_root" "packaging source"
done
echo "✅ SVG packaging guard passed: no forbidden, oversized, or embedded-raster SVG files"

# Permanent headless-runtime source invariant. These files are imported
# directly by main_headless.py or provide required local packages.
HEADLESS_RUNTIME_REQUIRED=(
    src/main_headless.py
    src/local_library.py
    src/network_music.py
    src/network_root_state.py
    src/radio_metadata.py
    src/app/__init__.py
    src/core/__init__.py
    src/ui/__init__.py
)

for required in "${HEADLESS_RUNTIME_REQUIRED[@]}"; do
    if [ ! -s "$required" ]; then
        echo "ERROR: required headless runtime source missing or empty: $required"
        exit 1
    fi
done

echo "✅ Required headless runtime source files are present"

# 1. Create temporary build directory
BUILD_ROOT="build_tmp"
rm -rf "$BUILD_ROOT"
mkdir -p "$BUILD_ROOT"

INSTALL_DIR="$BUILD_ROOT/usr/share/$APP_NAME"
BIN_DIR="$BUILD_ROOT/usr/bin"
APP_DIR="$BUILD_ROOT/usr/share/applications"
SYSTEM_ICON_DIR="$BUILD_ROOT/usr/share/icons"
SROVA_NAME="srova"
SROVA_INSTALL_DIR="$BUILD_ROOT/opt/$SROVA_NAME"

install_srova_headless_rust_audio_core() {
    # Headless/runtime package fix:
    # _rust/audio.py loads the native Rust core from /opt/srova/src_rust first.
    # Ensure the .deb includes that file so it never falls back to legacy
    # /usr/share/hiresti paths.
    local script_dir
    local source_root
    local rust_audio_so=""
    local dest_dir

    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    source_root="$(cd "$script_dir/.." && pwd)"

    for cand in \
        "$PWD/src_rust/rust_audio_core/target/release/librust_audio_core.so" \
        "$PWD/../src_rust/rust_audio_core/target/release/librust_audio_core.so" \
        "$script_dir/src_rust/rust_audio_core/target/release/librust_audio_core.so" \
        "$source_root/src_rust/rust_audio_core/target/release/librust_audio_core.so"
    do
        if [ -f "$cand" ]; then
            rust_audio_so="$cand"
            break
        fi
    done

    if [ -z "$rust_audio_so" ]; then
        echo "ERROR: built librust_audio_core.so not found for SROVA headless package"
        return 1
    fi

    dest_dir="$SROVA_INSTALL_DIR/src_rust/rust_audio_core/target/release"
    mkdir -p "$dest_dir"
    cp -a "$rust_audio_so" "$dest_dir/librust_audio_core.so"
    chmod 0755 "$dest_dir/librust_audio_core.so"

    echo "✅ SROVA headless Rust audio core: $dest_dir/librust_audio_core.so"
    sha256sum "$dest_dir/librust_audio_core.so" || true
}

SYSTEMD_SYSTEM_DIR="$BUILD_ROOT/lib/systemd/system"

mkdir -p "$INSTALL_DIR"
mkdir -p "$BIN_DIR"
mkdir -p "$APP_DIR"
mkdir -p "$SYSTEM_ICON_DIR"

# 2. Copy source files
echo "📂 Copying source files..."
# Copy main.py and new directory structure (src/)
cp -r src/* "$INSTALL_DIR/"
# Note: Rust .so files are copied separately below (see sections 2.1 and 2.2)
if [ -f "version.txt" ]; then cp version.txt "$INSTALL_DIR/"; fi
cp -r icons "$INSTALL_DIR/"
if [ -d "css" ]; then cp -r css "$INSTALL_DIR/"; fi
if [ -f "LICENSE" ]; then cp LICENSE "$INSTALL_DIR/"; fi

# 2.0 Optional: bundle the Python app as a standalone binary with PyInstaller onedir
if [ "$USE_PY_BINARY" == "1" ]; then
    if [ ! -x "tools/build_py_binary.sh" ]; then
        echo "Error: tools/build_py_binary.sh not found or not executable."
        exit 1
    fi
    echo "📦 Building bundled Python binary (PyInstaller)..."
    PYI_DIST_DIR="$BUILD_ROOT/pyi-dist"
    PYI_WORK_DIR="$BUILD_ROOT/pyi-work"
    PYI_SPEC_DIR="$BUILD_ROOT/pyi-spec"
    ./tools/build_py_binary.sh "$PYI_DIST_DIR" "$PYI_WORK_DIR" "$PYI_SPEC_DIR"
    if [ ! -x "$PYI_DIST_DIR/hiresti_app/hiresti_app" ]; then
        echo "Error: PyInstaller bundle missing executable: $PYI_DIST_DIR/hiresti_app/hiresti_app"
        exit 1
    fi
    rm -rf "$INSTALL_DIR/hiresti_app"
    cp -a "$PYI_DIST_DIR/hiresti_app" "$INSTALL_DIR/"
    echo "✅ Bundled Python binary: $INSTALL_DIR/hiresti_app/hiresti_app"
fi

# Public-package Rust builds must not embed private build-host paths.
# Preserve any caller-provided RUSTFLAGS, then add stable public prefixes.
srova_cargo_release_build() {
    local manifest="$1"
    local source_root
    local cargo_home
    local remap_flags
    local combined_rustflags

    source_root="$(pwd -P)"
    cargo_home="${CARGO_HOME:-${HOME:?HOME is required for Rust packaging}/.cargo}"

    remap_flags="--remap-path-prefix=${source_root}=/usr/src/srova"
    remap_flags+=" --remap-path-prefix=${cargo_home}/registry/src=/usr/src/cargo/registry"
    remap_flags+=" --remap-path-prefix=${cargo_home}/git=/usr/src/cargo/git"
    remap_flags+=" --remap-path-prefix=${HOME}=/usr/src/build-home"

    combined_rustflags="${RUSTFLAGS:-}"
    if [ -n "$combined_rustflags" ]; then
        combined_rustflags+=" "
    fi
    combined_rustflags+="$remap_flags"

    RUSTFLAGS="$combined_rustflags" \
        cargo build --manifest-path "$manifest" --release
}


# 2.1 Build and bundle Rust visualizer core shared library (libviz_core.so)
if [ -f "src_rust/rust_viz_core/Cargo.toml" ]; then
    if command -v cargo &> /dev/null; then
        echo "🦀 Building Rust visualizer core..."
        srova_cargo_release_build src_rust/rust_viz_core/Cargo.toml
        RUST_SO="src_rust/rust_viz_core/target/release/libviz_core.so"
        if [ ! -f "$RUST_SO" ]; then
            echo "Error: Rust build finished but $RUST_SO not found."
            exit 1
        fi
        mkdir -p "$INSTALL_DIR/src_rust/rust_viz_core/target/release"
        cp "$RUST_SO" "$INSTALL_DIR/src_rust/rust_viz_core/target/release/"
        echo "✅ Bundled Rust core: $RUST_SO"
    else
        echo "⚠️ 'cargo' not found. Rust core will not be bundled."
    fi
fi

# 2.2 Build and bundle Rust audio core shared library (librust_audio_core.so)
if [ -f "src_rust/rust_audio_core/Cargo.toml" ]; then
    if command -v cargo &> /dev/null; then
        echo "🦀 Building Rust audio core..."
        srova_cargo_release_build src_rust/rust_audio_core/Cargo.toml
        RUST_AUDIO_SO="src_rust/rust_audio_core/target/release/librust_audio_core.so"
        if [ ! -f "$RUST_AUDIO_SO" ]; then
            echo "Error: Rust audio build finished but $RUST_AUDIO_SO not found."
            exit 1
        fi
        mkdir -p "$INSTALL_DIR/src_rust/rust_audio_core/target/release"
        cp "$RUST_AUDIO_SO" "$INSTALL_DIR/src_rust/rust_audio_core/target/release/"
        echo "✅ Bundled Rust audio core: $RUST_AUDIO_SO"
    else
        echo "⚠️ 'cargo' not found. Rust audio core will not be bundled."
    fi
fi

# 2.3 Install SROVA launcher helper
# Note: EL9 and DEB use shell helpers because Rust launcher glibc compatibility can vary by target system
if [[ "$TYPE" == "rpm-el9" || "$TYPE" == "el9" || "$TYPE" == "deb" || "$TYPE" == "all" ]]; then
    # For EL9 and DEB, use a shell script wrapper for better compatibility
    cat <<'WRAPPER' > "$BIN_DIR/$APP_NAME"
#!/bin/bash
APP_DIR="/usr/share/srova"
cd "$APP_DIR"
PYTHONPATH="$APP_DIR/libs:$APP_DIR" python3 main.py "$@"
WRAPPER
    chmod +x "$BIN_DIR/$APP_NAME"
    echo "✅ Installed shell launcher: /usr/bin/$APP_NAME"
elif [ -f "src_rust/rust_launcher/Cargo.toml" ]; then
    if command -v cargo &> /dev/null; then
        echo "🦀 Building Rust launcher..."
        srova_cargo_release_build src_rust/rust_launcher/Cargo.toml
        RUST_LAUNCHER_BIN="src_rust/rust_launcher/target/release/hiresti"
        if [ ! -f "$RUST_LAUNCHER_BIN" ]; then
            echo "Error: Rust launcher build finished but $RUST_LAUNCHER_BIN not found."
            exit 1
        fi
        cp "$RUST_LAUNCHER_BIN" "$BIN_DIR/$APP_NAME"
        chmod +x "$BIN_DIR/$APP_NAME"
        echo "✅ Installed Rust launcher: /usr/bin/$APP_NAME"
    else
        echo "Error: 'cargo' not found. Rust launcher is required."
        exit 1
    fi
else
    echo "Error: src_rust/rust_launcher/Cargo.toml not found."
    exit 1
fi


# 2.3B Install SROVA desktop/open helper for headless service packages
# This prevents desktop "Open" from launching the legacy GUI wrapper.
cat <<'SROVA_OPEN_HELPER' > "$BIN_DIR/srova-open"
#!/usr/bin/env bash
set -u

APP_NAME="SROVA"

detect_port() {
  echo 8081
}

detect_lan_ip() {
  hostname -I 2>/dev/null | tr ' ' '\n' | grep -E '^[0-9]+\.' | grep -v '^127\.' | head -n1
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
SROVA_OPEN_HELPER
chmod +x "$BIN_DIR/srova-open"

# For headless packages, terminal/app-menu launch should not start the old GUI.
# Keep /usr/bin/srova as a harmless user-facing helper; systemd starts main_headless.py directly.
cat <<'SROVA_CLI_HELPER' > "$BIN_DIR/$APP_NAME"
#!/usr/bin/env bash
exec /usr/bin/srova-open "$@"
SROVA_CLI_HELPER
chmod +x "$BIN_DIR/$APP_NAME"

echo "✅ Installed SROVA open helper: /usr/bin/srova-open"
echo "✅ Installed SROVA CLI helper: /usr/bin/$APP_NAME"


# 3. Install icons
echo "🎨 Installing icons..."
# Keep bundled legacy icon assets, then duplicate them under the SROVA icon name for the desktop entry
if [ -d "icons/hicolor" ]; then
    cp -r icons/hicolor "$SYSTEM_ICON_DIR/"
    while IFS= read -r legacy_icon; do
        ext="${legacy_icon##*.}"
        dir="${legacy_icon%/*}"
        cp -f "$legacy_icon" "$dir/$APP_NAME.$ext"
    done < <(find "$SYSTEM_ICON_DIR/hicolor" -type f -name "hiresti.png" 2>/dev/null || true)
elif [ -f "icon.svg" ]; then
    mkdir -p "$SYSTEM_ICON_DIR/hicolor/scalable/apps"
    cp icon.svg "$SYSTEM_ICON_DIR/hicolor/scalable/apps/$APP_NAME.svg"
elif [ -f "icons/icon.png" ]; then
    mkdir -p "$SYSTEM_ICON_DIR/hicolor/256x256/apps"
    cp icons/icon.png "$SYSTEM_ICON_DIR/hicolor/256x256/apps/$APP_NAME.png"
else
    # Fallback
    if [ -f "icon.png" ]; then
         mkdir -p "$SYSTEM_ICON_DIR/hicolor/256x256/apps"
         cp icon.png "$SYSTEM_ICON_DIR/hicolor/256x256/apps/$APP_NAME.png"
    fi
fi


# 3.1 Install SROVA desktop/software-center icons from APK icon assets
SROVA_DESKTOP_ICON_DIR="packaging_assets/srova_desktop_icon/hicolor"
if [ -d "$SROVA_DESKTOP_ICON_DIR" ]; then
    for icon_png in "$SROVA_DESKTOP_ICON_DIR"/*x*/apps/srova.png; do
        [ -f "$icon_png" ] || continue
        size_dir="$(basename "$(dirname "$(dirname "$icon_png")")")"
        icon_target_dir="$BUILD_ROOT/usr/share/icons/hicolor/${size_dir}/apps"
        mkdir -p "$icon_target_dir"
        cp "$icon_png" "$icon_target_dir/srova.png"
        cp "$icon_png" "$icon_target_dir/com.srova.player.png"
    done

    mkdir -p "$BUILD_ROOT/usr/share/pixmaps"
    if [ -f "$SROVA_DESKTOP_ICON_DIR/512x512/apps/srova.png" ]; then
        cp "$SROVA_DESKTOP_ICON_DIR/512x512/apps/srova.png" "$BUILD_ROOT/usr/share/pixmaps/srova.png"
    elif [ -f "$SROVA_DESKTOP_ICON_DIR/256x256/apps/srova.png" ]; then
        cp "$SROVA_DESKTOP_ICON_DIR/256x256/apps/srova.png" "$BUILD_ROOT/usr/share/pixmaps/srova.png"
    fi

    echo "✅ Installed SROVA desktop/software-center icons from APK icon assets"
else
    echo "⚠️  SROVA desktop icon assets not found: $SROVA_DESKTOP_ICON_DIR"
fi

# 4. Bundle dependencies
echo "📦 Bundling Python dependencies..."
mkdir -p "$INSTALL_DIR/libs"

PYTHON_BUNDLE_LOCK="${SROVA_PYTHON_BUNDLE_LOCK:-packaging/python-bundle-requirements.lock}"
STRICT_PYTHON_BUNDLE="${SROVA_STRICT_PYTHON_BUNDLE:-0}"

if [ ! -s "$PYTHON_BUNDLE_LOCK" ]; then
    echo "ERROR: Python bundle lock missing or empty: $PYTHON_BUNDLE_LOCK"
    exit 1
fi

echo "🧾 Python bundle lock: $PYTHON_BUNDLE_LOCK"

if ! pip3 install \
    --requirement "$PYTHON_BUNDLE_LOCK" \
    --no-deps \
    --target "$INSTALL_DIR/libs" \
    --no-cache-dir \
    --upgrade \
    --disable-pip-version-check \
    --no-input
then
    if [ "$STRICT_PYTHON_BUNDLE" = "1" ]; then
        echo "ERROR: Strict Python bundle installation failed; local fallback is disabled."
        exit 1
    fi

    echo "⚠️ Pinned dependency install failed, using local site-packages fallback..."
    python3 - "$INSTALL_DIR/libs" <<'PY'
import os
import shutil
import sys
import sysconfig
from importlib.util import find_spec

target = sys.argv[1]
modules = [
    "tidalapi",
    "requests",
    "urllib3",
    "qrcode",
    "certifi",
    "idna",
    "dateutil",
    "typing_extensions",
    "isodate",
    "mpegdash",
    "pyaes",
    "ratelimit",
    "six",
]

def copy_path(src, dst_root):
    if not src or not os.path.exists(src):
        return False
    base = os.path.basename(src)
    dst = os.path.join(dst_root, base)
    if os.path.isdir(src):
        if os.path.exists(dst):
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)
    return True

copied = []
for mod in modules:
    spec = find_spec(mod)
    if spec is None:
        continue
    if spec.submodule_search_locations:
        src = list(spec.submodule_search_locations)[0]
    else:
        src = spec.origin
    if copy_path(src, target):
        copied.append(mod)

print("Copied local modules:", ", ".join(copied) if copied else "(none)")
PY
fi

# Portability invariant: /opt/srova/libs must contain only portable
# pure-Python dependencies. Compiled CPython extensions are tied to the
# builder interpreter ABI and must be supplied by the target distribution.
ABI_COUPLED_EXTENSION="$(
    find "$INSTALL_DIR/libs" \
        -type f \
        -name '*.cpython-*.so' \
        -print \
        -quit
)"

if [ -n "$ABI_COUPLED_EXTENSION" ]; then
    echo "ERROR: ABI-coupled Python extension found in portable bundle: $ABI_COUPLED_EXTENSION"
    exit 1
fi

for SYSTEM_PYTHON_PATH in \
    "$INSTALL_DIR/libs/PIL" \
    "$INSTALL_DIR/libs/pillow.libs" \
    "$INSTALL_DIR/libs/charset_normalizer"
do
    if [ -e "$SYSTEM_PYTHON_PATH" ]; then
        echo "ERROR: system-supplied Python dependency was bundled: $SYSTEM_PYTHON_PATH"
        exit 1
    fi
done

SYSTEM_PYTHON_METADATA="$(
    find "$INSTALL_DIR/libs" \
        -maxdepth 1 \
        -type d \
        \( \
            -iname 'pillow-*.dist-info' -o \
            -iname 'charset_normalizer-*.dist-info' \
        \) \
        -print \
        -quit
)"

if [ -n "$SYSTEM_PYTHON_METADATA" ]; then
    echo "ERROR: system-supplied Python dependency metadata was bundled: $SYSTEM_PYTHON_METADATA"
    exit 1
fi

echo "✅ Portable Python bundle contains no build-host CPython extensions"

# Keep RPM shebang checks happy: avoid /usr/bin/env python triggering brp-mangle-shebangs errors
while IFS= read -r f; do
    sed -i '1s|^#!/usr/bin/env python$|#!/usr/bin/env python3|' "$f"
done < <(grep -RIl '^#!/usr/bin/env python$' "$INSTALL_DIR/libs" || true)

install_srova_headless_files() {
    rm -rf "$SROVA_INSTALL_DIR"
    mkdir -p "$(dirname "$SROVA_INSTALL_DIR")"
    cp -a "$INSTALL_DIR" "$SROVA_INSTALL_DIR"

    mkdir -p "$SYSTEMD_SYSTEM_DIR"
    cat <<'EOF' > "$SYSTEMD_SYSTEM_DIR/srova.service"
[Unit]
Description=SROVA Headless Audio Player
After=network-online.target srova-network-mounts.service sound.target
Wants=network-online.target srova-network-mounts.service

[Service]
Type=simple
User=srova
Group=srova
WorkingDirectory=/opt/srova
Environment=HOME=/var/lib/srova
Environment=XDG_CONFIG_HOME=/var/lib/srova/.config
Environment=XDG_DATA_HOME=/var/lib/srova/.local/share
Environment=XDG_CACHE_HOME=/var/lib/srova/.cache
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONPATH=/opt/srova/libs:/opt/srova
EnvironmentFile=-/var/lib/srova/srova.env
ExecStart=/usr/bin/python3 /opt/srova/main_headless.py --host 0.0.0.0
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

    mkdir -p \
        "$BUILD_ROOT/usr/lib/srova" \
        "$BUILD_ROOT/usr/lib/systemd/system" \
        "$BUILD_ROOT/etc/sudoers.d" \
        "$BUILD_ROOT/etc/srova/network-credentials" \
        "$BUILD_ROOT/mnt/srova-network"

    install -m 0755 \
        packaging/network/srova-network-mount-helper \
        "$BUILD_ROOT/usr/lib/srova/srova-network-mount-helper"

    install -m 0644 \
        packaging/network/srova-network-mounts.service \
        "$BUILD_ROOT/usr/lib/systemd/system/srova-network-mounts.service"

    cat <<'EOF' > "$BUILD_ROOT/etc/sudoers.d/srova-network-mount"
srova ALL=(root) NOPASSWD: /usr/lib/srova/srova-network-mount-helper
EOF

    chmod 0440 "$BUILD_ROOT/etc/sudoers.d/srova-network-mount"
    chmod 0700 "$BUILD_ROOT/etc/srova/network-credentials"
    chmod 0755 "$BUILD_ROOT/mnt/srova-network"
}

finalize_deb_headless_payload() {
    # Debian installs the headless runtime exclusively under /opt/srova.
    # Never ship the legacy desktop application copy under /usr/share/srova.
    echo "🧹 Removing redundant Debian application tree: /usr/share/$APP_NAME"
    rm -rf "$INSTALL_DIR"

    if [ -e "$INSTALL_DIR" ]; then
        echo "ERROR: redundant Debian application tree still exists: $INSTALL_DIR"
        return 1
    fi

    # Permanent packaging invariant: every required headless Python runtime
    # file must exist inside the canonical /opt/srova payload. Reuse the
    # source preflight list so the two checks cannot drift apart.
    local source_path
    local runtime_path

    for source_path in "${HEADLESS_RUNTIME_REQUIRED[@]}"; do
        runtime_path="${source_path#src/}"

        if [ ! -s "$SROVA_INSTALL_DIR/$runtime_path" ]; then
            echo "ERROR: required headless runtime file missing or empty in Debian payload: /opt/$SROVA_NAME/$runtime_path"
            return 1
        fi
    done

    # Permanent packaging invariant: each required native runtime library
    # must appear exactly once in the completed Debian payload.
    local library
    local count
    for library in librust_audio_core.so libviz_core.so; do
        count="$(find "$BUILD_ROOT" -type f -name "$library" | wc -l | tr -d ' ')"
        if [ "$count" -ne 1 ]; then
            echo "ERROR: expected exactly one $library in Debian payload; found $count"
            find "$BUILD_ROOT" -type f -name "$library" -print
            return 1
        fi
    done

    echo "✅ Debian payload contains one /opt/srova runtime tree and one copy of each native core"
}

# 5. Create desktop file
# Keep the existing desktop file id for compatibility; user-visible name/launcher are SROVA
echo "🖥️ Creating desktop entry..."
cat <<EOF > "$APP_DIR/$APP_ID.desktop"
[Desktop Entry]
Name=$DISPLAY_NAME
Comment=$DESCRIPTION
Exec=/usr/bin/srova-open
# Icon name points to the duplicated SROVA desktop icon
Icon=$APP_NAME
Terminal=false
Type=Application
Categories=AudioVideo;Audio;Player;Music;
# StartupWMClass is kept for desktop/X11 compatibility.
StartupWMClass=$DISPLAY_NAME
StartupNotify=false
EOF


# 5.1 Install AppStream metadata for software centers
METAINFO_SRC="flatpak/${APP_ID}.metainfo.xml"
METAINFO_DIR="$BUILD_ROOT/usr/share/metainfo"
if [ -f "$METAINFO_SRC" ]; then
    mkdir -p "$METAINFO_DIR"
    cp "$METAINFO_SRC" "$METAINFO_DIR/${APP_ID}.metainfo.xml"
    echo "✅ Installed AppStream metadata: /usr/share/metainfo/${APP_ID}.metainfo.xml"
else
    echo "⚠️  AppStream metadata not found: $METAINFO_SRC"
fi

normalize_deb_payload_permissions() {
    echo "🔒 Normalizing Debian payload ownership-ready file modes..."

    # Record every file that is legitimately executable before removing
    # builder-user and group-write permissions from the payload.
    local -a executable_files=()
    local executable_file

    mapfile -d '' -t executable_files < <(
        find "$BUILD_ROOT" -type f -perm /111 -print0
    )

    find "$BUILD_ROOT" -type d -exec chmod 0755 {} +
    find "$BUILD_ROOT" -type f -exec chmod 0644 {} +

    # Restore execute permission only to files that had it before
    # normalization, including /usr/bin helpers, maintainer scripts,
    # bundled console tools, and native shared libraries.
    for executable_file in "${executable_files[@]}"; do
        chmod 0755 "$executable_file"
    done

    # Preserve the stricter modes required by the privileged Network Music
    # helper after the generic Debian payload normalization above.
    chmod 0755 "$BUILD_ROOT/usr/lib/srova/srova-network-mount-helper"
    chmod 0644 "$BUILD_ROOT/usr/lib/systemd/system/srova-network-mounts.service"
    chmod 0440 "$BUILD_ROOT/etc/sudoers.d/srova-network-mount"
    chmod 0700 "$BUILD_ROOT/etc/srova/network-credentials"
    chmod 0755 "$BUILD_ROOT/mnt/srova-network"

    echo "✅ Preserved executable mode on ${#executable_files[@]} payload files"
}

# ================= Package type handling =================

build_rpm_variant() {
    local variant="$1"
    local dist_tag="$2"
    local requires="$3"
    local arch spec_file rpm_build_root

    arch="$(uname -m)"
    rpm_build_root="$(pwd)/build_rpmbuild_${variant}"
    rm -rf "$rpm_build_root"
    mkdir -p "$rpm_build_root"/{BUILD,RPMS,SOURCES,SPECS,SRPMS}
    spec_file="$rpm_build_root/SPECS/$APP_NAME-${variant}.spec"

    cat <<EOF > "$spec_file"
Name:           $APP_NAME
Version:        $VERSION
Release:        1%{?dist}
Summary:        $DESCRIPTION (${variant})
License:        $LICENSE
BuildArch:      $arch
AutoReq:        no
AutoProv:       no
Requires:       $requires

%description
$DISPLAY_NAME is a headless audiophile player for Local Music, TIDAL, and Internet Radio (${variant} build).

%prep
%build
%install
cp -r $(pwd)/$BUILD_ROOT/* %{buildroot}

%files
/usr/share/$APP_NAME
/usr/bin/$APP_NAME
/usr/share/applications/$APP_ID.desktop
/usr/share/icons/*

%changelog
* $(date "+%a %b %d %Y") $MAINTAINER - $VERSION-1
- Automated ${variant} build
EOF

    rpmbuild -bb "$spec_file" \
        --define "_topdir $rpm_build_root" \
        --define "dist .${dist_tag}"

    mkdir -p dist
    mv "$rpm_build_root"/RPMS/"$arch"/${APP_NAME}-${VERSION}-1*.${arch}.rpm "dist/"
    echo "✅ RPM created (${variant})."
}

build_arch_package() {
    local arch pkg_rel pkg_ver_rel pkg_file pkg_root pkg_size build_ts
    arch="$(uname -m)"
    pkg_rel="1"
    pkg_ver_rel="${VERSION}-${pkg_rel}"
    pkg_file="dist/${APP_NAME}-${pkg_ver_rel}-${arch}.pkg.tar.zst"
    pkg_root="$(pwd)/build_archpkg/pkgroot"

    rm -rf "$(pwd)/build_archpkg"
    mkdir -p "$pkg_root"
    cp -a "$BUILD_ROOT"/. "$pkg_root"/

    pkg_size="$(du -sb "$pkg_root" | awk '{print $1}')"
    build_ts="$(date +%s)"

    cat <<EOF > "$pkg_root/.PKGINFO"
pkgname = $APP_NAME
pkgbase = $APP_NAME
pkgver = $pkg_ver_rel
pkgdesc = $DESCRIPTION
url = $URL
builddate = $build_ts
packager = $MAINTAINER
size = $pkg_size
arch = $arch
license = $LICENSE
depend = python
depend = gtk4
depend = libadwaita
depend = gstreamer
depend = gst-plugins-good
depend = gst-plugins-bad
depend = gst-plugins-ugly
depend = gst-python
depend = python-gobject
depend = python-cairo
depend = pipewire
depend = libpulse
EOF

    mkdir -p dist
    tar --sort=name --mtime="@$build_ts" --owner=0 --group=0 --numeric-owner \
        -C "$pkg_root" -I 'zstd -19 -T0' -cf "$pkg_file" .PKGINFO usr
    echo "✅ Arch package created."
}

build_flatpak_package() {
    local flatpak_builder_file="flatpak/com.srova.player.yml"
    local build_dir="build_flatpak"
    local repo_dir="flatpak/repo"

    if [ ! -f "$flatpak_builder_file" ]; then
        echo "Error: Flatpak manifest not found: $flatpak_builder_file"
        exit 1
    fi

    # Vendor Rust dependencies for offline Flatpak build.
    # flatpak-builder copies the source tree (type: dir) without network access, so the
    # vendor/ directory must exist before flatpak-builder is invoked.
    if [ -f "src_rust/rust_audio_core/Cargo.toml" ]; then
        if command -v cargo &>/dev/null; then
            echo "📦 Vendoring Rust audio core dependencies for Flatpak..."
            (cd src_rust/rust_audio_core && cargo vendor vendor)
        else
            echo "Error: 'cargo' not found. Cannot vendor Rust dependencies for Flatpak."
            exit 1
        fi
    fi

    # Clean previous build
    rm -rf "$build_dir"
    mkdir -p dist

    # Build the Flatpak using flatpak-builder
    # Note: runtime-version in manifest should match GNOME SDK version (e.g., 48), not app version
    flatpak-builder --force-clean --repo="$repo_dir" "$build_dir" "$flatpak_builder_file"

    # Export to a single .flatpak file
    flatpak build-bundle "$repo_dir" "dist/${APP_NAME}-${VERSION}.flatpak" "com.srova.player"

    echo "✅ Flatpak package created: dist/${APP_NAME}-${VERSION}.flatpak"
}

install_deb_maintainer_scripts() {
    mkdir -p "$BUILD_ROOT/var/lib/srova"
    cat <<'EOF' > "$BUILD_ROOT/DEBIAN/postinst"
#!/bin/sh
set -e

STATE_DIR="/var/lib/srova"
ENV_FILE="$STATE_DIR/srova.env"
LEGACY_ENV_FILE="/opt/srova/srova.env"
SERVICE_NAME="srova.service"
SERVICE_USER="srova"

ensure_service_user() {
    if id "$SERVICE_USER" >/dev/null 2>&1; then
        return 0
    fi
    if command -v adduser >/dev/null 2>&1; then
        adduser --system --group --home "$STATE_DIR" --no-create-home "$SERVICE_USER" >/dev/null 2>&1 || true
    elif command -v useradd >/dev/null 2>&1; then
        useradd --system --home-dir "$STATE_DIR" --no-create-home --user-group "$SERVICE_USER" >/dev/null 2>&1 || true
    fi
}

ensure_supplementary_groups() {
    if ! id "$SERVICE_USER" >/dev/null 2>&1 || ! command -v usermod >/dev/null 2>&1; then
        return 0
    fi
    if getent group audio >/dev/null 2>&1; then
        usermod -a -G audio "$SERVICE_USER" >/dev/null 2>&1 || true
    fi
}

ensure_service_user
ensure_supplementary_groups
install -d -m 0750 "$STATE_DIR"
install -d -m 0750 "$STATE_DIR/.config"
install -d -m 0750 "$STATE_DIR/.local/share"
install -d -m 0750 "$STATE_DIR/.cache"
install -d -m 0755 /mnt/srova-network
install -d -m 0755 /etc/srova
install -d -m 0700 /etc/srova/network-credentials

service_group="$SERVICE_USER"
if id "$SERVICE_USER" >/dev/null 2>&1; then
    service_group="$(id -gn "$SERVICE_USER")"
    chown "$SERVICE_USER:$service_group" "$STATE_DIR"
    chown "$SERVICE_USER:$service_group" "$STATE_DIR/.config" "$STATE_DIR/.local" "$STATE_DIR/.local/share" "$STATE_DIR/.cache"
fi

if [ ! -e "$ENV_FILE" ] && [ -f "$LEGACY_ENV_FILE" ]; then
    cp -p "$LEGACY_ENV_FILE" "$ENV_FILE"
    chmod 0640 "$ENV_FILE" || true
fi

if id "$SERVICE_USER" >/dev/null 2>&1; then
    chown "$SERVICE_USER:$service_group" "$ENV_FILE" 2>/dev/null || true
fi

if command -v systemctl >/dev/null 2>&1; then
    systemctl daemon-reload >/dev/null 2>&1 || true
    systemctl enable srova-network-mounts.service >/dev/null 2>&1 || true
    systemctl enable "$SERVICE_NAME" >/dev/null 2>&1 || true
    if [ -d /run/systemd/system ]; then
        systemctl restart "$SERVICE_NAME" >/dev/null 2>&1 || systemctl start "$SERVICE_NAME" >/dev/null 2>&1 || true
    fi
fi

exit 0
EOF
    chmod 0755 "$BUILD_ROOT/DEBIAN/postinst"

    cat <<'EOF' > "$BUILD_ROOT/DEBIAN/prerm"
#!/bin/sh
set -e

if [ "$1" = "remove" ] || [ "$1" = "deconfigure" ]; then
    if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
        systemctl stop srova.service >/dev/null 2>&1 || true
    fi

    if [ -x /usr/lib/srova/srova-network-mount-helper ]; then
        /usr/lib/srova/srova-network-mount-helper unmount-all </dev/null || \
            echo "WARNING: one or more SROVA network mounts could not be unmounted; continuing removal." >&2
    fi
fi

exit 0
EOF
    chmod 0755 "$BUILD_ROOT/DEBIAN/prerm"

    cat <<'EOF' > "$BUILD_ROOT/DEBIAN/postrm"
#!/bin/sh
set -e

if command -v systemctl >/dev/null 2>&1; then
    if [ "$1" = "purge" ]; then
        systemctl disable srova-network-mounts.service >/dev/null 2>&1 || true
        systemctl disable srova.service >/dev/null 2>&1 || true
    fi
    systemctl daemon-reload >/dev/null 2>&1 || true
fi

if [ "$1" = "purge" ]; then
    rm -f /etc/srova/network-mounts.json >/dev/null 2>&1 || true
    rm -rf /etc/srova/network-credentials >/dev/null 2>&1 || true

    for managed_dir in /mnt/srova-network/nfs-* /mnt/srova-network/smb-*; do
        [ -d "$managed_dir" ] || continue
        rmdir "$managed_dir" >/dev/null 2>&1 || true
    done

    rmdir /mnt/srova-network >/dev/null 2>&1 || true
fi

exit 0
EOF
    chmod 0755 "$BUILD_ROOT/DEBIAN/postrm"
}

validate_deb_network_payload() {
    local helper="$BUILD_ROOT/usr/lib/srova/srova-network-mount-helper"
    local restore_service="$BUILD_ROOT/usr/lib/systemd/system/srova-network-mounts.service"
    local sudoers="$BUILD_ROOT/etc/sudoers.d/srova-network-mount"
    local credential_dir="$BUILD_ROOT/etc/srova/network-credentials"

    [ -f "$helper" ] || {
        echo "Error: missing network mount helper." >&2
        return 1
    }

    [ -f "$restore_service" ] || {
        echo "Error: missing network restore service." >&2
        return 1
    }

    [ -f "$sudoers" ] || {
        echo "Error: missing network mount sudoers file." >&2
        return 1
    }

    [ "$(stat -c '%a' "$helper")" = "755" ] || {
        echo "Error: network helper mode must be 0755." >&2
        return 1
    }

    [ "$(stat -c '%a' "$restore_service")" = "644" ] || {
        echo "Error: restore service mode must be 0644." >&2
        return 1
    }

    [ "$(stat -c '%a' "$sudoers")" = "440" ] || {
        echo "Error: sudoers mode must be 0440." >&2
        return 1
    }

    [ "$(stat -c '%a' "$credential_dir")" = "700" ] || {
        echo "Error: network credential directory mode must be 0700." >&2
        return 1
    }

    if command -v visudo >/dev/null 2>&1; then
        visudo -cf "$sudoers"
    fi
}

validate_deb_network_archive() {
    local package="$1"
    local listing

    listing="$(dpkg-deb -c "$package")" || return 1

    printf '%s\n' "$listing" |
        awk '$1 == "-rwxr-xr-x" && $2 == "root/root" && $NF == "./usr/lib/srova/srova-network-mount-helper" { found=1 } END { exit !found }' || {
            echo "Error: packaged network helper must be root/root mode 0755." >&2
            return 1
        }

    printf '%s\n' "$listing" |
        awk '$1 == "-rw-r--r--" && $2 == "root/root" && $NF == "./usr/lib/systemd/system/srova-network-mounts.service" { found=1 } END { exit !found }' || {
            echo "Error: packaged network restore service must be root/root mode 0644." >&2
            return 1
        }

    printf '%s\n' "$listing" |
        awk '$1 == "-r--r-----" && $2 == "root/root" && $NF == "./etc/sudoers.d/srova-network-mount" { found=1 } END { exit !found }' || {
            echo "Error: packaged network sudoers file must be root/root mode 0440." >&2
            return 1
        }
}

if [ "$TYPE" == "deb" ]; then
    echo "📦 Building .deb package..."
    mkdir -p "$BUILD_ROOT/DEBIAN"
    cat <<EOF > "$BUILD_ROOT/DEBIAN/control"
Package: $APP_NAME
Version: $VERSION
Section: sound
Priority: optional
Architecture: $DEB_ARCH
Depends: python3, python3-gi, python3-gi-cairo, python3-cairo, python3-dateutil, python3-typing-extensions, python3-isodate, python3-pil, python3-charset-normalizer, gir1.2-gtk-4.0, gir1.2-adw-1, gir1.2-gtksource-4, qrencode, python3-gst-1.0, gstreamer1.0-plugins-base, gstreamer1.0-plugins-good, gstreamer1.0-plugins-bad, gstreamer1.0-plugins-ugly, libpipewire-0.3-0, libpulse0, sudo, nfs-common, cifs-utils, smbclient, iproute2
Maintainer: $MAINTAINER
Homepage: https://srova.music/
Description: $DESCRIPTION
 $DISPLAY_NAME is a headless audiophile player for Local Music, TIDAL, and Internet Radio.
EOF
    install_srova_headless_files
    install_srova_headless_rust_audio_core
    install_deb_maintainer_scripts
    finalize_deb_headless_payload
    mkdir -p dist
    clean_package_payload
    normalize_deb_payload_permissions
    validate_deb_network_payload
    dpkg-deb --root-owner-group --build "$BUILD_ROOT" "dist/${APP_NAME}_${VERSION}_${DEB_ARCH}.deb"
    validate_deb_network_archive "dist/${APP_NAME}_${VERSION}_${DEB_ARCH}.deb"
    echo "✅ DEB created."

elif [ "$TYPE" == "rpm" ]; then
    echo "📦 Building Fedora + EL9 RPM packages..."
    build_rpm_variant "fedora" "fedora" "python3, python3-gobject, python3-cairo, gtk4, libadwaita, gstreamer1-plugins-base, gstreamer1-plugins-good, gstreamer1-plugins-bad-free, gstreamer1-plugins-ugly-free"
    build_rpm_variant "el9" "el9" "python3, python3-gobject, python3-cairo, gtk4, libadwaita, gstreamer1-plugins-base, gstreamer1-plugins-good, gstreamer1-plugins-bad-free, gstreamer1-plugins-ugly-free"
elif [ "$TYPE" == "rpm-fedora" ]; then
    echo "📦 Building Fedora RPM package..."
    build_rpm_variant "fedora" "fedora" "python3, python3-gobject, python3-cairo, gtk4, libadwaita, gstreamer1-plugins-base, gstreamer1-plugins-good, gstreamer1-plugins-bad-free, gstreamer1-plugins-ugly-free"
elif [ "$TYPE" == "rpm-el9" ]; then
    echo "📦 Building EL9 RPM package..."
    build_rpm_variant "el9" "el9" "python3, python3-gobject, python3-cairo, gtk4, libadwaita, gstreamer1-plugins-base, gstreamer1-plugins-good, gstreamer1-plugins-bad-free, gstreamer1-plugins-ugly-free"
elif [ "$TYPE" == "arch" ]; then
    echo "📦 Building Arch package..."
    build_arch_package
elif [ "$TYPE" == "flatpak" ]; then
    echo "📦 Building Flatpak package..."
    build_flatpak_package
elif [ "$TYPE" == "all" ]; then
    echo "📦 Building DEB package..."
    mkdir -p "$BUILD_ROOT/DEBIAN"
    cat <<EOF > "$BUILD_ROOT/DEBIAN/control"
Package: $APP_NAME
Version: $VERSION
Section: sound
Priority: optional
Architecture: $DEB_ARCH
Depends: python3, python3-gi, python3-gi-cairo, python3-cairo, python3-dateutil, python3-typing-extensions, python3-isodate, python3-pil, python3-charset-normalizer, gir1.2-gtk-4.0, gir1.2-adw-1, gir1.2-gtksource-4, qrencode, python3-gst-1.0, gstreamer1.0-plugins-base, gstreamer1.0-plugins-good, gstreamer1.0-plugins-bad, gstreamer1.0-plugins-ugly, libpipewire-0.3-0, libpulse0, sudo, nfs-common, cifs-utils, smbclient, iproute2
Maintainer: $MAINTAINER
Homepage: https://srova.music/
Description: $DESCRIPTION
 $DISPLAY_NAME is a headless audiophile player for Local Music, TIDAL, and Internet Radio.
EOF
    install_srova_headless_files
    install_srova_headless_rust_audio_core
    install_deb_maintainer_scripts
    finalize_deb_headless_payload
    mkdir -p dist
    clean_package_payload
    normalize_deb_payload_permissions
    validate_deb_network_payload
    dpkg-deb --root-owner-group --build "$BUILD_ROOT" "dist/${APP_NAME}_${VERSION}_${DEB_ARCH}.deb"
    validate_deb_network_archive "dist/${APP_NAME}_${VERSION}_${DEB_ARCH}.deb"
    echo "✅ DEB created."

    # Remove DEBIAN metadata before RPM build to avoid unpackaged-file errors.
    rm -rf "$BUILD_ROOT/DEBIAN"

    echo "📦 Building Fedora + EL9 RPM packages..."
    build_rpm_variant "fedora" "fedora" "python3, python3-gobject, python3-cairo, gtk4, libadwaita, gstreamer1-plugins-base, gstreamer1-plugins-good, gstreamer1-plugins-bad-free, gstreamer1-plugins-ugly-free"
    build_rpm_variant "el9" "el9" "python3, python3-gobject, python3-cairo, gtk4, libadwaita, gstreamer1-plugins-base, gstreamer1-plugins-good, gstreamer1-plugins-bad-free, gstreamer1-plugins-ugly-free"
    echo "📦 Building Arch package..."
    build_arch_package
else
    echo "Error: unsupported type '$TYPE'. Use deb | rpm | rpm-fedora | rpm-el9 | arch | flatpak | all"
    exit 1
fi

rm -rf "$BUILD_ROOT"
echo "🎉 Build Complete!"
