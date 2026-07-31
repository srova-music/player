#!/usr/bin/env bash
set -euo pipefail
umask 022

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PACKAGE_SCRIPT="$REPO_ROOT/package.sh"
VERSION_FILE="$REPO_ROOT/version.txt"

if ! command -v dpkg >/dev/null 2>&1; then
    echo "Error: dpkg is required." >&2
    exit 1
fi

ARCH="$(dpkg --print-architecture)"

if [ "$ARCH" != "arm64" ]; then
    echo "Error: this wrapper requires a native Debian arm64 host; found: $ARCH" >&2
    exit 1
fi

if [ ! -f "$PACKAGE_SCRIPT" ]; then
    echo "Error: package builder not found: $PACKAGE_SCRIPT" >&2
    exit 1
fi

if [ ! -f "$VERSION_FILE" ]; then
    echo "Error: version file not found: $VERSION_FILE" >&2
    exit 1
fi

VERSION="$(tr -d '[:space:]' < "$VERSION_FILE")"

if [ -z "$VERSION" ]; then
    echo "Error: package version is empty." >&2
    exit 1
fi

echo "============================================================"
echo " SROVA — NATIVE ARM64 DEBIAN BUILD"
echo "============================================================"
echo "Repository:   $REPO_ROOT"
echo "Architecture: $ARCH"
echo "Version:      $VERSION"
echo "Builder:      package.sh"
echo

exec bash "$PACKAGE_SCRIPT" deb "$VERSION"
