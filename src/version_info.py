"""Read and format the installed SROVA release version."""

from pathlib import Path
import re


def display_version_for(package_version):
    """Convert a Debian package version into a concise user-facing version."""
    text = str(package_version or "").strip()
    if not text:
        return "unknown"

    # Remove the Debian packaging revision: 1.1-1 -> 1.1.
    match = re.match(r"^(?P<upstream>.+)-[0-9][A-Za-z0-9.+~]*$", text)
    upstream = match.group("upstream") if match else text

    # Keep common prerelease labels readable if this helper is used for an RC.
    upstream = re.sub(r"~rc([0-9]+)", r" RC\1", upstream, flags=re.IGNORECASE)
    upstream = re.sub(r"~beta([0-9]*)", r" Beta\1", upstream, flags=re.IGNORECASE)
    return upstream.strip() or "unknown"


def build_version_payload(package_version):
    package_text = str(package_version or "").strip() or "unknown"
    return {
        "package_version": package_text,
        "display_version": display_version_for(package_text),
    }


def read_version_payload(candidates=None):
    """Read version.txt from source-tree or installed-runtime locations."""
    if candidates is None:
        module_dir = Path(__file__).resolve().parent
        candidates = (
            module_dir / "version.txt",
            module_dir.parent / "version.txt",
        )

    for candidate in candidates:
        path = Path(candidate)
        try:
            version = path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            continue
        if version:
            return build_version_payload(version)

    return build_version_payload("unknown")
