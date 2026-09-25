# SROVA Changelog

## 2.0 (`2.0-1`) — 2026-09-25

Version 2.0 adds Qobuz as a full online provider alongside TIDAL and expands
SROVA's provider-aware playback, navigation and recommendation model.

### Added

- Qobuz authentication, catalog and library access, search and lossless playback
- Qobuz album, artist and track detail flows
- Qobuz playlists, favorites and lyrics integration
- contextual TIDAL and Qobuz provider Radio
- provider-aware Infinite Play and Auto-Mix
- provider-aware Go To Album
- optional Spotify Connect endpoint management through Spotify's official Soloist runtime
- permanent packaging regression coverage for the SROVA 8081 control-port contract

### Improved

- SOURCE 03 now represents the online-provider family, showing TIDAL or QOBUZ
  with one authenticated provider and ONLINE when both are available
- Global Search includes Qobuz with provider-aware navigation
- playlist loading and state presentation
- Internet Radio Stop behavior and active queue cleanup
- first-run DAC selection and headless startup behavior
- Spotify endpoint lifecycle coordination with native-audio ownership

### Packaging and public source

- public source is curated from locked private PSC2 commit
  `7e9d57aed0293aca85b2a707cf3843dde59bb2e5`
  without importing private Git history
- package version is `2.0-1`
- user-facing version is 2.0
- default SROVA control port is 8081
- configured `SROVA_PORT` remains supported where exposed by the runtime
- canonical installed runtime root is `/opt/srova`
- downloaded Spotify Soloist artifacts and private Spotify state are excluded
  from public source custody

## 1.4 (`1.4-1`) — 2026-08-28

### Added

- SROVA Cast now includes the accepted SROVA Clock presentation in the player-side Cast display, with the final header spacing and playback-state presentation behaviour.

### Improved

- TIDAL My Songs, My Albums and My Playlists loading coalesces concurrent cache misses, rejects stale account or mutation results, and uses a faster completion check.
- NAS and Network Music discovery presents immediate scan activity, clearer status text and centred modal controls.
- The Home wordmark is inert on the true Home landing view while retaining Home navigation from other views.

### Fixed

- Fresh installations now select the recommended ALSA mmap driver by default while preserving existing saved output choices.
- Radio Now Playing reports the authoritative saved station name consistently across station changes and browser restoration.
- Radio Add to Queue and Play Next confirmations identify the saved station by name while retaining a safe generic fallback.
- Home artwork remains stable through pause, resume, seeking and same-artwork track transitions while preserving transitions for genuine artwork changes.
- Saved Radio artwork is prepared while hidden after Android wake and revealed atomically, preventing a visible first-visit redraw.

## 1.3 (`1.3-1`) — 2026-08-19

### Added

- Now Playing can open the matching TIDAL album when SROVA has a confident album identity.

### Improved

- Play Queue reordering preserves the working scroll position instead of jumping back to the top.
- Radio transitions keep Up Next and the player bar synchronized with active playback, while Radio artwork is retained across source navigation to avoid unnecessary redraws.
- Infinite Play generation is coordinated more reliably and uses stronger diversity/history handling to reduce repetition and avoid avoidable generation pauses.
- Browser asset cache handling and low-risk production housekeeping were hardened without changing the release runtime contract.

### Fixed

- Manual mmap seeking for Local Music and TIDAL uses hardened position-state handling for more reliable forward and backward seeks.

## 1.2 (`1.2-1`) — 2026-08-13

### Added

- Lightweight update checks with the SROVA red-dot indicator on Settings and About
- Installed-version-aware update details and AMD64/ARM64 package links in About
- Saved Internet Radio presets can be reordered directly with drag handles
- SROVA Cast display-player assets are included for receiver and Android Remote playback
- Play Queue Up Next tracks can be reordered directly from accessible drag handles, with safer SROVA-styled removal confirmation

### Fixed

- Local Music Add to Queue now preserves the playing album and appends new tracks at the end

## 1.1 (`1.1-1`) — 2026-08-06

- Settings → About now reports the installed SROVA release version from package metadata instead of a stale hard-coded label.

### Improved

- Global Search now remains hidden until TIDAL is authenticated and online or My Music has a completed, non-empty, currently available searchable index
- Global Search availability now follows TIDAL login/logout, network availability, Local Music scan completion, and music-folder availability
- Unlocked DAC driver and output selections now validate and save automatically, while the existing release safety gate remains in place
- DAC selection now shows recommended external USB and supported audio HAT outputs by default, with consent-gated access to all other detected system outputs
- Other audio outputs now require an explicit hearing and equipment safety acknowledgement, while recommended devices remain labelled and grouped first
- My Music now marks edited folder choices as unsaved and uses one Save & Scan action that saves successfully before scanning

### Fixed

