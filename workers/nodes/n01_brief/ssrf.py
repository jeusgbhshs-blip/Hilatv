"""SSRF guard for user-supplied asset URLs.

Resolve the host, reject non-global addresses, then connect to the address that
was checked. Redirects are followed by hand so every hop is checked again.
"""

from __future__ import annotations

import contextvars
import ipaddress
import socket
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx

USER_AGENT = "HiLatvN1/0.1"
MAX_REDIRECTS = 5

_REDIRECTS = {301, 302, 303, 307, 308}
_NAT64 = ipaddress.IPv6Network("64:ff9b::/96")
_SIXTOFOUR = ipaddress.IPv6Network("2002::/16")
_TEREDO = ipaddress.IPv6Network("2001::/32")
_IPV4_COMPAT = ipaddress.IPv6Network("::/96")
# Addresses that serve cloud instance metadata. Link-local and unique-local
# ranges already cover most of these; 100.100.100.200 sits in carrier-grade NAT,
# which Python does not mark private.
_METADATA_V4 = frozenset(
    {
        ipaddress.IPv4Address("169.254.169.254"),
        ipaddress.IPv4Address("169.254.170.2"),
        ipaddress.IPv4Address("100.100.100.200"),
    }
)
_METADATA_V6 = frozenset({ipaddress.IPv6Address("fd00:ec2::254")})

Resolver = Callable[[str, int], list[str]]


class UnsafeURL(ValueError):
    """The URL must not be fetched."""


@dataclass(frozen=True)
class _Hooks:
    resolver: Resolver
    transport: httpx.BaseTransport


_hooks: contextvars.ContextVar[_Hooks | None] = contextvars.ContextVar(
    "hilatv_n1_fetch_hooks", default=None
)


@contextmanager
def fetch_hooks(*, resolver: Resolver, transport: httpx.BaseTransport) -> Iterator[None]:
    """Install a resolver and transport for the current context.

    IP literals are still classified directly. A resolver cannot turn
    ``127.0.0.1`` into a public address.
    """

    token = _hooks.set(_Hooks(resolver=resolver, transport=transport))
    try:
        yield
    finally:
        _hooks.reset(token)


