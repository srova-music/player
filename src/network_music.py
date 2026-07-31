"""Safe Network Music discovery and helper integration for SROVA.

This module is intentionally standard-library only so it can be tested without
importing the web server, GTK, GStreamer, or playback code.
"""

from __future__ import annotations

import concurrent.futures
import ipaddress
import json
import os
import re
import socket
import subprocess
import tempfile
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple


DEFAULT_HELPER = "/usr/lib/srova/srova-network-mount-helper"
DEFAULT_DISCOVERY_TIMEOUT = 8.0
DEFAULT_CONNECT_TIMEOUT = 0.35
DEFAULT_WORKERS = 48
DEFAULT_HOST_CAP = 512
_RFC1918_NETWORKS = tuple(ipaddress.ip_network(value) for value in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
))
_SHARED_NETWORK = ipaddress.ip_network("100.64.0.0/10")
_DNS_LABEL_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


class NetworkMusicError(Exception):
    """User-facing Network Music error."""


def _run_command(
    argv: Sequence[str],
    *,
    timeout: float,
    input_text: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(argv),
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        env=env,
        shell=False,
        check=False,
    )


def _json_ip_addr(timeout: float = 2.0) -> List[Dict[str, Any]]:
    try:
        proc = _run_command(["ip", "-j", "-4", "addr", "show", "up"], timeout=timeout)
        if proc.returncode != 0:
            return []
        data = json.loads(proc.stdout or "[]")
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _ip_neigh(timeout: float = 2.0) -> List[str]:
    try:
        proc = _run_command(["ip", "neigh"], timeout=timeout)
    except Exception:
        return []
    if proc.returncode != 0:
        return []
    out: List[str] = []
    for line in (proc.stdout or "").splitlines():
        token = line.split(None, 1)[0] if line.split(None, 1) else ""
        try:
            ip = ipaddress.ip_address(token)
        except ValueError:
            continue
        if isinstance(ip, ipaddress.IPv4Address) and not ip.is_loopback:
            out.append(str(ip))
    return out


def _lan_ipv4(ip: ipaddress.IPv4Address) -> bool:
    return any(ip in network for network in _RFC1918_NETWORKS) or ip in _SHARED_NETWORK


def validate_host(value: Any) -> str:
    """Validate a host before passing it to any external command."""
    host = str(value or "")
    if len(host) > 253 or not host or host != host.strip():
        raise NetworkMusicError("Host is invalid.")
    if host.startswith("-") or any(ord(ch) < 33 or ord(ch) == 127 for ch in host):
        raise NetworkMusicError("Host is invalid.")
    if any(ch in host for ch in ",;/\\|&`$<>()[]{}='\""):
        raise NetworkMusicError("Host is invalid.")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if ":" in host:
            raise NetworkMusicError("IPv6 hosts are not supported for Network Music.")
        if all(ch.isdigit() or ch == "." for ch in host):
            raise NetworkMusicError("Host IP address is malformed.")
        if not all(_DNS_LABEL_RE.fullmatch(label) for label in host.split(".")):
            raise NetworkMusicError("Host DNS name is malformed.")
        return host
    if isinstance(ip, ipaddress.IPv6Address):
        raise NetworkMusicError("IPv6 hosts are not supported for Network Music.")
    return str(ip)


def validate_credential(value: Any, field: str, max_len: int) -> str:
    text = "" if value is None else str(value)
    if len(text) > max_len:
        raise NetworkMusicError(f"{field} is too long.")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
        raise NetworkMusicError(f"{field} contains unsupported characters.")
    return text


def validate_password(value: Any) -> str:
    """Return a printable SMB password byte-for-character unchanged."""
    return validate_credential(value, "Password", 1024)


@dataclass(frozen=True)
class LocalNetwork:
    address: str
    network: str


