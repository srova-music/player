# ARM64 Version 2.0 Debian Builder

The canonical ARM64 wrapper is:

`packaging/arm64/build_rc1_deb.sh`

The historical filename is retained for workflow compatibility. It does not
represent the current release version.

## Version 2.0 contract

- display version: `2.0`
- Debian package version: `2.0-1`
- architecture: native Debian `arm64`
- default control port: `8081`
- configured `SROVA_PORT`: supported
- installed runtime root: `/opt/srova`
- source default: `HEAD`
- source custody: resolved Git commit export
- Rust audio core: rebuilt natively on ARM64

The package contains `/opt/srova/version.txt`.

The native Rust audio library is installed at:

`/opt/srova/src_rust/rust_audio_core/target/release/librust_audio_core.so`

## Source selection

By default the wrapper selects `HEAD`, resolves it to an immutable Git commit,
verifies that its `version.txt` is exactly `2.0-1`, then exports that resolved
commit.

An explicit source may be selected with:

`SROVA_ARM64_SOURCE_REF=<commit-or-ref>`

Uncommitted working-tree source is not packaged.

## Python dependency bundle

The prepared dependency bundle must be supplied explicitly with:

`SROVA_ARM64_PYTHON_SITE=/absolute/path/to/site-packages`

The builder stops if that directory is unavailable.

## Build

On the prepared ARM64 builder:

    export SROVA_ARM64_PYTHON_SITE=/absolute/path/to/site-packages
    ./packaging/arm64/build_rc1_deb.sh

Generated exports, Cargo output, package trees, logs, inspection trees and
Debian artifacts remain outside the Git source tree.

## Package-source custody

Application source, `version.txt`, desktop assets and AppStream metadata are
taken from the selected Git export.

The checkout is used only as the Git object database from which the selected
commit is resolved and exported.

## Validation

The wrapper validates ARM64 architecture, source version, Rust architecture,
required runtime files, JavaScript and shell syntax, AppStream XML, Network
Music integration, Spotify firewall integration, package metadata, runtime
cleanliness and the permanent 8081 control-port contract.

Package installation and physical playback testing remain separate release
steps. This public-source worker does not build or publish packages.
