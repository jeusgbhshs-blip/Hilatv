"""SSRF checks for N1 URL fetches. Resolver and transport are mocks; no sockets."""

from __future__ import annotations

import ipaddress
import socket

import httpx
import pytest

from workers.nodes.n01_brief.attachments import Deadline, parse_attachment
from workers.nodes.n01_brief.node import run
from workers.nodes.n01_brief.schema import AttachmentRef
from workers.nodes.n01_brief.ssrf import MAX_REDIRECTS, UnsafeURL, fetch_bytes, fetch_hooks

PUBLIC_IP = "93.184.216.34"
PUBLIC_V6 = "2001:4860:4860::8888"

_BLOCKED_LITERALS = [
    "http://127.0.0.1/secret",
    "http://10.1.2.3/secret",
    "http://192.168.1.20/secret",
    "http://172.16.4.5/secret",
    "http://169.254.169.254/latest/meta-data",
    "http://169.254.170.2/",
    "http://100.100.100.200/",
    "http://0.0.0.0/",
    "http://224.0.0.1/",
    "http://[::1]/secret",
    "http://[::ffff:127.0.0.1]/secret",
    "http://[::ffff:10.0.0.8]/secret",
    "http://[::ffff:192.168.0.2]/secret",
    "http://[::ffff:169.254.169.254]/latest/meta-data",
    "http://[::ffff:100.100.100.200]/",
    "http://[fd00:ec2::254]/",
    "http://[fec0::1]/",
    "http://[64:ff9b::7f00:1]/",
]


@pytest.fixture(autouse=True)
def _no_system_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> list[object]:
        raise AssertionError("system DNS was used")

    monkeypatch.setattr(socket, "getaddrinfo", boom)


def _fetch(
    url: str,
    *,
    resolver,
    handler,
    timeout: float = 2.0,
    max_bytes: int = 100_000,
) -> tuple[bytes, str, list[httpx.Request], list[str]]:
    requests: list[httpx.Request] = []
    resolved: list[str] = []

    def resolve(host: str, port: int) -> list[str]:
        resolved.append(host)
        return resolver(host, port)

    def transport_handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    with fetch_hooks(resolver=resolve, transport=httpx.MockTransport(transport_handler)):
        body, content_type = fetch_bytes(url, timeout=timeout, max_bytes=max_bytes)
    return body, content_type, requests, resolved


def _reject(url: str, *, resolver=None) -> tuple[list[httpx.Request], list[str]]:
    requests: list[httpx.Request] = []
    resolved: list[str] = []

    def resolve(host: str, port: int) -> list[str]:
        resolved.append(host)
        if resolver is None:
            raise AssertionError(f"unexpected DNS for {host}")
        return resolver(host, port)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise AssertionError(f"connected to {request.url.host}")

    with (
        fetch_hooks(resolver=resolve, transport=httpx.MockTransport(handler)),
        pytest.raises(UnsafeURL, match="not allowed"),
    ):
        fetch_bytes(url, timeout=2.0, max_bytes=1000)
    return requests, resolved


@pytest.mark.parametrize("url", _BLOCKED_LITERALS)
def test_blocked_literals_never_connect(url: str) -> None:
    requests, resolved = _reject(url)
    assert requests == []
    assert resolved == []


@pytest.mark.parametrize("answers", [["127.0.0.1"], ["::1"], ["127.0.0.1", "::1"]])
def test_localhost_is_rejected(answers: list[str]) -> None:
    requests, resolved = _reject("http://localhost/admin", resolver=lambda host, port: answers)
    assert requests == []
    assert resolved == ["localhost"]


def test_metadata_hostname_is_rejected() -> None:
    requests, resolved = _reject(
        "http://metadata.google.internal/computeMetadata/v1/",
        resolver=lambda host, port: ["169.254.169.254"],
    )
    assert requests == []
    assert resolved == ["metadata.google.internal"]


def test_mixed_public_and_private_records_are_rejected() -> None:
    requests, _resolved = _reject(
        "http://cdn.example/a",
        resolver=lambda host, port: [PUBLIC_IP, "10.0.0.2"],
    )
    assert requests == []