- Removed a stale browser reference to the nonexistent legacy `ui.css` asset, eliminating its harmless 404 without changing rendered styles
- Player-bar TIDAL artist and album links now follow the same status snapshot as the visible track metadata, preventing stale navigation after album switches
- Local Music player-bar artist names now open the existing Local artist page, while Local track titles no longer route into broken TIDAL album pages
- Local artist pages now populate album-card artwork and stable Local album IDs through the existing read-only album grouping path
- Local artist page track rows now display their Local album artwork instead of the generic music-note tile
- Direct Local track selections now synchronize the Play Queue and player-bar status with the file that actually started playing

### Validation

- Recommended-device filtering, the consent-gated Other-output flow, and live audio-output classification passed on an AMD64 NUC with a Topping DX5 II USB DAC and the internal `pcsp` output
- ARM64 audio HAT validation remains a separate release target

## 1.0 (`1.0-1`) — 2026-07-27

### Added

- Last.fm benefits guidance in Scrobbling Settings explaining the SROVA enhancements unlocked by a free, one-time setup
- External-browser signup links for free Last.fm and ListenBrainz-compatible accounts, shown only while setup is required
- Always-visible SROVA service controls in System Settings
- Manual SROVA status refresh and a client-local last-restarted timestamp

### Improved

- Pinned all bundled Python package versions for reproducible AMD64 and ARM64 release builds
- Restart progress now remains locked while the page reconnects automatically
- Restart success is confirmed only after the backend process identity changes
- Disabled restart controls use a neutral grey state
- Success actions are hidden briefly to prevent an accidental second restart
- System Settings remains selected after reconnecting or changing the web address

### Fixed

- Removed obsolete Last.fm API-key and ListenBrainz-token help links from Scrobbling Settings
- Replaced unreliable browser-triggered `systemctl` and `sudo` restart attempts with a controlled systemd-managed process restart
- Preserved queue state with a bounded save before the controlled restart exit
- Kept the Remote Access restart button hidden unless a saved port change requires it

### Validation

- Restart flow passed in the SROVA Remote APK WebView
- Restart timestamp, automatic reconnection, success state, and repeat-click protection passed
- Existing Network Recovery tests and focused System restart tests passed

## 1.0 RC2 (`1.0~rc2-1`) — 2026-07-16

RC2 expands Network Music setup, Radio management, TIDAL playlist control, and artist navigation while hardening Debian packaging and release validation.

### Added

- LAN discovery for NFS and SMB Network Music shares
- Managed read-only Network Music mounts with reboot restoration
- Safe connect, disconnect, and persisted managed-root handling
- Six curated Internet Radio presets
- Persistent custom ordering for Radio stations
- Rename support for user-owned TIDAL playlists
- Ownership checks that keep editorial and non-owned playlists read-only
- Artists results in Global, Local, and TIDAL search
- Local artist album navigation with corrected artwork and Back behaviour

### Improved

- Local Music album artwork and playback context handling
- Network Music package dependencies, helper integration, service configuration, and sudoers rules
- Radio preset migration while preserving existing stations and ordering
- Debian package ownership and file-mode normalization
- AMD64 and ARM64 package parity validation
- Browser cache-bust and hard-refresh release testing

### Fixed

- Restored the TIDAL playlist ownership backend required for safe playlist renaming
- Prevented package removal from hanging while waiting for helper stdin
- Removed an oversized embedded-raster SVG from the package source
- Hardened package audits against oversized or embedded-raster SVG artwork
- Corrected Local artist album navigation and artwork in packaged builds
- Corrected missing Network Music runtime files in Debian packages

### Validation

- AMD64 built and tested on Zorin OS
- ARM64 built natively on Raspberry Pi 5
- ARM64 installed and tested on Raspberry Pi 4
- Radio, My Music, Network Music, TIDAL playback, queue navigation, and owned-playlist renaming passed
- Architecture-independent AMD64 and ARM64 payload parity passed
- Published GitHub and R2 package downloads were re-downloaded and SHA256 verified

## 1.0 RC1 (`1.0~rc1-1`) — 2026-07-10

First private GitHub baseline for the SROVA release-candidate series.

### Included

- Headless Linux service with responsive browser interface
- TIDAL playback, authentication, library, search, playlists, and queue actions
- Local lossless music scanning and playback
- Multiple Local Music folders
- Mounted Network Music folder support
- Internet Radio playback and Radio queue actions
- Play Queue position and wall/list return memory
- Local Music lyrics and artist information
- Infinite Play with same-artist and Last.fm-assisted modes
- Exclusive ALSA output and bit-perfect status reporting
- AMD64 and ARM64 Debian packaging workflows
- SROVA desktop launcher, icon, browser-access helper, and AppStream metadata
- SROVA Remote compatibility

### Repository preparation

- Removed build caches, generated packages, backups, logs, runtime databases, and local configuration
- Retained the AMD64 Rust audio library as a packaging fallback while preserving source-based Rust builds
- Removed bundled upstream Last.fm credentials and replaced them with optional environment-variable configuration
- Replaced inherited hiresTI release documentation with SROVA-specific RC1 documentation
- Preserved GPL-3.0 licensing and upstream attribution

## Earlier development

SROVA was developed through a series of internal test builds before RC1. Those working-build notes and generated packages are intentionally not imported into Git history.

The first Git commit establishes RC1 as the clean project baseline.
