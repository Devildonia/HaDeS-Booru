"""
Shared pytest fixtures for the HaDeS Booru test suite.
"""

from __future__ import annotations

import ipaddress
import socket

import pytest

# Audit R7-D: keep the suite hermetic. Ten tests used to fail with
# "Could not resolve host: example.com" on machines without network access,
# because `assert_public_host()` performs a real DNS lookup before every
# request. This autouse fixture fakes DNS resolution:
#   - IP literals resolve to themselves, so the SSRF guard still sees loopback /
#     private / reserved addresses and keeps blocking them (R6-04 tests intact);
#   - hostnames resolve to a fixed public IP, so the guard passes offline.
_HERMETIC_PUBLIC_IP = "93.184.216.34"


def _fake_getaddrinfo(host: str, *args: object, **kwargs: object) -> list[tuple]:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        family = socket.AF_INET6 if ip.version == 6 else socket.AF_INET
        return [(family, socket.SOCK_STREAM, 6, "", (str(ip), 0))]
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (_HERMETIC_PUBLIC_IP, 0))]


@pytest.fixture(autouse=True)
def _hermetic_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo)
