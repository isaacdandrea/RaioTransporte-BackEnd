"""Utility helpers for configuration handling."""

from __future__ import annotations

from typing import Iterable, List, Sequence
from urllib.parse import urlsplit


def _dedupe_preserve_order(values: Iterable[str]) -> List[str]:
    """Return the unique values preserving the original ordering."""

    seen: set[str] = set()
    result: List[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def hosts_from_origins(origins: Sequence[str]) -> List[str]:
    """Extract hostnames from a sequence of origin URLs."""

    hosts: List[str] = []
    for origin in origins:
        if not origin:
            continue
        candidate = origin.strip()
        if not candidate:
            continue
        parsed = urlsplit(candidate if "://" in candidate else f"//{candidate}")
        host = parsed.hostname
        if host:
            hosts.append(host)
    return hosts


def extend_allowed_hosts(
    base_hosts: Sequence[str],
    *origin_lists: Sequence[str],
) -> List[str]:
    """Merge hostnames derived from origin lists into ``ALLOWED_HOSTS``.

    ``ALLOWED_HOSTS`` must already be a concrete sequence of hosts. When the
    wildcard host (``"*"``) is present we do not attempt to derive additional
    entries because Django would already accept all hosts.
    """

    if "*" in base_hosts:
        return list(base_hosts)

    derived_hosts: List[str] = []
    for origins in origin_lists:
        derived_hosts.extend(hosts_from_origins(origins))

    if not derived_hosts:
        return list(base_hosts)

    return _dedupe_preserve_order([*base_hosts, *derived_hosts])

