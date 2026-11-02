"""Doubao / Volcengine TTS over the v1 HTTP one-shot API.

`with_timestamp=1` asks for word timings when the voice supports them. Audio is
stored as WAV. Subtitles are not burned into a picture; timings are data for
the later render nodes.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from decimal import Decimal
from typing import Any
from uuid import uuid4

import httpx

from gateway.adapters.http_json import billable_postprocess, decode_b64, price_media, request_json
from gateway.constants import DEFAULT_TTS_VOICE, TTS_VOICE_ALIASES, VOLC_TTS_BASE_URL
from gateway.errors import AdapterError
from gateway.media_bytes import decode_wav, extension_for, sniff_mime
from gateway.models import AdapterResult, Invocation
from gateway.pricing import Pricing
from gateway.storage import ObjectStore


class VolcTtsAdapter:
    provider = "volc_tts"
    billable = True
    tasks = frozenset({"tts"})

    def __init__(
        self,
        *,
        base_url: str = VOLC_TTS_BASE_URL,
        api_key: str = "",
        app_id: str = "",
        key_fn: Callable[[], str] | None = None,
        app_id_fn: Callable[[], str] | None = None,
        cluster: str = "volcano_tts",
        default_voice: str = DEFAULT_TTS_VOICE,
        store: ObjectStore | None = None,
        transport: httpx.BaseTransport | None = None,
        pricing: Pricing | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.app_id = app_id
        self.key_fn = key_fn
        self.app_id_fn = app_id_fn
        self.cluster = cluster
        self.default_voice = default_voice
        self.store = store
        self.transport = transport
        self._pricing = pricing

    def available(self) -> bool:
        return bool(self._key().strip() and self._app_id().strip())

    def cost_upper_bound(self, call: Invocation, pricing: Any) -> Decimal | None:
        params = dict(call.params)
        return pricing.upper_bound(call.model, call.prompt, task=call.task, params=params)

    def invoke(self, call: Invocation) -> AdapterResult:
        if self.store is None:
            raise AdapterError("object store is not configured")
        token = self._key().strip()
        app_id = self._app_id().strip()
        if not token or not app_id:
            raise AdapterError("volc tts app id or access token is empty")
        text = call.prompt.strip()
        if not text:
            raise AdapterError("tts text is empty")
        voice = _voice(call, self.default_voice)
        timeout = httpx.Timeout(call.timeout_s)
        with httpx.Client(timeout=timeout, transport=self.transport) as client:
            payload = request_json(
                client,
                "POST",
                f"{self.base_url}/api/v1/tts",
                headers={
                    "Authorization": f"Bearer;{token}",
                    "Content-Type": "application/json",
                },
                body=_body(call, app_id=app_id, voice=voice, cluster=self.cluster),
                provider=self.provider,
            )
        if str(payload.get("code")) not in {"3000", "0"}:
            message = payload.get("message") or payload.get("code")
            raise AdapterError(f"volc tts failed: {message}")
        usage = {"characters": len(text)}
        receipt = AdapterResult(
            provider=self.provider,
            model=call.model,
            output={},
            cost_cny=_decimal(price_media(self._pricing_table(), call, usage)),
            usage=usage,
        )
        with billable_postprocess(receipt):
            encoded = payload.get("data")
            if not isinstance(encoded, str) or not encoded:
                raise AdapterError("volc tts response missing audio")
            raw = decode_b64(encoded)
            mime = sniff_mime(raw, "audio/wav")
            ext = extension_for(mime)
            uri = self.store.put(f"gateway/tts/{uuid4().hex}.{ext}", raw, mime)
            receipt.output = {
                "mock": False,
                "task": "tts",
                "uri": uri,
                "mime_type": mime,
                "text": call.prompt,
                "voice": call.params.get("voice") or self.default_voice,
                "seed": call.seed,
                "duration_s": _duration(payload, raw),
                "timestamps": parse_timestamps(payload),
            }
        return receipt

    def _key(self) -> str:
        if self.key_fn is not None:
            return self.key_fn() or ""
        return self.api_key or ""

    def _app_id(self) -> str:
        if self.app_id_fn is not None:
            return self.app_id_fn() or ""
        return self.app_id or ""

    def _pricing_table(self) -> Pricing:
        if self._pricing is None:
            self._pricing = Pricing.load()
        return self._pricing


def parse_timestamps(payload: dict[str, Any]) -> list[dict[str, object]]:
    words = _word_list(payload)
    items: list[tuple[str, float, float]] = []
    for word in words:
        if not isinstance(word, dict):
            continue
        text = word.get("word") or word.get("text") or ""
        start = _first(word, "start_s", "start_time", "startTime")
        end = _first(word, "end_s", "end_time", "endTime")
        if start is None or end is None:
            continue
        items.append((str(text), float(start), float(end)))
    if not items:
        return []
    scale = 0.001 if max(end for _text, _start, end in items) > 120 else 1.0
    return [
        {
            "text": text,
            "start_s": round(start * scale, 3),
            "end_s": round(end * scale, 3),
        }
        for text, start, end in items
    ]


def _body(call: Invocation, *, app_id: str, voice: str, cluster: str) -> dict[str, Any]:
    speed = call.params.get("speed")
    try:
        speed_ratio = float(speed) if speed is not None else 1.0
    except (TypeError, ValueError):
        speed_ratio = 1.0
    if speed_ratio <= 0:
        speed_ratio = 1.0
    pause = call.params.get("pause_s")
    try:
        pause_s = float(pause) if pause is not None else 0.0
    except (TypeError, ValueError):
        pause_s = 0.0
    if pause_s < 0:
        pause_s = 0.0
    text, text_type = apply_ssml(call.prompt, call.params.get("lexicon"))
    return {
        "app": {"appid": app_id, "token": "hilatv", "cluster": cluster},
        "user": {"uid": call.project_id or "hilatv"},
        "audio": {
            "voice_type": voice,
            "encoding": "wav",
            "rate": 24000,
            "speed_ratio": speed_ratio,
        },
        "request": {
            "reqid": uuid4().hex,
            "text": text,
            "text_type": text_type,
            "operation": "query",
            "with_timestamp": 1,
            # Trailing silence in milliseconds. 0 keeps a line tight; N6 sets this on the CTA.
            "silence_duration": int(round(pause_s * 1000)),
        },
    }


def apply_ssml(text: str, lexicon: object) -> tuple[str, str]:
    """Wrap dictionary hits in SSML phoneme tags. Unmatched lines stay plain text."""

    entries = _lexicon_entries(lexicon)
    if not entries or not text:
        return text, "plain"
    entries.sort(key=lambda item: len(item[0]), reverse=True)
    occupied = [False] * len(text)
    spans: list[tuple[int, int, str, str]] = []
    for term, pinyin in entries:
        start = 0
        while True:
            index = text.find(term, start)
            if index < 0:
                break
            end = index + len(term)
            if not any(occupied[index:end]):
                spans.append((index, end, term, pinyin))
                for cursor in range(index, end):
                    occupied[cursor] = True
            start = index + 1
    if not spans:
        return text, "plain"
    spans.sort()
    parts = ["<speak>"]
    cursor = 0
    for index, end, term, pinyin in spans:
        parts.append(_xml(text[cursor:index]))
        parts.append(f'<phoneme alphabet="py" ph="{_xml(pinyin)}">{_xml(term)}</phoneme>')
        cursor = end
    parts.append(_xml(text[cursor:]))
    parts.append("</speak>")
    return "".join(parts), "ssml"


def _lexicon_entries(lexicon: object) -> list[tuple[str, str]]:
    if not isinstance(lexicon, list):
        return []
    entries: list[tuple[str, str]] = []
    for item in lexicon:
        if not isinstance(item, dict):
            continue
        term = item.get("text")
        pinyin = item.get("pinyin")
        if isinstance(term, str) and term and isinstance(pinyin, str) and pinyin:
            entries.append((term, pinyin))
    return entries


def _xml(value: str) -> str:
    return (
        value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def _voice(call: Invocation, default_voice: str) -> str:
    requested = call.params.get("voice")
    if not isinstance(requested, str) or not requested.strip():
        return default_voice
    name = requested.strip()
    return TTS_VOICE_ALIASES.get(name, name)


def _word_list(payload: dict[str, Any]) -> list[object]:
    if isinstance(payload.get("words"), list):
        return list(payload["words"])
    addition = _as_dict(payload.get("addition"))
    frontend = addition.get("frontend")
    if isinstance(frontend, str):
        frontend = _as_dict(_loads(frontend))
    if isinstance(frontend, dict):
        words = frontend.get("words")
        if isinstance(words, list):
            return list(words)
    return []


def _duration(payload: dict[str, Any], raw: bytes) -> float | None:
    addition = _as_dict(payload.get("addition"))
    raw_duration = addition.get("duration")
    if raw_duration is not None:
        try:
            value = float(raw_duration)
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            return round(value / 1000 if value > 120 else value, 3)
    if sniff_mime(raw, "") == "audio/wav":
        try:
            return round(decode_wav(raw), 3)
        except AdapterError:
            return None
    return None


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _loads(value: str) -> object:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {}


def _first(word: dict[str, Any], *names: str) -> object:
    for name in names:
        if word.get(name) is not None:
            return word[name]
    return None


def _decimal(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


class VolcTtsV3Adapter:
    """豆包语音合成 2.0（新版控制台 API Key，HTTP Chunked 单向流式）。

    官方接口：POST https://openspeech.bytedance.com/api/v3/tts/unidirectional
    鉴权头：X-Api-Key + X-Api-Resource-Id: seed-tts-2.0。
    返回是逐行 JSON，音频数据在 data 字段（base64 PCM）；结束包 code=20000000。
    """

    provider = "volc_tts_v3"
    billable = True
    tasks = frozenset({"tts"})

    def __init__(
        self,
        *,
        base_url: str = "https://openspeech.bytedance.com",
        resource_id: str = "seed-tts-2.0",
        default_voice: str = "zh_female_vv_uranus_bigtts",
        key_fn: Callable[[], str] | None = None,
        speaker_fn: Callable[[], str] | None = None,
        store: ObjectStore | None = None,
        transport: httpx.BaseTransport | None = None,
        pricing: Pricing | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.resource_id = resource_id
        self.default_voice = default_voice
        self.key_fn = key_fn
        self.speaker_fn = speaker_fn
        self.store = store
        self.transport = transport
        self._pricing = pricing

    def available(self) -> bool:
        return bool(self._key().strip() and self._speaker().strip())

    def cost_upper_bound(self, call: Invocation, pricing: Any) -> Decimal | None:
        return pricing.upper_bound(call.model, call.prompt, task=call.task, params={})

    def invoke(self, call: Invocation) -> AdapterResult:
        if self.store is None:
            raise AdapterError("object store is not configured")
        key = self._key().strip()
        speaker = _v3_voice(call, self._speaker() or self.default_voice)
        if not key or not speaker:
            raise AdapterError("volc tts v3 api key or speaker is empty")
        text = call.prompt.strip()
        if not text:
            raise AdapterError("tts text is empty")
        sample_rate = 24000
        body = {
            "user": {"uid": call.project_id or "hilatv"},
            "namespace": "BidirectionalTTS",
            "req_params": {
                "text": text,
                "speaker": speaker,
                "audio_params": {"format": "pcm", "sample_rate": sample_rate},
            },
        }
        headers = {
            "X-Api-Key": key,
            "X-Api-Resource-Id": self.resource_id,
            "X-Api-Request-Id": uuid4().hex,
            "X-Control-Require-Usage-Tokens-Return": "*",
            "Content-Type": "application/json",
        }
        chunks: list[bytes] = []
        words: list[tuple[str, float, float]] = []
        usage: dict[str, Any] = {}
        timeout = httpx.Timeout(call.timeout_s)
        try:
            with httpx.Client(timeout=timeout, transport=self.transport) as client:
                with client.stream(
                    "POST",
                    f"{self.base_url}/api/v3/tts/unidirectional",
                    headers=headers,
                    json=body,
                ) as response:
                    if response.status_code != 200:
                        detail = response.read()[:240].decode("utf-8", "replace")
                        raise AdapterError(f"volc tts v3 HTTP {response.status_code}: {detail}")
                    for line in response.iter_lines():
                        if not line.strip():
                            continue
                        try:
                            item = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        code = item.get("code")
                        if code not in (0, 20000000) and code is not None:
                            raise AdapterError(f"volc tts v3 failed: {item.get('message') or code}")
                        payload = item.get("data")
                        if isinstance(payload, str) and payload:
                            chunks.append(decode_b64(payload))
                        sentence = item.get("sentence")
                        if isinstance(sentence, dict):
                            words.extend(_sentence_words(sentence))
                        if isinstance(item.get("usage"), dict):
                            usage = dict(item["usage"])
        except httpx.HTTPError as exc:
            raise AdapterError(f"volc tts v3 request failed: {exc}") from exc
        if not chunks:
            raise AdapterError("volc tts v3 returned no audio")
        raw = _pcm_to_wav(b"".join(chunks), sample_rate)
        uri = self.store.put(f"gateway/tts/{uuid4().hex}.wav", raw, "audio/wav")
        receipt = AdapterResult(
            provider=self.provider,
            model=call.model,
            output={},
            cost_cny=_decimal(price_media(self._pricing_table(), call, usage)),
            usage={"characters": len(text)},
        )
        receipt.output = {
            "mock": False,
            "task": "tts",
            "uri": uri,
            "mime_type": "audio/wav",
            "text": text,
            "voice": speaker,
            "seed": call.seed,
            "duration_s": round(len(raw) / (sample_rate * 2), 3),
            "timestamps": _v3_timestamps(words),
        }
        return receipt

    def _key(self) -> str:
        return (self.key_fn() if self.key_fn else "") or ""

    def _speaker(self) -> str:
        return (self.speaker_fn() if self.speaker_fn else "") or ""

    def _pricing_table(self) -> Pricing:
        if self._pricing is None:
            self._pricing = Pricing.load()
        return self._pricing


def _v3_voice(call: Invocation, fallback: str) -> str:
    voice = call.params.get("voice")
    return str(voice) if isinstance(voice, str) and voice.strip() else fallback


def _sentence_words(sentence: dict[str, Any]) -> list[tuple[str, float, float]]:
    raw = sentence.get("words")
    if not isinstance(raw, list):
        return []
    items: list[tuple[str, float, float]] = []
    for word in raw:
        if not isinstance(word, dict):
            continue
        start = word.get("startTime", word.get("start_time", word.get("start_s")))
        end = word.get("endTime", word.get("end_time", word.get("end_s")))
        if start is None or end is None:
            continue
        items.append((str(word.get("word") or word.get("text") or ""), float(start), float(end)))
    return items


def _v3_timestamps(words: list[tuple[str, float, float]]) -> list[dict[str, Any]]:
    if not words:
        return []
    scale = 0.001 if max(end for _text, _start, end in words) > 120 else 1.0
    return [
        {"text": text, "start_s": round(start * scale, 3), "end_s": round(end * scale, 3)}
        for text, start, end in words
    ]


def _pcm_to_wav(pcm: bytes, sample_rate: int) -> bytes:
    import io
    import wave

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm)
    return buffer.getvalue()