def is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True for loopback, private, link-local, reserved, multicast, unspecified, metadata."""

    if isinstance(ip, ipaddress.IPv6Address):
        mapped = ip.ipv4_mapped
        if mapped is not None:
            return is_blocked_ip(mapped)
        if _is_translation_address(ip) or ip.is_site_local or ip in _METADATA_V6:
            return True
    elif ip in _METADATA_V4:
        return True
    return bool(
        ip.is_multicast
        or ip.is_loopback
        or ip.is_unspecified
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_private
        or not ip.is_global
    )


def fetch_bytes(url: str, *, timeout: float, max_bytes: int) -> tuple[bytes, str]:
    """GET ``url`` and return ``(body, content_type)``.

    The body is truncated to ``max_bytes``. ``timeout`` bounds the whole
    redirect chain, not each hop on its own. A caller-supplied HTTP client is
    not accepted: it could follow redirects or use a proxy first.
    """

    if max_bytes < 1:
        raise ValueError("url fetch size cap is invalid")
    if timeout <= 0:
        raise ValueError("url fetch timed out")
    hooks = _hooks.get()
    resolver = hooks.resolver if hooks is not None else _system_resolver
    transport = hooks.transport if hooks is not None else httpx.HTTPTransport(retries=0)
    deadline = time.monotonic() + timeout
    current = _logical_url(url)
    redirects = 0
    with httpx.Client(
        transport=transport,
        timeout=httpx.Timeout(timeout),
        follow_redirects=False,
        max_redirects=0,
        trust_env=False,
    ) as client:
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise ValueError("url fetch timed out")
            ip = _validated_target(current, resolver)
            try:
                response = _send(client, current, ip, left)
            except httpx.TimeoutException as exc:
                raise ValueError("url fetch timed out") from exc
            try:
                if response.status_code in _REDIRECTS:
                    redirects += 1
                    if redirects > MAX_REDIRECTS:
                        raise UnsafeURL("url has too many redirects")
                    current = _redirect_target(current, response.headers.get("location"))
                    continue
                response.raise_for_status()
                content_type = (response.headers.get("content-type") or "").split(";", 1)[0]
                body = _read_limited(response, max_bytes, deadline)
                return body, content_type.strip().lower()
            finally:
                response.close()


def _logical_url(url: str) -> httpx.URL:
    try:
        parsed = httpx.URL(url)
    except httpx.InvalidURL as exc:
        raise UnsafeURL("url is not allowed") from exc
    if parsed.scheme not in {"http", "https"}:
        raise UnsafeURL("url scheme is not allowed")
    if not parsed.host or parsed.username or parsed.password:
        raise UnsafeURL("url host is not allowed")
    return parsed


def _redirect_target(current: httpx.URL, location: str | None) -> httpx.URL:
    if location is None or not location.strip():
        raise UnsafeURL("url redirect is not allowed")
    if any(char in location for char in "\r\n\x00"):
        raise UnsafeURL("url redirect is not allowed")
    return _logical_url(urljoin(str(current), location.strip()))


def _validated_target(url: httpx.URL, resolver: Resolver) -> str:
    host = url.host
    literal = _parse_ip(host)
    if literal is not None:
        addresses = [literal]
    else:
        addresses = _resolve(host, _port(url), resolver)
    if not addresses or any(is_blocked_ip(ip) for ip in addresses):
        raise UnsafeURL(f"url target is not allowed: {host}")
    return str(addresses[0])


def _resolve(
    host: str, port: int, resolver: Resolver
) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        raw = resolver(host, port)
    except UnsafeURL:
        raise
    except Exception as exc:
        raise UnsafeURL(f"url host did not resolve: {host}") from exc
    found: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    seen: set[str] = set()
    for item in raw or []:
        ip = _parse_ip(str(item))
        if ip is None:
            raise UnsafeURL(f"url host did not resolve: {host}")
        key = str(ip)
        if key in seen:
            continue
        seen.add(key)
        found.append(ip)
    if not found:
        raise UnsafeURL(f"url host did not resolve: {host}")
    return found


def _system_resolver(host: str, port: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeURL(f"url host did not resolve: {host}") from exc
    addresses: list[str] = []
    for *_, sockaddr in infos:
        ip = str(sockaddr[0]).split("%", 1)[0]
        if ip not in addresses:
            addresses.append(ip)
    return addresses


def _parse_ip(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    text = value.strip().strip("[]")
    if "%" in text:
        text = text.split("%", 1)[0]
    try:
        return ipaddress.ip_address(text)
    except ValueError:
        return None


def _is_translation_address(ip: ipaddress.IPv6Address) -> bool:
    """NAT64, 6to4, Teredo, and deprecated IPv4-compatible forms.

    These embed an IPv4 destination inside a non-global IPv6 prefix. Connecting
    to the IPv6 address can still reach the embedded IPv4 host.
    """

    if ip in _NAT64 or ip in _SIXTOFOUR or ip in _TEREDO:
        return True
    return ip in _IPV4_COMPAT and int(ip) > 1


def _port(url: httpx.URL) -> int:
    if url.port is not None:
        return url.port
    if url.scheme == "https":
        return 443
    return 80


def _send(client: httpx.Client, logical: httpx.URL, ip: str, timeout: float) -> httpx.Response:
    pinned = logical.copy_with(host=ip)
    request = client.build_request(
        "GET",
        pinned,
        headers={
            "User-Agent": USER_AGENT,
            "Host": logical.netloc.decode("ascii"),
        },
        extensions={"sni_hostname": logical.raw_host.decode("ascii")},
        timeout=timeout,
    )
    return client.send(request, stream=True, follow_redirects=False)


def _read_limited(response: httpx.Response, max_bytes: int, deadline: float) -> bytes:
    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_bytes():
        if time.monotonic() >= deadline:
            raise ValueError("url fetch timed out")
        if not chunk:
            continue
        room = max_bytes - size
        if room <= 0:
            break
        if len(chunk) > room:
            chunks.append(chunk[:room])
            break
        chunks.append(chunk)
        size += len(chunk)
        if size >= max_bytes:
            break
    return b"".join(chunks)
