"""One test per fallback level, plus a flawed shot that must not reach the film."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from workers.fallback.direct import direct_shots
from workers.fallback.encode import motion_graphic
from workers.fallback.files import read_bytes
from workers.media.ffmpeg import playable, probe
from workers.nodes.n15_compose.node import run as compose
from workers.qa.budget_store import project_folder
from workers.qa.frames import sample_frames, write_mp4
from workers.qa.rules import inspect_image
from workers.qa.samples import _font
from workers.schemas.asset import Candidate, QAReport, QAScores
from workers.schemas.brand import BrandKit
from workers.schemas.script import Script

WIDTH = 320
HEIGHT = 180
MAGENTA = (255, 0, 200)


def test_level1_regenerates_through_the_gateway(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_LIVE", "1")
    project = "lvl1"
    folder = project_folder(project)
    folder.mkdir(parents=True)
    made = folder / "clean.mp4"
    motion_graphic(made, size=(WIDTH, HEIGHT), frames=8, cutout=None)
    gateway = _VideoOk(made, judge=True)

    clip, note = _run(project, gateway, key=None)

    assert note.fallback_level == 1
    assert note.fallback_name == "regenerate"
    assert note.degraded is True
    assert note.qa_passed is False
    assert note.reviewed is False
    assert note.needs_review is False
    assert "建议补拍" not in note.note
    assert gateway.routes == ["product"]
    assert _budget_used(project) == 1
    _playable(Path(clip.path))
    assert probe(Path(clip.path))["codec"] == "h264"


def test_level2_uses_a_keyframe_that_passed_qa(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_LIVE", "1")
    project = "lvl2"
    key = _scene(project_folder(project) / "key.png")
    gateway = _ImageToVideo(_scene_video(project_folder(project) / "i2v.mp4"))

    clip, note = _run(project, gateway, key=key)

    assert note.fallback_level == 2
    assert note.fallback_name == "image_to_video"
    assert note.qa_passed is False
    assert note.reviewed is False
    assert gateway.saw_image is True
    assert _budget_used(project) == 2
    _playable(Path(clip.path))


def test_level3_ken_burns_when_the_video_model_keeps_failing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_LIVE", "1")
    project = "lvl3"
    key = _scene(project_folder(project) / "key.png")
    gateway = _ReviewedDown()

    clip, note = _run(project, gateway, key=key)

    assert note.fallback_level == 3
    assert note.camera == "ken_burns"
    assert note.qa_passed is False
    assert note.reviewed is False
    assert note.needs_review is False
    frames = sample_frames(Path(clip.path))
    assert len(frames) >= 2
    assert frames[0].tobytes() != frames[-1].tobytes()
    _playable(Path(clip.path))


def test_level3_parallax_uses_a_product_cutout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_LIVE", "1")
    project = "lvl3p"
    root = project_folder(project)
    key = _scene(root / "key.png")
    cutout = _cutout(root / "cutout.png")
    gateway = _ReviewedDown()

    _clip, note = _run(project, gateway, key=key, brand=_brand(cutout))

    assert note.fallback_level == 3
    assert note.camera == "ken_burns+parallax"
    frames = sample_frames(Path(note.media_path))
    assert frames[0].tobytes() != frames[-1].tobytes()


def test_level4_motion_graphics_always_renders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    project = "lvl4"
    root = project_folder(project)
    cutout = _cutout(root / "cutout.png")
    gateway = _VideoDown()

    clip, note = _run(project, gateway, key=None, brand=_brand(cutout), mode="motion_graphics")

    assert note.fallback_level == 4
    assert note.fallback_name == "motion_graphics"
    assert note.subject == "cutout"
    assert note.qa_passed is False
    assert note.reviewed is False
    assert note.needs_review is True
    assert clip.cards and clip.cards[0].text == "压力稳定"
    assert "建议补拍" not in json.dumps(note.model_dump(), ensure_ascii=False)
    plate = sample_frames(Path(clip.path))
    assert not any(item.code == "extra_text" for item in inspect_image(plate[0]))
    _playable(Path(clip.path))


def test_a_qa_rejected_shot_is_absent_from_the_film(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    project = "lvlbad"
    root = project_folder(project)
    root.mkdir(parents=True, exist_ok=True)
    flawed = root / "flawed.mp4"
    _flawed_clip(flawed)
    flaws = inspect_image(sample_frames(flawed)[0])
    assert any(item.code in {"extra_text", "garbled_text"} for item in flaws)
    key = _scene(root / "key.png")
    gateway = _VideoDown()
    script = _script()
    videos = [_candidate("S01", str(flawed), node="N10", frame="video")]
    keys = [_candidate("S01", str(key), node="N8", frame="first")]

    result = direct_shots(
        project_id=project,
        script=script,
        videos=videos,
        keyframes=keys,
        brand_kit=None,
        width=WIDTH,
        height=HEIGHT,
        gateway=gateway,
    )
    note = result.notes[0]
    assert note.fallback_level == 4
    assert note.needs_review is True
    assert note.qa_passed is False
    assert note.reviewed is False
    assert _has_magenta(Path(note.media_path)) is False

    logo = root / "logo.png"
    Image.new("RGBA", (16, 16), (255, 255, 255, 255)).save(logo)
    composed = compose(
        {
            "project_id": project,
            "payload": {
                "work_dir": str(root / "edit"),
                "intro_s": 0,
                "outro_s": 0.4,
                "width": WIDTH,
                "height": HEIGHT,
                "script": script.model_dump(mode="json"),
                "shot_clips": [item.model_dump(mode="json") for item in result.clips],
                "elements": [
                    {
                        "element_id": "outro-logo",
                        "kind": "outro_logo",
                        "text": "",
                        "start_s": 0.0,
                        "end_s": 0.4,
                        "anchor": "center",
                        "y_ratio": 0.4,
                        "png_path": str(logo),
                    },
                    {
                        "element_id": "outro-cta",
                        "kind": "outro_cta",
                        "text": "联系我们",
                        "start_s": 0.0,
                        "end_s": 0.4,
                        "anchor": "center",
                        "y_ratio": 0.6,
                        "png_path": str(logo),
                    },
                ],
            },
        },
        timeout_s=60,
        max_attempts=1,
    )
    master = Path(composed.payload["exports"]["master"])
    info = probe(master)
    playable(master)
    timeline = composed.payload["timeline"]
    assert abs(info["duration_s"] - timeline["duration_s"]) < 0.15
    shot_ids = [clip["clip_id"] for clip in timeline["clips"]]
    assert "S01" in shot_ids
    assert shot_ids[-1] == "outro"
    assert _has_magenta(master) is False


def test_remote_and_outside_paths_are_not_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    assert read_bytes("http://127.0.0.1/cutout.png") is None
    assert read_bytes("/etc/passwd") is None


def _run(
    project: str,
    gateway: object,
    *,
    key: Path | None,
    brand: BrandKit | None = None,
    mode: str = "image_to_video",
):
    script = _script(mode)
    keys = [] if key is None else [_candidate("S01", str(key), node="N8", frame="first")]
    result = direct_shots(
        project_id=project,
        script=script,
        videos=[],
        keyframes=keys,
        brand_kit=brand,
        width=WIDTH,
        height=HEIGHT,
        gateway=gateway,
    )
    return result.clips[0], result.notes[0]


def _script(mode: str = "image_to_video") -> Script:
    return Script.model_validate(
        {
            "script_id": "script-1",
            "brief_id": "brief-1",
            "language": "zh",
            "sections": [],
            "shots": [
                {
                    "shot_id": "S01",
                    "order": 1,
                    "duration_s": 1.0,
                    "purpose": "卖点",
                    "visual": "产品居中，画面没有文字",
                    "shot_size": "中景",
                    "camera": "locked_off",
                    "subject_refs": ["product:pump"],
                    "scene_ref": "scene:shop",
                    "voiceover": "压力稳定。",
                    "on_screen_text": [
                        {"text": "压力稳定", "style": "badge", "in": 0.1, "out": 0.8}
                    ],
                    "transition_out": "cut",
                    "generation_mode": mode,
                    "status": "pending",
                }
            ],
        }
    )


def _candidate(shot_id: str, uri: str, *, node: str, frame: str) -> Candidate:
    return Candidate(
        candidate_id=f"{shot_id}-{frame}",
        shot_id=shot_id,
        node=node,
        model="mock-image" if node == "N8" else "mock-video",
        params={"frame": frame, "prompt": "An unmarked pump.", "seed": 3, "shot_type": "product"},
        uri=uri,
        qa=QAReport(
            scores=QAScores(
                product_fidelity=0,
                motion_quality=0,
                aesthetics=0,
                prompt_match=0,
                artifact_free=0,
            ),
            hard_fail=["not_reviewed"],
            total=0,
            evaluator="not-reviewed",
            notes="not reviewed",
            visual_reviewed=False,
        ),
        selected=True,
    )


def _scene(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (WIDTH, HEIGHT), (24, 52, 96))
    draw = ImageDraw.Draw(image)
    draw.ellipse((120, 40, 200, 140), fill=(70, 130, 190))
    image.save(path)
    return path


def _cutout(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((130, 50, 190, 130), radius=8, fill=(20, 90, 160, 255))
    image.save(path)
    return path


def _scene_video(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    motion_graphic(path, size=(WIDTH, HEIGHT), frames=8, cutout=None, rgb=(18, 70, 60))
    return path


def _flawed_clip(path: Path) -> None:
    frame = Image.new("RGB", (WIDTH, HEIGHT), (236, 236, 236))
    draw = ImageDraw.Draw(frame)
    draw.rectangle((110, 50, 210, 130), fill=(80, 110, 140))
    draw.rectangle((16, 16, 48, 48), fill=MAGENTA)
    draw.text((24, 150), "促销价 99", fill=(0, 0, 0), font=_font(22))
    write_mp4([frame, frame, frame, frame], path, fps=8)


def _brand(cutout: Path) -> BrandKit:
    return BrandKit.model_validate(
        {
            "brand_id": "brand-1",
            "company_name": "测试机械",
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
                    "product_id": "pump",
                    "name": "泵",
                    "photos": [],
                    "cutouts": [str(cutout)],
                    "selling_points": [],
                    "forbidden_changes": [],
                }
            ],
            "people": [
                {
                    "person_id": "p1",
                    "role": "工程师",
                    "photos": [str(cutout.parent / "missing-person.png")],
                    "consent": False,
                    "voice_id": None,
                }
            ],
            "voice": {"tts_voice": "zh_male_steady", "speed": 1},
            "tone": "专业",
            "cta": {"phone": "", "website": "", "wechat_qr": ""},
        }
    )


def _budget_used(project: str) -> int:
    raw = json.loads((project_folder(project) / "regen_budget.json").read_text(encoding="utf-8"))
    assert raw["increase_only"] is True
    return int(raw["used"])


def _playable(path: Path) -> None:
    info = probe(path)
    assert info["codec"] == "h264"
    assert float(info["duration_s"]) > 0
    playable(path)


def _has_magenta(path: Path) -> bool:
    for frame in sample_frames(path):
        colors = frame.getcolors(maxcolors=200000) or []
        for _count, rgb in colors:
            if not isinstance(rgb, tuple):
                continue
            distance = (
                abs(rgb[0] - MAGENTA[0]) + abs(rgb[1] - MAGENTA[1]) + abs(rgb[2] - MAGENTA[2])
            )
            if distance <= 24:
                return True
    return False


def _clean_opinion() -> dict[str, object]:
    return {
        "scores": {
            "product_fidelity": 9,
            "motion_quality": 8,
            "aesthetics": 8,
            "prompt_match": 9,
            "artifact_free": 9,
        },
        "hard_fail": [],
        "total": 8.6,
        "evaluator": "vlm-judge-test",
        "notes": "clean",
    }


class _VideoOk:
    def __init__(self, path: Path, *, judge: bool = False) -> None:
        self.path = path
        self.routes: list[str] = []
        self.seeds: list[object] = []
        self._judge = judge

    def generate_video(self, _prompt: str, **kwargs: object) -> dict[str, str]:
        shot_type = kwargs.get("shot_type")
        self.routes.append(str(shot_type or ""))
        self.seeds.append(kwargs.get("seed"))
        return {"uri": str(self.path)}

    def judge(self, _prompt: str, **_kwargs: object) -> dict[str, object]:
        if not self._judge:
            raise RuntimeError("vlm unavailable")
        return _clean_opinion()


class _ImageToVideo:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.saw_image = False

    def generate_video(self, _prompt: str, **kwargs: object) -> dict[str, str]:
        params = kwargs.get("params")
        if isinstance(params, dict) and params.get("image_b64"):
            self.saw_image = True
            return {"uri": str(self.path)}
        raise RuntimeError("video model failed")

    def judge(self, _prompt: str, **_kwargs: object) -> dict[str, object]:
        return _clean_opinion()


class _VideoDown:
    def generate_video(self, _prompt: str, **_kwargs: object) -> dict[str, str]:
        raise RuntimeError("video model failed")

    def generate_image(self, _prompt: str, **_kwargs: object) -> dict[str, str]:
        raise RuntimeError("image model failed")


class _ReviewedDown(_VideoDown):
    def judge(self, _prompt: str, **_kwargs: object) -> dict[str, object]:
        return _clean_opinion()


def test_vlm_error_drops_to_level_4(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_LIVE", "1")
    project = "lvl-vlm-err"
    folder = project_folder(project)
    folder.mkdir(parents=True)
    made = folder / "clean.mp4"
    motion_graphic(made, size=(WIDTH, HEIGHT), frames=8, cutout=None)
    gateway = _VideoOk(made, judge=False)

    clip, note = _run(project, gateway, key=None)

    assert note.fallback_level == 4
    assert note.needs_review is True
    assert note.qa_passed is False
    assert note.reviewed is False
    assert "judge_unavailable" in note.hard_fail or note.hard_fail
    _playable(Path(clip.path))


def test_mock_judge_drops_to_level_4(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_LIVE", "1")
    project = "lvl-mock-judge"
    folder = project_folder(project)
    folder.mkdir(parents=True)
    made = folder / "clean.mp4"
    motion_graphic(made, size=(WIDTH, HEIGHT), frames=8, cutout=None)

    class MockJudge(_VideoOk):
        def judge(self, _prompt: str, **_kwargs: object) -> dict[str, object]:
            return {
                "scores": {
                    "product_fidelity": 0,
                    "motion_quality": 0,
                    "aesthetics": 0,
                    "prompt_match": 0,
                    "artifact_free": 0,
                },
                "hard_fail": [],
                "total": 0,
                "evaluator": "mock",
                "notes": "mock",
            }

    _clip, note = _run(project, MockJudge(made, judge=True), key=None)

    assert note.fallback_level == 4
    assert note.needs_review is True
    assert note.qa_passed is False
    assert note.reviewed is False


def test_seed_changes_when_the_budget_or_attempt_changes() -> None:
    from workers.fallback.direct import _seed

    first = _seed("S01", 1, budget_used=1, attempt=1)
    spent = _seed("S01", 1, budget_used=2, attempt=1)
    retried = _seed("S01", 1, budget_used=1, attempt=2)
    assert first == _seed("S01", 1, budget_used=1, attempt=1)
    assert len({first, spent, retried}) == 3
