# SROVA

SROVA is a headless Linux music player for dedicated audio systems. Connect the
player computer to a DAC, place it out of sight, and control TIDAL, My Music and
Internet Radio from a browser on another device.

SROVA is designed around high-quality playback, a responsive browser interface
and clear Bit-Perfect signal-path reporting.

## Version 1 release

This public source snapshot corresponds to:

- SROVA Version 1.0
- Debian package version `1.0-1`
- web and control port `8081`
- qualified Debian package architectures: AMD64 and ARM64

The clean public snapshot was derived from the private release tag `v1.0.0`,
which resolves to commit
`3209b033b75928d01ebb594955e32d0b64f4a9f9`.

Private Git history is not included. Changes made while preparing this public
snapshot are limited to source curation, comment and branding cleanup,
test-harness repairs, documentation, and replacement of the obsolete RC1 ARM64
builder with a thin Version 1 wrapper around the shared package builder.

## Features

- TIDAL playback and library browsing
- My Music local-library scanning and playback
- mounted Network Music support
- Internet Radio with saved stations
- responsive desktop, tablet and mobile browser interfaces
- queue and playback control
- lyrics, track information and visualisation
- Last.fm and ListenBrainz scrobbling
- Bit-Perfect status and signal-path reporting
- direct ALSA and supported Linux audio-output paths
- automatic systemd service startup

## Supported release targets

The Version 1 release-qualified package format is Debian `.deb`.

- AMD64: tested on Debian and Debian-family PC or NUC systems
- ARM64: built natively on ARM64 Debian systems and tested on Raspberry Pi

Other inherited packaging and desktop-oriented source may remain in the tree
for compatibility or future work, but RPM, Arch and Flatpak packages are not
qualified Version 1 release targets.

## Accessing SROVA

The Debian package installs and enables `srova.service`.

After installation, open:

    http://<SROVA-player-LAN-IP>:8081

The player and browser device must be connected to the same local network.

The service launches the canonical runtime with:

    /usr/bin/python3 /opt/srova/main_headless.py --host 0.0.0.0

The installed application runtime is under `/opt/srova`.

## Repository layout

- `src/main_headless.py` — headless application and HTTP service
- `src/ui_web/` — browser interface
- `src/backend/` — TIDAL and backend integrations
- `src/services/` — remote API, scrobbling and supporting services
- `src/core/` — settings and shared application infrastructure
- `src_rust/` — Rust audio, visualisation and launcher sources
- `packaging/network/` — Network Music mount helper and systemd unit
- `packaging/arm64/build_deb.sh` — native ARM64 wrapper
- `package.sh` — authoritative Debian package builder
- `tests/` — automated test suite
- `CHANGELOG.md` — Version 1 and release-candidate history
- `NOTICE.md` — upstream attribution and modification notice

## Building an AMD64 Debian package

Build on a prepared native AMD64 Debian or Debian-family system with the
required Debian, Python, GStreamer, Rust and Cargo build dependencies installed.

From the repository root:

    ./package.sh deb "$(cat version.txt)"

For Version 1 this produces:

    dist/srova_1.0-1_amd64.deb

## Building an ARM64 Debian package

Build on a prepared native Debian ARM64 host, such as a Raspberry Pi 5:

    ./packaging/arm64/build_deb.sh

The wrapper verifies that the host architecture is ARM64, reads `version.txt`,
and delegates to the same authoritative `package.sh` Debian build path used for
AMD64.

For Version 1 this produces:

    dist/srova_1.0-1_arm64.deb

See `packaging/arm64/README.md` for the ARM64 build contract.

## Installing a locally built package

Install the package matching the machine architecture:

    sudo apt install ./dist/srova_1.0-1_amd64.deb

or:

    sudo apt install ./dist/srova_1.0-1_arm64.deb

The resulting package must be validated on a separate clean target system
before publication.

## Configuration and secrets

Do not commit runtime environment files, TIDAL sessions, Last.fm credentials,
API keys, databases, logs, mounted-share credentials or user-library data.

Optional Last.fm application credentials are read from:

- `SROVA_LASTFM_API_KEY`
- `SROVA_LASTFM_API_SECRET`

Users connect their own TIDAL, Last.fm and ListenBrainz-compatible accounts
through the application interfaces.

## Public-source scope

This repository contains the SROVA player source and its AMD64 and ARM64 Debian
build materials.

The SROVA Remote Android application, APK source, Google Cast receiver source
and passive Cast display source are separate projects and are not included in
this repository.

## Licence and attribution

SROVA is a modified work derived from the GPL-licensed
[hiresTI Music Player](https://github.com/yelanxin/hiresTI).

SROVA includes substantial modifications for headless operation, browser
control, My Music, Network Music, Internet Radio, packaging, branding, queue
behaviour, service management and remote control.

See `NOTICE.md` for attribution and `LICENSE` for the complete GNU General
Public License text.