@pytest.mark.parametrize(
    "location",
    [
        "http://127.0.0.1/secret",
        "http://10.9.8.7/secret",
        "http://192.168.0.4/secret",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/secret",
        "http://[::ffff:10.1.1.1]/secret",
        "//169.254.169.254/latest",
    ],
)
def test_public_redirect_to_internal_is_rejected(location: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == PUBLIC_IP
        return httpx.Response(302, headers={"location": location})

    with pytest.raises(UnsafeURL, match="not allowed"):
        _fetch(
            "https://cdn.example/start",
            resolver=lambda host, port: [PUBLIC_IP],
            handler=handler,
        )


def test_redirect_to_hostname_that_resolves_internally_is_rejected() -> None:
    resolved: list[str] = []
    connected: list[str] = []

    def resolver(host: str, port: int) -> list[str]:
        resolved.append(host)
        if host == "cdn.example":
            return [PUBLIC_IP]
        if host == "intranet.example":
            return ["192.168.5.5"]
        raise AssertionError(host)

    def handler(request: httpx.Request) -> httpx.Response:
        connected.append(request.url.host)
        return httpx.Response(302, headers={"location": "http://intranet.example/secret"})

    with (
        fetch_hooks(resolver=resolver, transport=httpx.MockTransport(handler)),
        pytest.raises(UnsafeURL, match="intranet.example"),
    ):
        fetch_bytes("http://cdn.example/start", timeout=2.0, max_bytes=1000)
    assert connected == [PUBLIC_IP]
    assert resolved == ["cdn.example", "intranet.example"]


def test_redirect_revalidates_and_pins_the_address() -> None:
    answers = [[PUBLIC_IP], ["127.0.0.1"]]

    def resolver(host: str, port: int) -> list[str]:
        return answers.pop(0)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == PUBLIC_IP
        return httpx.Response(302, headers={"location": "http://cdn.example/next"})

    with pytest.raises(UnsafeURL, match="not allowed"):
        _fetch("http://cdn.example/start", resolver=resolver, handler=handler)
    assert answers == []


def test_public_url_connects_to_the_validated_ip() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == PUBLIC_IP
        assert request.url.scheme == "https"
        assert request.headers["host"] == "cdn.example"
        assert request.extensions["sni_hostname"] == "cdn.example"
        budget = request.extensions["timeout"]
        assert budget["connect"] <= 2
        assert budget["read"] <= 2
        return httpx.Response(
            200,
            content=b"<p>ok</p>",
            headers={"content-type": "text/html; charset=utf-8"},
        )

    body, content_type, requests, resolved = _fetch(
        "https://cdn.example/brochure",
        resolver=lambda host, port: [PUBLIC_IP] if (host, port) == ("cdn.example", 443) else [],
        handler=handler,
    )
    assert body == b"<p>ok</p>"
    assert content_type == "text/html"
    assert len(requests) == 1
    assert resolved == ["cdn.example"]


def test_public_ipv6_and_mapped_public_are_allowed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=request.url.host.encode(), headers={"content-type": "text/plain"}
        )

    body, _ctype, requests, _resolved = _fetch(
        "https://cdn.example/v6",
        resolver=lambda host, port: [PUBLIC_V6],
        handler=handler,
    )
    assert body == PUBLIC_V6.encode()
    assert requests[0].url.host == PUBLIC_V6

    mapped = "http://[::ffff:93.184.216.34]/ok"
    body, _ctype, requests, resolved = _fetch(
        mapped, resolver=lambda host, port: [], handler=handler
    )
    assert resolved == []
    pinned = ipaddress.ip_address(requests[0].url.host)
    assert pinned == ipaddress.ip_address("::ffff:93.184.216.34")
    assert ipaddress.ip_address(body.decode()) == pinned


