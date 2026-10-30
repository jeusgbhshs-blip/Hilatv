"""SSRF guard for user-supplied asset URLs.

Resolve the host, reject non-global addresses, then connect to the address that
was checked. Redirects are followed by hand so every hop is checked again.
"""

from __future__ import annotations

import contextvars
import ipaddress
import socket
import threading
import time
import zlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
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


def assert_public_url(url: str, *, resolver: Resolver | None = None) -> None:
    """Reject a URL the SSRF guard would not fetch. This does not download the body."""

    hooks = _hooks.get()

    def resolve(host: str, port: int) -> list[str]:
        if resolver is not None:
            return resolver(host, port)
        if hooks is not None:
            return hooks.resolver(host, port)
        return _system_resolver(host, port, 5.0)

    _validated_target(_logical_url(url), resolve)


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
    transport = hooks.transport if hooks is not None else httpx.HTTPTransport(retries=0)
    deadline = time.monotonic() + timeout

    def resolver(host: str, port: int) -> list[str]:
        left = deadline - time.monotonic()
        if left <= 0:
            raise ValueError("url fetch timed out")
        if hooks is None:
            return _system_resolver(host, port, left)
        return hooks.resolver(host, port)

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
    if literal is None:
        literal = _parse_obfuscated_ipv4(host)
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
    except (UnsafeURL, ValueError):
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


def _system_resolver(host: str, port: int, timeout: float) -> list[str]:
    try:
        infos = _getaddrinfo(host, port, timeout)
    except socket.gaierror as exc:
        raise UnsafeURL(f"url host did not resolve: {host}") from exc
    addresses: list[str] = []
    for *_, sockaddr in infos:
        ip = str(sockaddr[0]).split("%", 1)[0]
        if ip not in addresses:
            addresses.append(ip)
    return addresses


def _getaddrinfo(host: str, port: int, timeout: float) -> list[tuple[object, ...]]:
    """Resolve ``host`` without letting DNS run past the fetch deadline."""

    if timeout <= 0:
        raise ValueError("url fetch timed out")
    outcome: dict[str, object] = {}

    def run() -> None:
        try:
            outcome["infos"] = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except BaseException as exc:
            outcome["error"] = exc

    worker = threading.Thread(target=run, name="hilatv-n1-dns", daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        raise ValueError("url fetch timed out")
    error = outcome.get("error")
    if error is not None:
        if isinstance(error, BaseException):
            raise error
        raise UnsafeURL(f"url host did not resolve: {host}")
    infos = outcome.get("infos")
    if not isinstance(infos, list):
        raise UnsafeURL(f"url host did not resolve: {host}")
    return infos


def _parse_ip(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    text = value.strip().strip("[]")
    if "%" in text:
        text = text.split("%", 1)[0]
    try:
        return ipaddress.ip_address(text)
    except ValueError:
        return None


def _parse_obfuscated_ipv4(host: str) -> ipaddress.IPv4Address | None:
    """Decode decimal, octal, hex, and short IPv4 forms such as ``127.1``.

    Browsers treat these as addresses. ``httpx`` leaves most of them as
    hostnames, so they must be classified before DNS.
    """

    if not host or any(char in host for char in "[]%:/"):
        return None
    parts = host.split(".")
    if not 1 <= len(parts) <= 4:
        return None
    numbers: list[int] = []
    for part in parts:
        number = _ipv4_component(part)
        if number is None:
            return None
        numbers.append(number)
    if len(numbers) == 1:
        packed = numbers[0]
    elif len(numbers) == 2:
        if numbers[0] > 0xFF or numbers[1] > 0xFFFFFF:
            return None
        packed = (numbers[0] << 24) | numbers[1]
    elif len(numbers) == 3:
        if numbers[0] > 0xFF or numbers[1] > 0xFF or numbers[2] > 0xFFFF:
            return None
        packed = (numbers[0] << 24) | (numbers[1] << 16) | numbers[2]
    else:
        if any(number > 0xFF for number in numbers):
            return None
        packed = (numbers[0] << 24) | (numbers[1] << 16) | (numbers[2] << 8) | numbers[3]
    if packed > 0xFFFFFFFF:
        return None
    return ipaddress.IPv4Address(packed)


def _ipv4_component(part: str) -> int | None:
    if not part:
        return None
    lowered = part.lower()
    try:
        if lowered.startswith("0x"):
            if len(part) == 2 or any(char not in "0123456789abcdef" for char in lowered[2:]):
                return None
            return int(lowered, 16)
        if part[0] == "0" and len(part) > 1:
            if any(char not in "01234567" for char in part):
                return None
            return int(part, 8)
        if not part.isdigit():
            return None
        return int(part, 10)
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
            "Accept-Encoding": "identity",
        },
        extensions={"sni_hostname": logical.raw_host.decode("ascii")},
        timeout=timeout,
    )
    return client.send(request, stream=True, follow_redirects=False)


def _read_limited(response: httpx.Response, max_bytes: int, deadline: float) -> bytes:
    # ``Response(content=...)`` has already buffered the body. Slice it.
    # Live responses stay streamed so a gzip body is capped while it expands.
    loaded = getattr(response, "_content", None)
    if isinstance(loaded, bytes):
        return loaded[:max_bytes]
    encoding = _content_encoding(response)
    if encoding == "gzip":
        return _read_decoded(response, max_bytes, deadline, zlib.decompressobj(16 + zlib.MAX_WBITS))
    if encoding == "deflate":
        return _read_decoded(response, max_bytes, deadline, zlib.decompressobj(zlib.MAX_WBITS))
    return _read_raw(response, max_bytes, deadline)


def _content_encoding(response: httpx.Response) -> str:
    parts = [
        part.strip().lower()
        for part in (response.headers.get("content-encoding") or "").split(",")
        if part.strip()
    ]
    if parts == ["gzip"] or parts == ["x-gzip"]:
        return "gzip"
    if parts == ["deflate"]:
        return "deflate"
    return ""


def _read_raw(response: httpx.Response, max_bytes: int, deadline: float) -> bytes:
    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_raw():
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


def _read_decoded(
    response: httpx.Response,
    max_bytes: int,
    deadline: float,
    decoder: Any,
) -> bytes:
    """Cap decompressed bytes so a small gzip body cannot expand without limit."""

    out = bytearray()
    try:
        for raw in response.iter_raw():
            if time.monotonic() >= deadline:
                raise ValueError("url fetch timed out")
            pending = raw
            while pending:
                room = max_bytes - len(out)
                if room <= 0:
                    return bytes(out[:max_bytes])
                piece = decoder.decompress(pending, room)
                leftover = decoder.unconsumed_tail
                if piece:
                    out.extend(piece)
                if len(out) >= max_bytes:
                    return bytes(out[:max_bytes])
                if leftover == pending:
                    break
                pending = leftover
        room = max_bytes - len(out)
        if room <= 0:
            return bytes(out[:max_bytes])
        tail = decoder.flush()
        if tail:
            out.extend(tail[:room])
    except zlib.error as exc:
        raise ValueError("url body could not be decoded") from exc
    return bytes(out[:max_bytes])
