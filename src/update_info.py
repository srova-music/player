"""Lightweight SROVA release-update discovery."""

from copy import deepcopy
from html import unescape
import os
import platform
import re
import threading
import time
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from version_info import read_version_payload

DOWNLOADS_URL = "https://srova.music/downloads/"
UPDATE_CACHE_SECONDS = 6 * 60 * 60
UPDATE_FAILURE_CACHE_SECONDS = 10 * 60
UPDATE_TIMEOUT_SECONDS = 4

_CACHE = {"checked_at": 0.0, "payload": None}
_CACHE_LOCK = threading.Lock()


def normalized_architecture(machine=None):
    value = str(machine if machine is not None else platform.machine()).strip().lower()
    if value in ("x86_64", "amd64"):
        return "amd64"
    if value in ("aarch64", "arm64"):
        return "arm64"
    return "unknown"


def version_key(value):
    """Return a comparable release key, or None for malformed versions."""
    text = re.sub(r"^[vV]", "", str(value or "").strip())
    text = re.sub(r"-[0-9][A-Za-z0-9.+~]*$", "", text)
    match = re.match(
        r"^(?P<numbers>[0-9]+(?:\.[0-9]+){0,3})"
        r"(?:(?:[\s.~_-]?)(?P<label>rc|beta|alpha)(?P<serial>[0-9]*))?$",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    numbers = tuple(int(part) for part in match.group("numbers").split("."))
    numbers = (numbers + (0, 0, 0, 0))[:4]
    label = (match.group("label") or "").lower()
    stage = {"alpha": 0, "beta": 1, "rc": 2, "": 3}[label]
    return numbers + (stage, int(match.group("serial") or 0))


def is_newer_version(latest, current):
    latest_key = version_key(latest)
    current_key = version_key(current)
    return bool(latest_key is not None and current_key is not None and latest_key > current_key)


def _release_version(release):
    for field in ("tag_name", "name"):
        value = str(release.get(field) or "").strip()
        match = re.search(r"[vV]?[0-9]+(?:\.[0-9]+){0,3}(?:(?:[\s.~_-]?)(?:rc|beta|alpha)[0-9]*)?", value, re.I)
        if match and version_key(match.group(0)) is not None:
            return re.sub(r"^[vV]", "", match.group(0))
    return ""


def _asset_download_url(release, architecture):
    if architecture not in ("amd64", "arm64"):
        return ""
    pattern = re.compile(r"(?:^|[_-])" + re.escape(architecture) + r"\.deb$", re.I)
    for asset in release.get("assets") or []:
        name = str(asset.get("name") or "")
        url = str(asset.get("browser_download_url") or "").strip()
        if url and pattern.search(name):
            return url
    return ""


def build_update_payload(release, current_payload=None, machine=None):
    current_payload = current_payload or read_version_payload()
    current = str(current_payload.get("display_version") or "").strip()
    latest = _release_version(release)
    architecture = normalized_architecture(machine)
    available = is_newer_version(latest, current)
    release_url = str(release.get("html_url") or "").strip() or DOWNLOADS_URL
    package_url = _asset_download_url(release, architecture)
    return {
        "ok": True,
        "current_version": current or "unknown",
        "latest_version": latest or "unknown",
        "update_available": available,
        "architecture": architecture,
        "download_url": (package_url or release_url) if available else "",
        "download_kind": ("package" if package_url else "release_page") if available else "",
    }


def _downloads_release_from_html(page_html):
    text = str(page_html or "")
    title = re.search(r"<title[^>]*>\s*SROVA\s+Downloads\s*[—-]\s*Version\s+([^<]+)</title>", text, re.I)
    version = title.group(1).strip() if title else ""
    assets = []
    for href in re.findall(r"href=[\"']([^\"']+\.deb(?:\?[^\"']*)?)[\"']", text, re.I):
        url = urljoin(DOWNLOADS_URL, unescape(href))
        name = url.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
        assets.append({"name": name, "browser_download_url": url})
        if not version:
            match = re.search(r"srova_([^_]+)_(?:amd64|arm64)\.deb$", name, re.I)
            if match:
                version = match.group(1)
    return {"tag_name": version, "name": "SROVA " + version, "html_url": DOWNLOADS_URL, "assets": assets}


def _fetch_latest_release(opener=urlopen):
    request = Request(DOWNLOADS_URL, headers={"User-Agent": "SROVA-update-check"})
    with opener(request, timeout=UPDATE_TIMEOUT_SECONDS) as response:
        return _downloads_release_from_html(response.read().decode("utf-8", "replace"))


def read_update_payload(force=False, now=None, opener=urlopen, machine=None):
    """Return cached update state; network failures remain neutral."""
    test_version = str(os.environ.get("SROVA_UPDATE_TEST_VERSION", "")).strip()
    if test_version:
        test_package_version = re.sub(r"^[vV]", "", test_version)
        test_release = {
            "tag_name": test_version,
            "name": "SROVA " + test_version,
            "html_url": DOWNLOADS_URL,
            "assets": [
                {
                    "name": "srova_%s-1_%s.deb" % (test_package_version, arch),
                    "browser_download_url": "https://downloads.srova.music/srova_%s-1_%s.deb"
                    % (test_package_version, arch),
                }
                for arch in ("amd64", "arm64")
            ],
        }
        return build_update_payload(test_release, machine=machine)

    timestamp = time.time() if now is None else float(now)
    with _CACHE_LOCK:
        cached = _CACHE.get("payload")
        checked_at = float(_CACHE.get("checked_at") or 0.0)
        cache_seconds = UPDATE_CACHE_SECONDS if cached and cached.get("ok") else UPDATE_FAILURE_CACHE_SECONDS
        if not force and cached is not None and timestamp - checked_at < cache_seconds:
            return deepcopy(cached)
        try:
            payload = build_update_payload(_fetch_latest_release(opener=opener), machine=machine)
        except Exception:
            current = read_version_payload().get("display_version", "unknown")
            payload = {
                "ok": False, "current_version": current, "latest_version": "unknown",
                "update_available": False, "architecture": normalized_architecture(machine),
                "download_url": "", "download_kind": "",
            }
        _CACHE["checked_at"] = timestamp
        _CACHE["payload"] = payload
        return deepcopy(payload)


def clear_update_cache():
    with _CACHE_LOCK:
        _CACHE["checked_at"] = 0.0
        _CACHE["payload"] = None
