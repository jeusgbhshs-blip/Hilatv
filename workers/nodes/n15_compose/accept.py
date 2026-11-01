"""T09 acceptance: fixture shots and audio become a playable, replayable MP4.

Text pixels are compared before the H.264 4:2:0 encode. The same overlay filter
is what burns those PNGs into the master.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from PIL import Image, ImageDraw

from gateway.media_bytes import speech_timestamps
from workers.media.ffmpeg import composite_overlay_png, probe
from workers.media.raster import render_overlay, same_pixels
from workers.nodes.n13_subtitle.node import run as run_subs
from workers.nodes.n13_subtitle.schema import SubtitleCue
from workers.nodes.n14_packaging.node import run as run_pack
from workers.nodes.n14_packaging.schema import PackageElement
from workers.nodes.n15_compose.node import render_timeline
from workers.nodes.n15_compose.node import run as run_edit
from workers.nodes.n15_compose.qa import check
from workers.nodes.n15_compose.schema import Timeline


def main() -> int:
    failures = run_acceptance(Path("/tmp/hilatv-t09-accept"))
    if failures:
        print(f"T09 accept: FAIL {len(failures)}")
        for item in failures:
            print(f"[fail] {item}")
        return 1
    print("T09 accept: playable H.264 30fps MP4, text pixels match, timeline replays")
    return 0


def run_acceptance(work: Path) -> list[str]:
    work.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    try:
        _case(work)
    except Exception as exc:
        failures.append(str(exc))
    return failures


def _case(work: Path) -> None:
    os.environ["HILATV_PROJECT_DIR"] = str(work.resolve())
    logo = Image.new("RGBA", (100, 50))
    ImageDraw.Draw(logo).rectangle((25, 12, 74, 37), fill=(235, 31, 89, 255))
    logo_path = work / "source-logo.png"
    logo.save(logo_path)
    language = "zh"
    voice = "这台高压柱塞泵以三十兆帕稳定运行，适合连续作业的工厂产线。"
    audio_s = speech_timestamps(voice, language=language)[1]
    duration = max(2.0, round(audio_s + 0.2, 3))
    raw = _storyboard(voice, language, duration)
    raw["brand_kit"]["logo"]["primary"] = str(logo_path.resolve())
    subs = run_subs({"project_id": "accept-t09", "payload": {**raw, "work_dir": str(work / "n13")}})
    cues = [SubtitleCue.model_validate(item) for item in subs.payload["cues"]]
    if not cues:
        raise AssertionError("no subtitles")
    if any(cue.alignment_error_ms > 100 for cue in cues):
        raise AssertionError("subtitle alignment is over 100ms")
    if any(sum(1 for char in cue.text if not char.isspace()) > 16 for cue in cues):
        raise AssertionError("a Chinese subtitle line is over 16 characters")
    plain = run_subs(
        {
            "project_id": "accept-t09-plain",
            "payload": {**raw, "subject_boxes": [], "work_dir": str(work / "n13-plain")},
        }
    )
    lifted = cues[0].y_ratio
    if not lifted < SubtitleCue.model_validate(plain.payload["cues"][0]).y_ratio:
        raise AssertionError("subtitle did not move up off the product")
    packed = run_pack(
        {
            "project_id": "accept-t09",
            "payload": {
                "script": raw["script"],
                "brand_kit": raw["brand_kit"],
                "brief": raw["brief"],
                "intro": "fade",
                "width": 640,
                "height": 360,
                "work_dir": str(work / "n14"),
            },
        }
    )
    elements = [PackageElement.model_validate(item) for item in packed.payload["elements"]]
    if packed.payload["intro_s"] > 2:
        raise AssertionError("intro is longer than 2s")
    if not any(item.kind == "outro_logo" for item in elements):
        raise AssertionError("ending has no logo")
    cta = next(item for item in elements if item.kind == "outro_cta")
    if "0532-88881234" not in cta.text:
        raise AssertionError("ending CTA is missing the phone")
    badge = next(item for item in elements if item.text == "¥12800")
    _pixels(badge, cta, elements)
    edited = run_edit(
        {
            "project_id": "accept-t09",
            "payload": {
                "script": raw["script"],
                "voiceovers": raw["voiceovers"],
                "cues": subs.payload["cues"],
                "elements": packed.payload["elements"],
                "brand_kit": raw["brand_kit"],
                "brief": raw["brief"],
                "intro_s": packed.payload["intro_s"],
                "outro_s": packed.payload["outro_s"],
                "width": 640,
                "height": 360,
                "work_dir": str(work / "n15"),
            },
        }
    )
    timeline = check(edited)
    master = Path(edited.payload["exports"]["master"])
    info = probe(master)
    if info["codec"] != "h264" or abs(float(info["fps"]) - 30) > 0.05:
        raise AssertionError(f"master is {info}")
    _replay(timeline, master)
    _overlay_proof(work, badge)
    nosub = Path(edited.payload["exports"]["nosub"]).read_bytes()
    novo = Path(edited.payload["exports"]["novo"])
    if hashlib.sha256(master.read_bytes()).hexdigest() == hashlib.sha256(nosub).hexdigest():
        raise AssertionError("no-subtitle export matches the master")
    if probe(novo)["audio_codecs"]:
        raise AssertionError("no-voiceover export has audio")
    saved = json.loads(Path(edited.payload["timeline_path"]).read_text(encoding="utf-8"))
    if Timeline.model_validate(saved).duration_s != timeline.duration_s:
        raise AssertionError("timeline JSON does not round-trip")
    print(
        f"[ok] master {info['width']}x{info['height']} {info['fps']:.0f}fps "
        f"{info['duration_s']:.2f}s cues={len(cues)} intro={packed.payload['intro_template']}"
    )


def _pixels(badge: PackageElement, cta: PackageElement, elements: list[PackageElement]) -> None:
    if not same_pixels(Image.open(badge.png_path), render_overlay(**badge.spec)):
        raise AssertionError("price badge pixels differ from the reference render")
    if not same_pixels(Image.open(cta.png_path), render_overlay(**cta.spec)):
        raise AssertionError("phone CTA pixels differ from the reference render")
    logo = next(item for item in elements if item.kind == "outro_logo")
    source = Path(logo.spec["source_uri"])
    if not same_pixels(Image.open(logo.png_path), Image.open(source)):
        raise AssertionError("logo pixels differ from the independent uploaded source")


def _overlay_proof(work: Path, badge: PackageElement) -> None:
    plate = Image.new("RGBA", (640, 360), (26, 35, 50, 255))
    plate_path = work / "plate.png"
    plate.save(plate_path)
    overlay = Image.open(badge.png_path).convert("RGBA")
    reference = plate.copy()
    reference.alpha_composite(overlay, (24, 40))
    dest = work / "proof.png"
    composite_overlay_png(plate_path, Path(badge.png_path), (24, 40), dest)
    got = Image.open(dest).convert("RGB")
    if got.tobytes() != reference.convert("RGB").tobytes():
        raise AssertionError("ffmpeg overlay pixels differ from the reference composite")


def _replay(timeline: Timeline, master: Path) -> None:
    dest = master.with_name("replay.mp4")
    render_timeline(timeline, dest, variant="master")
    if hashlib.sha256(master.read_bytes()).digest() != hashlib.sha256(dest.read_bytes()).digest():
        raise AssertionError("replaying the timeline JSON did not reproduce the MP4")


def _storyboard(voice: str, language: str, duration: float) -> dict:
    stamps, audio = speech_timestamps(voice, language=language)
    return {
        "script": {
            "script_id": "script-t09",
            "brief_id": "brief-t09",
            "language": language,
            "sections": [],
            "shots": [
                {
                    "shot_id": "S01",
                    "order": 1,
                    "duration_s": duration,
                    "purpose": "展示核心卖点：高压",
                    "visual": "柱塞泵特写，金属表面，画面里没有文字",
                    "shot_size": "close_up",
                    "camera": "locked_off",
                    "subject_refs": ["product:HP-300"],
                    "scene_ref": "scene:workshop",
                    "voiceover": voice,
                    "on_screen_text": [
                        {
                            "text": "¥12800",
                            "style": "price_badge",
                            "in": 0.2,
                            "out": min(1.8, duration),
                        },
                        {
                            "text": "30 MPa",
                            "style": "spec_badge",
                            "in": 0.2,
                            "out": min(1.8, duration),
                        },
                    ],
                    "transition_out": "cut",
                    "generation_mode": "image_to_video",
                    "status": "pending",
                }
            ],
        },
        "voiceovers": [
            {
                "shot_id": "S01",
                "uri": "mock://S01",
                "voice": "zh_male_steady",
                "speed": 1.0,
                "pause_s": 0.0,
                "audio_s": audio,
                "hold_s": max(0.0, duration - audio),
                "duration_s": duration,
                "timestamps": stamps,
                "transcript": voice,
                "cer": 0.0,
                "loudness_dbfs": -16.0,
                "clipped": False,
                "role": "body",
            }
        ],
        "brand_kit": {
            "brand_id": "brand-t09",
            "company_name": "青岛某某机械有限公司",
            "industry": "manufacturing",
            "logo": {
                "primary": "oss://logo.png",
                "mono_white": "oss://logo-w.png",
                "safe_area_ratio": 0.2,
            },
            "colors": {"primary": "#0A3D91", "secondary": "#FFFFFF", "accent": "#F5A623"},
            "fonts": {"title": "NotoSansSC-Bold", "body": "NotoSansSC-Regular"},
            "products": [
                {
                    "product_id": "HP-300",
                    "name": "高压柱塞泵",
                    "photos": [],
                    "cutouts": [],
                    "selling_points": ["压力 30 MPa"],
                    "forbidden_changes": ["铭牌文字"],
                }
            ],
            "people": [],
            "voice": {"tts_voice": "zh_male_steady", "speed": 1.0},
            "tone": "专业",
            "banned_words": ["最好"],
            "cta": {"phone": "0532-88881234", "website": "https://example.com", "wechat_qr": ""},
        },
        "brief": {
            "brief_id": "brief-t09",
            "raw_input": "给我们的柱塞泵做条片子，标上价格和电话",
            "goal": "获客",
            "platform": ["YouTube"],
            "duration_s": 15,
            "aspect_ratios": ["16:9"],
            "languages": [language],
            "video_type": "product_showcase",
            "audience": "采购",
            "must_include": ["30 MPa"],
            "style": "工业",
            "assumptions": [],
            "open_questions": [],
        },
        "subject_boxes": [{"shot_id": "S01", "x": 0.1, "y": 0.62, "w": 0.8, "h": 0.38}],
        "width": 640,
        "height": 360,
    }


if __name__ == "__main__":
    raise SystemExit(main())
