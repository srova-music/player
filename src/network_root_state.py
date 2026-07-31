"""Pure root-list updates for managed Network Music transactions."""

import os


def _parse_roots(value):
    roots = []
    for item in str(value or "").split(os.pathsep):
        item = item.strip()
        if not item:
            continue
        root = os.path.realpath(os.path.expanduser(item))
        if root not in roots:
            roots.append(root)
    return roots


def add_exact_managed_root(local_value, network_value, mount_path):
    text = str(mount_path or "").strip()
    if not text or not os.path.isabs(text):
        raise ValueError("Connected managed mount path is invalid.")
    managed = os.path.realpath(os.path.expanduser(text))
    roots = _parse_roots(local_value)
    network_roots = _parse_roots(network_value)
    if managed not in roots:
        roots.append(managed)
    if managed not in network_roots:
        network_roots.append(managed)
    return {
        "roots": roots,
        "network_roots": network_roots,
        "local_roots": [root for root in roots if root not in network_roots],
        "local_value": os.pathsep.join(roots),
        "network_value": os.pathsep.join(network_roots),
    }


def remove_exact_managed_root(local_value, network_value, mount_path):
    text = str(mount_path or "").strip()
    if not text or not os.path.isabs(text):
        raise ValueError("Disconnected managed mount path is invalid.")
    managed = os.path.realpath(os.path.expanduser(text))

    roots = [root for root in _parse_roots(local_value) if root != managed]
    network_roots = [root for root in _parse_roots(network_value) if root != managed]
    return {
        "roots": roots,
        "network_roots": network_roots,
        "local_roots": [root for root in roots if root not in network_roots],
        "local_value": os.pathsep.join(roots),
        "network_value": os.pathsep.join(network_roots),
    }