def discover_local_networks(ip_addr_data: Optional[List[Dict[str, Any]]] = None) -> List[LocalNetwork]:
    data = _json_ip_addr() if ip_addr_data is None else ip_addr_data
    out: List[LocalNetwork] = []
    seen = set()
    for iface in data:
        if not isinstance(iface, dict):
            continue
        for info in iface.get("addr_info") or []:
            if not isinstance(info, dict) or info.get("family") != "inet":
                continue
            raw_local = str(info.get("local") or "").strip()
            prefix = info.get("prefixlen")
            try:
                addr = ipaddress.ip_address(raw_local)
                network = ipaddress.ip_network(f"{raw_local}/{int(prefix)}", strict=False)
            except Exception:
                continue
            if not isinstance(addr, ipaddress.IPv4Address) or not (_lan_ipv4(addr) or addr.is_loopback):
                continue
            key = (str(addr), str(network))
            if key not in seen:
                seen.add(key)
                out.append(LocalNetwork(address=str(addr), network=str(network)))
    return out


def _bounded_hosts_for_network(local: LocalNetwork) -> List[str]:
    try:
        addr = ipaddress.ip_address(local.address)
        net = ipaddress.ip_network(local.network, strict=False)
    except ValueError:
        return []
    if not isinstance(addr, ipaddress.IPv4Address) or not _lan_ipv4(addr):
        return []
    if net.num_addresses <= 256:
        return [str(host) for host in net.hosts() if _lan_ipv4(host)]
    lan24 = ipaddress.ip_network(f"{addr}/24", strict=False)
    return [str(host) for host in lan24.hosts() if _lan_ipv4(host)]


def host_candidates(
    *,
    ip_addr_data: Optional[List[Dict[str, Any]]] = None,
    neigh_hosts: Optional[Iterable[str]] = None,
    cap: int = DEFAULT_HOST_CAP,
) -> List[str]:
    candidates: List[str] = []
    seen = set()

    def add(raw: str, *, local_address: bool = False) -> None:
        if len(candidates) >= cap:
            return
        try:
            ip = ipaddress.ip_address(str(raw).strip())
        except ValueError:
            return
        if not isinstance(ip, ipaddress.IPv4Address):
            return
        if not _lan_ipv4(ip) and not (local_address and ip.is_loopback):
            return
        text = str(ip)
        if text not in seen:
            seen.add(text)
            candidates.append(text)

    networks = discover_local_networks(ip_addr_data)
    for local in networks:
        add(local.address, local_address=True)
    for raw in neigh_hosts if neigh_hosts is not None else _ip_neigh():
        add(raw)
    for local in networks:
        for raw in _bounded_hosts_for_network(local):
            add(raw)
            if len(candidates) >= cap:
                break
    return candidates


