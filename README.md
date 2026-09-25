# SROVA

SROVA is a headless Linux music player for dedicated audio systems. Connect the
player computer to a DAC and control playback from a browser on another device.

SROVA is designed around high-quality native playback, a responsive browser
interface and clear Bit-Perfect signal-path reporting.

## Version 2.0 release

This public source snapshot corresponds to:

- SROVA Version 2.0
- Debian package version `2.0-1`
- default web and control port `8081`
- canonical installed runtime root `/opt/srova`
- qualified Debian package architectures: AMD64 and ARM64

This Version 2.0 public source update is derived from the locked private release
source at commit:

`7e9d57aed0293aca85b2a707cf3843dde59bb2e5`

Private Git history is not included. The public repository contains curated
release source, build materials and tests. Private runtime state, credentials,
provider tokens, user databases, downloaded third-party runtime artifacts,
generated packages and development-only material are excluded.

## Playback sources and online providers

SROVA presents three native source families:

- My Music — Local Music and mounted Network Music
- Internet Radio
- SOURCE 03 — online music providers

TIDAL and Qobuz are normal SROVA online providers.

When one online provider is authenticated, SOURCE 03 identifies that provider
as TIDAL or QOBUZ. When both providers are available, SOURCE 03 is presented as
ONLINE.

Version 2.0 includes Qobuz authentication, catalog and library browsing,
lossless playback, search, playlists, favorites, lyrics, contextual Radio and
provider-aware navigation alongside TIDAL.

Provider-aware features include shared search and queue behavior, Infinite
Play, Auto-Mix and Go To Album.

## Optional Spotify Connect endpoint

SROVA can optionally manage Spotify's official Soloist endpoint as an external
convenience integration.

Spotify/Soloist is not SOURCE 04 and is separate from the SROVA native source
model.

The Spotify/Soloist path is not represented as SROVA native
Bit-Perfect/exclusive playback. Its playback behavior is determined by Spotify,
Soloist and the Linux audio path used by that endpoint.

Downloaded Soloist executables and archives are not included in this public
source snapshot.

## Other features

- My Music local-library scanning and playback
- mounted Network Music support
- Internet Radio with saved stations
- responsive desktop, tablet and mobile browser interfaces
- queue and playback control
- lyrics, track information and visualisation
- Last.fm and ListenBrainz scrobbling
- Bit-Perfect status and signal-path reporting for native playback
- direct ALSA and supported Linux audio-output paths
- automatic systemd service startup

## Supported release targets

The Version 2.0 release-qualified package format is Debian `.deb`.

- AMD64: Debian and Debian-family PC or NUC systems
- ARM64: native Debian ARM64 systems including Raspberry Pi

Other inherited packaging or desktop-oriented source may remain in the tree
for compatibility or future work, but RPM, Arch and Flatpak packages are not
qualified Version 2.0 release targets.

## Accessing SROVA

The Debian package installs and enables `srova.service`.

The default control address is:

    http://<SROVA-player-LAN-IP>:8081

The package default is port 8081. A configured `SROVA_PORT` remains supported
where exposed by the runtime.

The canonical installed application runtime is:

    /opt/srova

Runtime state and user configuration are stored outside the public source tree.

## Repository layout

- `src/main_headless.py` — headless application and HTTP service
- `src/ui_web/` — browser interface
- `src/backend/` — TIDAL and Qobuz provider backends
- `src/services/` — Spotify endpoint, scrobbling and support services
- `src/local_library.py` — Local and Network Music support
- `src_rust/` — Rust audio, visualisation and launcher source
- `packaging/network/` — Network Music and Spotify firewall helpers
- `packaging/arm64/build_rc1_deb.sh` — canonical ARM64 wrapper
- `package.sh` — AMD64/native Debian package source
- `tests/` — automated test suite
- `CHANGELOG.md` — release history
- `NOTICE.md` — attribution and third-party notices

The ARM64 wrapper retains its historical filename `build_rc1_deb.sh` for
release-workflow compatibility. The filename does not define the current
package version.

## Building an AMD64 Debian package

On a prepared native AMD64 Debian or Debian-family build host:

    ./package.sh deb "$(cat version.txt)"

For Version 2.0 the package version is `2.0-1`.

Architecture-specific package validation must be completed before publication.

## Building an ARM64 Debian package

Build on a prepared native Debian ARM64 host such as a Raspberry Pi 5:

    ./packaging/arm64/build_rc1_deb.sh

The ARM64 wrapper uses a Git source export and rebuilds the Rust audio core
natively for ARM64.

See `packaging/arm64/README.md` for the exact Version 2.0 ARM64 build contract.

## Configuration and secrets

Do not commit runtime environment files, TIDAL or Qobuz sessions, Last.fm
credentials, Spotify API keys, databases, logs, Network Music credentials,
signed media URLs or user-library data.

Optional Last.fm application credentials are read from:

- `SROVA_LASTFM_API_KEY`
- `SROVA_LASTFM_API_SECRET`

Qobuz service metadata needed by the provider implementation is discovered at
runtime from the Qobuz web-player service and cached outside the source tree.

Spotify API material and Soloist state are private runtime data.

## Public-source scope

This repository contains the SROVA Linux player source and its AMD64 and ARM64
Debian build materials.

The SROVA Remote Android application and SROVA Cast receiver/provisioning source
are separate projects and are not included here. Player-side SROVA Cast display
assets used by the Linux player remain part of this repository.

## Licence and attribution

SROVA is a modified work derived from the GPL-licensed hiresTI Music Player.

The Qobuz implementation contains work adapted from the MIT-licensed QBZ
project.

See `NOTICE.md` for attribution and `LICENSE` for the GNU General Public License
text applying to SROVA.
