"""Read URLs, PDFs, and images into text facts. Models only see the text."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from pypdf import PdfReader

from workers.nodes.n01_brief.prompts import render_classify, system_prompt
from workers.nodes.n01_brief.schema import AttachmentRef, ImageLabel
from workers.nodes.n01_brief.signals import AttachmentFacts, extract_facts

_IMAGE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("logo", ("logo", "标志", "商标", "徽标")),
    ("person", ("person", "portrait", "人物", "老板", "讲师", "人像", "员工")),
    ("scene", ("scene", "workshop", "场景", "车间", "工厂", "店内", "环境", "门头")),
    ("product", ("product", "产品", "sku", "商品", "包装", "正面", "侧面")),
)
_USER_AGENT = "HiLatvN1/0.1"


@dataclass
class ParsedAttachment:
    kind: str
    uri: str
    filename: str = ""
    text: str = ""
    title: str = ""
    images: list[dict[str, Any]] = field(default_factory=list)
    products: list[str] = field(default_factory=list)
    selling_points: list[str] = field(default_factory=list)
    specs: list[str] = field(default_factory=list)
    image_class: str | None = None
    classifier: str | None = None
    error: str | None = None

    def facts(self) -> AttachmentFacts:
        return AttachmentFacts(
            products=list(self.products),
            selling_points=list(self.selling_points),
            specs=list(self.specs),
            text=self.text,
        )

    def as_dict(self) -> dict[str, Any]:
        excerpt = self.text.strip()
        if len(excerpt) > 2000:
            excerpt = excerpt[:2000] + "…"
        payload: dict[str, Any] = {
            "kind": self.kind,
            "uri": self.uri,
            "filename": self.filename,
            "title": self.title,
            "text_excerpt": excerpt,
            "images": self.images,
            "products": self.products,
            "selling_points": self.selling_points,
            "specs": self.specs,
            "error": self.error,
        }
        if self.image_class:
            payload["image_class"] = self.image_class
            payload["classifier"] = self.classifier
        return payload


class Deadline:
    """Node-level timeout. Attachment and model calls check it before and after."""

    def __init__(self, timeout_s: float) -> None:
        import time

        if timeout_s <= 0:
            raise TimeoutError("n01_brief exceeded timeout")
        self._time = time
        self.deadline = time.monotonic() + timeout_s

    def remaining(self) -> float:
        left = self.deadline - self._time.monotonic()
        if left <= 0:
            raise TimeoutError("n01_brief exceeded timeout")
        return left

    def check(self) -> None:
        self.remaining()


def parse_attachment(
    attachment: AttachmentRef,
    *,
    deadline: Deadline,
    gateway: Any,
    client: httpx.Client | None = None,
    project_id: str | None = None,
    shot_id: str | None = None,
    attempt: int | None = None,
) -> ParsedAttachment:
    deadline.check()
    trace = {"project_id": project_id, "shot_id": shot_id, "attempt": attempt}
    try:
        if attachment.kind == "url":
            return _parse_url(
                attachment, deadline=deadline, gateway=gateway, client=client, trace=trace
            )
        if attachment.kind == "pdf":
            return _parse_pdf(attachment)
        return _parse_image(attachment, deadline=deadline, gateway=gateway, trace=trace)
    except TimeoutError:
        raise
    except Exception as exc:
        return ParsedAttachment(
            kind=attachment.kind,
            uri=attachment.uri,
            filename=attachment.filename or Path(attachment.uri).name,
            error=str(exc),
        )


def classify_metadata(*parts: str) -> str | None:
    blob = " ".join(part for part in parts if part).lower()
    for kind, words in _IMAGE_KEYWORDS:
        if any(word.lower() in blob for word in words):
            return kind
    return None


def _parse_pdf(attachment: AttachmentRef) -> ParsedAttachment:
    path = _local_file(attachment.uri)
    reader = PdfReader(str(path))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    facts = extract_facts(text)
    return ParsedAttachment(
        kind="pdf",
        uri=attachment.uri,
        filename=attachment.filename or path.name,
        text=facts.text,
        products=facts.products,
        selling_points=facts.selling_points,
        specs=facts.specs,
    )


def _parse_image(
    attachment: AttachmentRef,
    *,
    deadline: Deadline,
    gateway: Any,
    trace: dict[str, Any],
) -> ParsedAttachment:
    path = _local_file(attachment.uri)
    filename = attachment.filename or path.name
    kind, how = _classify(filename, "", str(path), deadline=deadline, gateway=gateway, trace=trace)
    return ParsedAttachment(
        kind="image",
        uri=attachment.uri,
        filename=filename,
        text=filename,
        image_class=kind,
        classifier=how,
        images=[
            {
                "uri": attachment.uri,
                "alt": "",
                "image_class": kind,
                "classifier": how,
                "bytes": path.stat().st_size,
            }
        ],
    )


def _parse_url(
    attachment: AttachmentRef,
    *,
    deadline: Deadline,
    gateway: Any,
    client: httpx.Client | None,
    trace: dict[str, Any],
) -> ParsedAttachment:
    parsed = urlparse(attachment.uri)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("url attachment must be http or https")
    timeout, max_bytes = _fetch_limits(deadline)
    body, content_type = _get(attachment.uri, timeout=timeout, max_bytes=max_bytes, client=client)
    if "pdf" in content_type or attachment.uri.lower().endswith(".pdf"):
        text = _pdf_bytes(body)
        facts = extract_facts(text)
        return ParsedAttachment(
            kind="url",
            uri=attachment.uri,
            filename=attachment.filename or Path(parsed.path).name,
            text=facts.text,
            products=facts.products,
            selling_points=facts.selling_points,
            specs=facts.specs,
        )
    if content_type.startswith("image/"):
        filename = attachment.filename or Path(parsed.path).name
        kind, how = _classify(
            filename, "", attachment.uri, deadline=deadline, gateway=gateway, trace=trace
        )
        return ParsedAttachment(
            kind="url",
            uri=attachment.uri,
            filename=filename,
            image_class=kind,
            classifier=how,
            images=[
                {
                    "uri": attachment.uri,
                    "alt": "",
                    "image_class": kind,
                    "classifier": how,
                    "bytes": len(body),
                }
            ],
        )
    html = body.decode("utf-8", errors="replace")
    page = _PageParser()
    page.feed(html)
    text = "\n".join(part.strip() for part in page.parts if part.strip())
    facts = extract_facts(f"{page.title}\n{text}")
    images = _page_images(
        page.images,
        page_url=attachment.uri,
        deadline=deadline,
        gateway=gateway,
        client=client,
        trace=trace,
    )
    return ParsedAttachment(
        kind="url",
        uri=attachment.uri,
        filename=attachment.filename or Path(parsed.path).name,
        text=facts.text,
        title=page.title.strip(),
        images=images,
        products=facts.products,
        selling_points=facts.selling_points,
        specs=facts.specs,
    )


def _page_images(
    found: list[tuple[str, str]],
    *,
    page_url: str,
    deadline: Deadline,
    gateway: Any,
    client: httpx.Client | None,
    trace: dict[str, Any],
) -> list[dict[str, Any]]:
    images: list[dict[str, Any]] = []
    timeout, max_bytes = _fetch_limits(deadline)
    for src, alt in found[:4]:
        deadline.check()
        absolute = urljoin(page_url, src)
        filename = Path(urlparse(absolute).path).name
        size = 0
        try:
            body, _content_type = _get(
                absolute, timeout=timeout, max_bytes=max_bytes, client=client
            )
            size = len(body)
        except Exception:
            size = 0
        kind, how = _classify(
            filename, alt, absolute, deadline=deadline, gateway=gateway, trace=trace
        )
        images.append(
            {
                "uri": absolute,
                "alt": alt,
                "image_class": kind,
                "classifier": how,
                "bytes": size,
            }
        )
    return images


def _classify(
    filename: str,
    alt: str,
    source: str,
    *,
    deadline: Deadline,
    gateway: Any,
    trace: dict[str, Any],
) -> tuple[str, str]:
    found = classify_metadata(filename, alt, source)
    if found:
        return found, "metadata"
    deadline.check()
    try:
        raw = gateway.generate_text(
            render_classify(filename=filename or "unknown", alt=alt, source=source),
            schema=ImageLabel,
            system=system_prompt(),
            seed=0,
            node="n01_brief",
            project_id=trace.get("project_id"),
            shot_id=trace.get("shot_id"),
            attempt=trace.get("attempt"),
        )
        label = ImageLabel.model_validate(raw)
    except Exception:
        return "product", "model"
    return label.kind, "model"


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.images: list[tuple[str, str]] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        name = tag.lower()
        if name in {"script", "style", "noscript"}:
            self._skip += 1
        if name == "title":
            self._in_title = True
        if name == "img":
            attr = {key.lower(): value or "" for key, value in attrs}
            src = attr.get("src") or ""
            if src:
                self.images.append((src, attr.get("alt") or ""))

    def handle_endtag(self, tag: str) -> None:
        name = tag.lower()
        if name in {"script", "style", "noscript"} and self._skip:
            self._skip -= 1
        if name == "title":
            self._in_title = False
        if name in {"p", "div", "li", "h1", "h2", "h3", "br", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._in_title:
            self.title += data
            return
        self.parts.append(data)


def _local_file(uri: str) -> Path:
    path = Path(uri)
    if not path.is_file():
        raise FileNotFoundError(uri)
    return path


def _pdf_bytes(data: bytes) -> str:
    import io

    reader = PdfReader(io.BytesIO(data))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _fetch_limits(deadline: Deadline) -> tuple[float, int]:
    configured = float(os.getenv("HILATV_N1_FETCH_TIMEOUT_S", "10") or "10")
    max_bytes = int(os.getenv("HILATV_N1_FETCH_MAX_BYTES", "2000000") or "2000000")
    return min(configured, deadline.remaining()), max(1, max_bytes)


def _get(
    url: str,
    *,
    timeout: float,
    max_bytes: int,
    client: httpx.Client | None,
) -> tuple[bytes, str]:
    headers = {"User-Agent": _USER_AGENT}
    owns_client = client is None
    http = client or httpx.Client(timeout=timeout, follow_redirects=True, headers=headers)
    try:
        with http.stream("GET", url) as response:
            response.raise_for_status()
            content_type = (response.headers.get("content-type") or "").split(";", 1)[0].strip()
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_bytes():
                chunks.append(chunk)
                size += len(chunk)
                if size >= max_bytes:
                    break
            return b"".join(chunks)[:max_bytes], content_type.lower()
    finally:
        if owns_client:
            http.close()