def _port_open(host: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _safe_name_lookup(host: str, timeout: float = 0.15) -> str:
    try:
        proc = _run_command(["getent", "hosts", validate_host(host)], timeout=timeout)
        if proc.returncode != 0:
            return ""
        parts = (proc.stdout or "").split()
        return parts[1].split(".")[0] if len(parts) > 1 else ""
    except (NetworkMusicError, FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return ""


def discover_servers(
    *,
    candidates: Optional[Iterable[str]] = None,
    total_timeout: float = DEFAULT_DISCOVERY_TIMEOUT,
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
    workers: int = DEFAULT_WORKERS,
    cap: int = DEFAULT_HOST_CAP,
    connector: Callable[[str, int, float], bool] = _port_open,
) -> Dict[str, Any]:
    started = time.monotonic()
    hosts = list(candidates) if candidates is not None else host_candidates(cap=cap)
    hosts = host_candidates(
        ip_addr_data=[{"addr_info": [{"family": "inet", "local": h, "prefixlen": 32}]} for h in hosts],
        neigh_hosts=[],
        cap=cap,
    ) if candidates is not None else hosts[:cap]

    results: Dict[str, set] = {}
    max_workers = max(1, min(int(workers), 64, max(1, len(hosts) * 2)))

    def probe(item: Tuple[str, int]) -> Tuple[str, int, bool]:
        host, port = item
        if time.monotonic() - started > total_timeout:
            return host, port, False
        return host, port, bool(connector(host, port, connect_timeout))

    items = [(host, 2049) for host in hosts] + [(host, 445) for host in hosts]
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
    try:
        futures = {pool.submit(probe, item) for item in items}
        done, pending = concurrent.futures.wait(futures, timeout=total_timeout)
        for future in pending:
            future.cancel()
        for future in done:
            try:
                host, port, ok = future.result(timeout=0)
            except Exception:
                continue
            if not ok:
                continue
            results.setdefault(host, set()).add("nfs" if port == 2049 else "smb")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    servers = []
    for host in sorted(results, key=lambda h: tuple(int(p) for p in h.split("."))):
        protocols = sorted(results[host])
        remaining = total_timeout - (time.monotonic() - started)
        name = _safe_name_lookup(host, timeout=min(0.15, remaining)) if remaining > 0.01 else ""
        servers.append({"host": host, "name": name, "protocols": protocols})
    return {
        "ok": True,
        "servers": servers,
        "candidate_count": len(hosts),
        "duration_seconds": round(time.monotonic() - started, 3),
        "timeout_seconds": total_timeout,
        "host_cap": cap,
    }


def parse_showmount_exports(stdout: str, stderr: str = "", returncode: int = 0) -> List[Dict[str, str]]:
    if returncode != 0:
        return []
    exports: List[Dict[str, str]] = []
    for line in (stdout or "").splitlines():
        text = line.strip()
        if not text or text.lower().startswith("export list for"):
            continue
        path = text.split(None, 1)[0].strip()
        if path.startswith("/"):
            exports.append({"path": path})
    return exports


_SMB_IGNORED_TYPES = {"IPC", "PRINTER"}


def _is_admin_share(name: str) -> bool:
    upper = name.upper()
    return upper.endswith("$") or upper in {"ADMIN$", "IPC$", "PRINT$"}


def parse_smbclient_g(stdout: str, stderr: str = "", returncode: int = 0) -> List[Dict[str, str]]:
    if returncode != 0:
        return []
    shares: List[Dict[str, str]] = []
    for line in (stdout or "").splitlines():
        parts = line.rstrip("\n").split("|")
        if len(parts) < 2 or parts[0] != "Disk":
            continue
        name = parts[1].strip()
        if not name or _is_admin_share(name):
            continue
        if len(parts) >= 1 and parts[0].upper() in _SMB_IGNORED_TYPES:
            continue
        shares.append({"name": name, "comment": parts[2].strip() if len(parts) > 2 else ""})
    return shares


def list_nfs_exports(host: str, timeout: float = 4.0) -> Dict[str, Any]:
    try:
        safe_host = validate_host(host)
        proc = _run_command(["showmount", "-e", safe_host], timeout=timeout)
    except NetworkMusicError as exc:
        return {"ok": False, "error": str(exc)}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "NFS share listing timed out."}
    except FileNotFoundError:
        return {"ok": False, "error": "NFS share listing is unavailable because showmount is not installed."}
    except OSError as exc:
        return {"ok": False, "error": _classify_network_error(str(exc), "NFS")}
    exports = parse_showmount_exports(proc.stdout, proc.stderr, proc.returncode)
    if proc.returncode != 0 and not exports:
        return {"ok": False, "error": _classify_network_error(proc.stderr or proc.stdout, "NFS")}
    return {"ok": True, "host": safe_host, "protocol": "nfs", "exports": exports}


def _write_smb_auth_file(username: str, password: str, domain: str = "") -> str:
    username = validate_credential(username, "Username", 255)
    password = validate_password(password)
    domain = validate_credential(domain, "Domain", 255)
    fd, path = tempfile.mkstemp(prefix="srova-smb-", text=True)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(f"username = {username}\n")
            fh.write(f"password = {password}\n")
            if domain:
                fh.write(f"domain = {domain}\n")
    except Exception:
        try:
            os.unlink(path)
        except OSError:
            pass
        raise
    return path


def list_smb_shares(
    host: str,
    *,
    username: str = "",
    password: str = "",
    domain: str = "",
    timeout: float = 5.0,
) -> Dict[str, Any]:
    auth_path = ""
    try:
        safe_host = validate_host(host)
        username = validate_credential(username, "Username", 255)
        password = validate_password(password)
        domain = validate_credential(domain, "Domain", 255)
        argv = ["smbclient", "-g", "-L", safe_host]
        if username:
            auth_path = _write_smb_auth_file(username, password, domain)
            argv.extend(["-A", auth_path])
        else:
            argv.append("-N")
        try:
            proc = _run_command(argv, timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"ok": False, "auth_required": False, "error": "SMB share listing timed out."}
        except FileNotFoundError:
            return {"ok": False, "auth_required": False,
                    "error": "SMB share listing is unavailable because smbclient is not installed."}
        except OSError as exc:
            return {"ok": False, "auth_required": False,
                    "error": _classify_network_error(str(exc), "SMB", secrets=[password])}
        shares = parse_smbclient_g(proc.stdout, proc.stderr, proc.returncode)
        if proc.returncode != 0 and not shares:
            raw_error = proc.stderr or proc.stdout
            return {
                "ok": False,
                "auth_required": _smb_auth_failure(raw_error),
                "error": _classify_network_error(raw_error, "SMB", secrets=[password]),
            }
        return {"ok": True, "host": safe_host, "protocol": "smb", "shares": shares}
    except NetworkMusicError as exc:
        return {"ok": False, "auth_required": False, "error": str(exc)}
    finally:
        if auth_path:
            try:
                os.unlink(auth_path)
            except OSError:
                pass


def list_shares(host: str, protocol: str, credentials: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    proto = str(protocol or "").lower()
    if proto == "nfs":
        return list_nfs_exports(host)
    if proto == "smb":
        creds = credentials or {}
        return list_smb_shares(
            host,
            username=str(creds.get("username") or ""),
            password=validate_password(creds.get("password")),
            domain=str(creds.get("domain") or ""),
        )
    return {"ok": False, "error": "Unsupported network share protocol."}


def _sanitize_error(value: str, secrets: Optional[Iterable[str]] = None) -> str:
    text = str(value or "").strip()
    for secret in secrets or []:
        if secret:
            text = text.replace(str(secret), "[redacted]")
    low = text.lower()
    if "permission denied" in low or "logon failure" in low or "nt_status_logon_failure" in low:
        return "Authentication failed."
    if "timed out" in low or "timeout" in low:
        return "Network request timed out."
    if not text:
        return "Network request failed."
    return text[:500]


def _smb_auth_failure(value: str) -> bool:
    low = str(value or "").lower()
    return any(token in low for token in (
        "access denied", "permission denied", "logon failure", "nt_status_logon_failure",
        "nt_status_access_denied", "authentication failed", "session setup failed",
    ))


def _classify_network_error(value: str, protocol: str, secrets: Optional[Iterable[str]] = None) -> str:
    text = _sanitize_error(value, secrets=secrets)
    low = str(value or "").lower()
    if _smb_auth_failure(value):
        return "Authentication failed."
    if "timed out" in low or "timeout" in low:
        return f"{protocol} share listing timed out."
    if any(token in low for token in ("connection refused", "no route to host", "host is down",
                                       "network is unreachable", "name or service not known")):
        return f"{protocol} server is unreachable."
    if any(token in low for token in ("protocol", "nt_status_invalid", "rpc:")):
        return f"{protocol} protocol error: {text}"[:500]
    return text


def helper_path() -> str:
    return os.environ.get("SROVA_NETWORK_MOUNT_HELPER", DEFAULT_HELPER)


def call_mount_helper(action: str, payload: Optional[Dict[str, Any]] = None, timeout: float = 12.0) -> Dict[str, Any]:
    helper = helper_path()
    password = (payload or {}).get("password", "")
    if not os.path.exists(helper):
        return {"ok": False, "error": "Network mount helper is not installed."}
    argv = ["sudo", "-n", helper, action]
    try:
        proc = _run_command(argv, timeout=timeout, input_text=json.dumps(payload or {}))
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Network mount helper timed out."}
    except PermissionError:
        return {"ok": False, "error": "Network mount helper permission denied."}
    except FileNotFoundError:
        return {"ok": False, "error": "sudo or network mount helper is missing."}
    try:
        data = json.loads(proc.stdout)
        if isinstance(data, dict) and isinstance(data.get("ok"), bool):
            if data.get("error") is not None:
                data["error"] = _sanitize_error(data.get("error"), secrets=[password])
            data.pop("password", None)
            return data
    except Exception:
        pass
    error = str(proc.stderr or "").strip() or "Network mount helper returned an invalid response."
    return {"ok": False, "error": _sanitize_error(error, secrets=[password])}
