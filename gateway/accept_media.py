"""Acceptance: mock image, video, and TTS samples land in object storage and decode.

HILATV_LIVE=1 with a positive budget and the matching key also runs one live
call per modality. Missing keys skip that live probe. The mock proof always runs.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
import uuid
from decimal import Decimal
from pathlib import Path

from gateway.budget import limits_from_env
from gateway.cache import MemoryCache
from gateway.media_bytes import decode_png, decode_wav, ffmpeg_decode, sniff_mime
from gateway.pricing import Pricing
from gateway.registry import build_registry
from gateway.router import RouteTable, default_routes_path
from gateway.service import Gateway
from gateway.storage import object_store_from_env
from gateway.store import SqlStore, postgres_reachable


def main() -> int:
    try:
        store = object_store_from_env()
        if store is None:
            print("object storage is not configured (MINIO_* or S3_*)", file=sys.stderr)
            return 1
        if not store.reachable():
            print(f"object storage is not reachable at {store.endpoint}", file=sys.stderr)
            return 1
        summary = _mock_samples(store)
        print(json.dumps(summary, ensure_ascii=False, default=str))
        _maybe_live(store)
        print("T04 accept: PASS")
        return 0
    except Exception:
        traceback.print_exc()
        return 1


def _mock_samples(store: object) -> dict[str, object]:
    project_id = f"accept-t04-{uuid.uuid4()}"
    sql = _sql_store()
    gateway = Gateway(
        routes=RouteTable(default_routes_path()),
        store=sql,
        cache=MemoryCache(),
        pricing=Pricing.load(),
        registry=build_registry(store=store),
        limits_fn=lambda: (False, Decimal("0"), Decimal("0")),
        progress_path=Path(os.environ.get("TMPDIR", "/tmp")) / f"hilatv-t04-{uuid.uuid4()}.md",
        model_overrides_fn=lambda: {},
    )
    image = gateway.generate_image(
        "冷色调金属柱塞泵特写，车间背景虚化", seed=11, project_id=project_id
    )
    video = gateway.generate_video(
        "金属柱塞泵缓慢旋转，冷色工业光",
        seed=11,
        duration_s=5,
        project_id=project_id,
    )
    from workers.compliance.consent_gate import issue_tts_consent

    speech = gateway.tts(
        "这台柱塞泵每天都在稳定工作",
        voice="zh_male_steady",
        seed=11,
        project_id=project_id,
        consent_token=issue_tts_consent("zh_male_steady", None),
    )
    image_again = gateway.generate_image(
        "冷色调金属柱塞泵特写，车间背景虚化",
        seed=11,
        project_id=project_id,
    )
    if image_again != image:
        raise AssertionError("image cache miss")
    downloaded = {
        "image": _check_image(store, image),
        "video": _check_video(store, video),
        "tts": _check_tts(store, speech),
    }
    logs = sql.list_logs(project_id=project_id)
    tasks = [row["task"] for row in logs]
    if tasks[:3] != ["image", "video", "tts"]:
        raise AssertionError(f"unexpected call log tasks: {tasks}")
    for row in logs[:3]:
        if row["provider"] != "mock" or Decimal(str(row["cost_cny"])) != 0:
            raise AssertionError(f"mock call was not logged at cost 0: {row}")
        if row["status"] != "ok":
            raise AssertionError(row["status"])
    if logs[3]["status"] != "cache_hit":
        raise AssertionError("second image call was not a cache hit")
    return {"project_id": project_id, "samples": downloaded, "rows": len(logs)}


def _check_image(store: object, output: dict[str, object]) -> dict[str, object]:
    uri = str(output["uri"])
    _require_object_uri(uri)
    if "no text" not in str(output["prompt"]) or "电话" not in str(output["prompt"]):
        raise AssertionError("image prompt is missing the no-text constraint")
    data = store.get(uri)  # type: ignore[attr-defined]
    width, height, _rgb = decode_png(data)
    ffmpeg_decode(data, ".png")
    return {
        "uri": uri,
        "bytes": len(data),
        "width": width,
        "height": height,
        "mime": output["mime_type"],
    }


def _check_video(store: object, output: dict[str, object]) -> dict[str, object]:
    uri = str(output["uri"])
    _require_object_uri(uri)
    if "电话" not in str(output.get("negative_prompt")):
        raise AssertionError("video is missing the no-text constraint")
    data = store.get(uri)  # type: ignore[attr-defined]
    if sniff_mime(data, "") != "video/mp4":
        raise AssertionError("downloaded video is not an mp4")
    ffmpeg_decode(data, ".mp4")
    return {
        "uri": uri,
        "bytes": len(data),
        "mime": output["mime_type"],
        "duration_s": output["duration_s"],
    }


def _check_tts(store: object, output: dict[str, object]) -> dict[str, object]:
    uri = str(output["uri"])
    _require_object_uri(uri)
    stamps = output.get("timestamps")
    if not isinstance(stamps, list) or not stamps:
        raise AssertionError("tts sample has no word timestamps")
    data = store.get(uri)  # type: ignore[attr-defined]
    duration = decode_wav(data)
    ffmpeg_decode(data, ".wav")
    if duration <= 0:
        raise AssertionError("wav duration is empty")
    return {
        "uri": uri,
        "bytes": len(data),
        "mime": output["mime_type"],
        "duration_s": duration,
        "timestamp_count": len(stamps),
        "voice": output.get("voice"),
    }


def _maybe_live(store: object) -> None:
    live, total, daily = limits_from_env()
    if not live:
        print("live probe skipped (HILATV_LIVE is off)")
        return
    if total <= 0 or daily <= 0:
        print("live probe skipped (budget is 0, live calls stay on mock)")
        return
    from workers.compliance.consent_gate import issue_tts_consent

    registry = build_registry(store=store)
    gateway = Gateway.from_env()
    probes = (
        ("seedream", "image", lambda: gateway.generate_image("冷色调金属泵体特写", seed=1)),
        (
            "seedance",
            "video",
            lambda: gateway.generate_video("金属泵体缓慢旋转", seed=1, duration_s=5),
        ),
        (
            "volc_tts",
            "tts",
            lambda: gateway.tts(
                "稳定工作",
                voice="zh_male_steady",
                seed=1,
                consent_token=issue_tts_consent("zh_male_steady", None),
            ),
        ),
    )
    for provider, kind, call in probes:
        adapter = registry[provider]
        if not adapter.available():
            print(f"live {kind} skipped (no key)")
            continue
        result = call()
        if result.get("mock") is True:
            raise AssertionError(f"live {kind} fell back to mock")
        data = store.get(result["uri"])  # type: ignore[attr-defined]
        suffix = {"image": ".img", "video": ".mp4", "tts": ".wav"}[kind]
        mime = sniff_mime(data, str(result.get("mime_type") or ""))
        if kind == "image" and mime not in {"image/png", "image/jpeg"}:
            raise AssertionError(f"live image mime {mime}")
        if mime == "image/png":
            suffix = ".png"
        elif mime == "image/jpeg":
            suffix = ".jpg"
        elif mime == "audio/mpeg":
            suffix = ".mp3"
        ffmpeg_decode(data, suffix)
        print(
            json.dumps({"live": kind, "uri": result["uri"], "bytes": len(data)}, ensure_ascii=False)
        )


def _require_object_uri(uri: str) -> None:
    if not (uri.startswith("oss://") or uri.startswith("s3://")):
        raise AssertionError(f"expected an object uri, got {uri}")


def _sql_store() -> SqlStore:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if postgres_reachable(database_url):
        return SqlStore.postgres(database_url)
    path = Path(os.environ.get("TMPDIR", "/tmp")) / f"hilatv-t04-{uuid.uuid4()}.sqlite"
    return SqlStore.sqlite(path)


if __name__ == "__main__":
    sys.exit(main())
