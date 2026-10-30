"""A capped project does not spend another video call. Logo URLs go through the SSRF guard."""

import json

from workers.workflow.revise import _maybe_fetch_logo, revise_project
from workers.workflow.store import init_project, project_path, update_snapshot
from workers.workflow.versions import hashes


def _script() -> dict:
    def shot(shot_id: str, order: int) -> dict:
        return {
            "shot_id": shot_id,
            "order": order,
            "duration_s": 2.0,
            "purpose": "展示产品",
            "visual": "车间里的泵。画面无任何文字、无 Logo、无价格、无电话号码。",
            "shot_size": "medium",
            "camera": "locked_off",
            "subject_refs": ["product:HP-300"],
            "scene_ref": "scene:workshop",
            "voiceover": "泵已经就位。",
            "on_screen_text": [],
            "transition_out": "cut",
            "generation_mode": "image_to_video",
            "status": "pending",
        }

    return {
        "script_id": "script-cap",
        "brief_id": "brief-cap",
        "language": "zh",
        "sections": [],
        "shots": [shot("S01", 1), shot("S02", 2)],
    }


def test_project_regen_cap_blocks_another_video_call(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_QA_PROJECT_RETRIES", "1")
    monkeypatch.setenv("HILATV_LIVE", "0")
    project_id = "revcap01"
    init_project(project_id, sentence="一句", status="completed")
    directory = project_path(project_id)
    nodes = directory / "nodes"
    nodes.mkdir()
    (nodes / "n05_storyboard.json").write_text(
        json.dumps({"script": _script()}, ensure_ascii=False),
        encoding="utf-8",
    )
    media = directory / "media"
    media.mkdir()
    (media / "S01.bin").write_bytes(b"a")
    (media / "S02.bin").write_bytes(b"b")
    update_snapshot(project_id, status="completed", deliverable=None)
    from workers.qa.budget_store import open_project_budget

    assert open_project_budget(project_id).try_take() is True
    before = hashes(directory)
    from workers.workflow.revise import revision_gateway

    class _Answers:
        def __init__(self, inner: object) -> None:
            self._inner = inner

        def generate_text(self, prompt: str, **kwargs: object) -> dict[str, object]:
            return {
                "targets": ["S02"],
                "change": {"lighting": "brighter"},
                "keep": ["composition"],
            }

        def __getattr__(self, name: str) -> object:
            return getattr(self._inner, name)

    gateway = _Answers(revision_gateway(directory))
    result = revise_project(project_id, "第二个镜头太暗", gateway=gateway)
    assert result["quality_pass"] is False
    assert result["video_shots"] == []
    assert hashes(directory) == before
    assert not any(
        row.get("task") == "video" for row in gateway.store.list_logs(project_id=project_id)
    )


def test_missing_video_keeps_the_file_and_does_not_hold_the_lock(tmp_path, monkeypatch) -> None:
    import fcntl

    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_LIVE", "0")
    monkeypatch.setenv("HILATV_RENDER_WIDTH", "64")
    monkeypatch.setenv("HILATV_RENDER_HEIGHT", "36")
    project_id = "revkeep01"
    init_project(project_id, sentence="一句", status="completed")
    directory = project_path(project_id)
    nodes = directory / "nodes"
    nodes.mkdir()
    (nodes / "n05_storyboard.json").write_text(
        json.dumps({"script": _script()}, ensure_ascii=False),
        encoding="utf-8",
    )
    media = directory / "media"
    media.mkdir()
    (media / "S01.bin").write_bytes(b"a")
    (media / "S02.bin").write_bytes(b"b")
    update_snapshot(project_id, status="completed", deliverable=None)

    def compose(*_args: object, **_kwargs: object) -> str:
        path = directory / "render" / "n15" / "master.mp4"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"composed")
        return str(path)

    monkeypatch.setattr("workers.workflow.revise._compose", compose)
    from workers.workflow.revise import revision_gateway

    class _Answers:
        def __init__(self, inner: object) -> None:
            self._inner = inner
            self.lock_free: bool | None = None

        def generate_text(self, prompt: str, **kwargs: object) -> dict[str, object]:
            return {
                "targets": ["S02"],
                "change": {"lighting": "brighter"},
                "keep": ["composition"],
            }

        def generate_video(self, *_args: object, **_kwargs: object) -> dict[str, object]:
            handle = (directory / ".lock").open("a+")
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                self.lock_free = False
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                self.lock_free = True
            finally:
                handle.close()
            raise RuntimeError("video file is missing")

        def __getattr__(self, name: str) -> object:
            return getattr(self._inner, name)

    gateway = _Answers(revision_gateway(directory))
    before = hashes(directory)
    result = revise_project(project_id, "第二个镜头太暗", gateway=gateway)
    assert gateway.lock_free is True
    assert result["status"] == "incomplete"
    assert result["kept_previous"] == ["S02"]
    assert "保留" in result["notice"]
    assert "改稿已生成新版本" not in result["notice"]
    assert result["quality_pass"] is False
    assert hashes(directory) == before
    assert (media / "S02.bin").read_bytes() == b"b"


def test_logo_replacement_url_is_refused_by_the_ssrf_guard(tmp_path) -> None:
    _maybe_fetch_logo(
        tmp_path,
        "把 Logo 换成 https://127.0.0.1/logo.png",
        {"change": {"logo": "replace"}},
    )
    assert not (tmp_path / "render" / "fetched-logo.png").exists()
