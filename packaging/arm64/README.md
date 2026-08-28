# ARM64 Debian Build

SROVA uses the repository-root `package.sh` as the authoritative Debian
package builder for both AMD64 and ARM64.

On a prepared native Debian ARM64 build system, such as a Raspberry Pi 5, run:

    ./packaging/arm64/build_deb.sh

The wrapper:

- refuses non-ARM64 hosts;
- reads the package version from `version.txt`;
- delegates directly to `package.sh deb`;
- does not maintain a separate package payload or service definition.

For Version 1.4, `version.txt` contains `1.4-1`, producing:

    dist/srova_1.4-1_arm64.deb

The AMD64 and ARM64 packages share the same release contract:

- canonical runtime under `/opt/srova`;
- `srova.service` starts `main_headless.py`;
- browser and control service uses port `8081`;
- native Rust libraries are built for the host architecture;
- Network Music lifecycle and Debian payload validation are applied.

Build dependencies, including Rust and Cargo, must be installed. Validate the
finished package on a separate clean ARM64 test system before publication.