def test_same_host_redirect_is_followed_via_the_pinned_ip() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == PUBLIC_IP
        if request.url.path == "/a":
            return httpx.Response(302, headers={"location": "/b"})
        return httpx.Response(200, content=b"done", headers={"content-type": "text/plain"})

    body, content_type, requests, resolved = _fetch(
        "http://cdn.example/a",
        resolver=lambda host, port: [PUBLIC_IP],
        handler=handler,
    )
    assert body == b"done"
    assert content_type == "text/plain"
    assert [request.url.path for request in requests] == ["/a", "/b"]
    assert resolved == ["cdn.example", "cdn.example"]


def test_redirects_are_capped() -> None:
    connected: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        connected.append(request.url.host)
        return httpx.Response(302, headers={"location": "/again"})

    with (
        fetch_hooks(
            resolver=lambda host, port: [PUBLIC_IP],
            transport=httpx.MockTransport(handler),
        ),
        pytest.raises(UnsafeURL, match="redirect"),
    ):
        fetch_bytes("http://cdn.example/start", timeout=2.0, max_bytes=1000)
    assert connected == [PUBLIC_IP] * (MAX_REDIRECTS + 1)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://cdn.example/a",
        "gopher://127.0.0.1/",
        "http://user:pass@cdn.example/a",
    ],
)
def test_schemes_and_userinfo_are_rejected(url: str) -> None:
    requests, resolved = _reject(url)
    assert requests == []
    assert resolved == []


def test_streamed_body_stops_at_the_size_cap() -> None:
    class _Endless(httpx.SyncByteStream):
        def __init__(self) -> None:
            self.reads = 0

        def __iter__(self):
            while True:
                self.reads += 1
                if self.reads > 10:
                    raise AssertionError("stream exceeded the size cap")
                yield b"0123456789"

    stream = _Endless()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream, headers={"content-type": "text/plain"})

    body, content_type, _requests, _resolved = _fetch(
        "http://cdn.example/big",
        resolver=lambda host, port: [PUBLIC_IP],
        handler=handler,
        max_bytes=25,
    )
    assert body == b"0123456789" * 2 + b"01234"
    assert content_type == "text/plain"
    assert stream.reads <= 4


def test_timeout_is_enforced_on_the_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        budget = request.extensions["timeout"]
        assert budget["connect"] <= 0.4
        assert budget["read"] <= 0.4
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(ValueError, match="timed out"):
        _fetch(
            "http://cdn.example/slow",
            resolver=lambda host, port: [PUBLIC_IP],
            handler=handler,
            timeout=0.4,
        )


def test_caller_client_cannot_bypass_the_guard(gateway) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"secret", headers={"content-type": "text/plain"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        parsed = parse_attachment(
            AttachmentRef(kind="url", uri="http://127.0.0.1/secret"),
            deadline=Deadline(5),
            gateway=gateway,
            client=client,
        )
    assert parsed.error
    assert "not allowed" in parsed.error


def test_metadata_url_is_an_attachment_error(gateway) -> None:
    result = run(
        {
            "project_id": "ssrf-meta",
            "payload": {
                "raw_input": "给数控机床做一条产品宣传片",
                "attachments": [{"kind": "url", "uri": "http://169.254.169.254/latest/meta-data/"}],
            },
        },
        gateway=gateway,
    )
    assert "not allowed" in result.payload["attachments"][0]["error"]


def test_loopback_image_on_a_public_page_is_not_downloaded(gateway) -> None:
    html = b'<html><title>pump</title><img src="http://127.0.0.1/secret.png" alt="logo"></html>'

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == PUBLIC_IP
        return httpx.Response(200, content=html, headers={"content-type": "text/html"})

    with fetch_hooks(
        resolver=lambda host, port: [PUBLIC_IP],
        transport=httpx.MockTransport(handler),
    ):
        result = run(
            {
                "project_id": "ssrf-img",
                "payload": {
                    "raw_input": "给柱塞泵做产品宣传片",
                    "attachments": [{"kind": "url", "uri": "http://cdn.example/page"}],
                },
            },
            gateway=gateway,
        )
    page = result.payload["attachments"][0]
    assert page["error"] is None
    assert page["images"][0]["uri"] == "http://127.0.0.1/secret.png"
    assert page["images"][0]["bytes"] == 0
    assert page["images"][0]["image_class"] == "logo"
