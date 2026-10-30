"""Mock end-to-end: one sentence becomes a playable MP4, with per-shot progress."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SENTENCE = "给我们的柱塞泵做个15秒宣传片，面向采购，风格稳重"
SHOT_LINE = re.compile(r"第 \d+ 镜：正在生成画面")
PHASES = ("理解需求", "选方案", "看分镜", "生成中", "成片")


def main() -> int:
    os.environ.setdefault("HILATV_SESSION_SECRET", "accept-t10-session")
    from workers.identity.session import open_session

    identity = open_session()
    env = os.environ.copy()
    env["HILATV_SESSION"] = identity.token
    env["HILATV_SESSION_SECRET"] = os.environ["HILATV_SESSION_SECRET"]
    proc = subprocess.run(
        [sys.executable, "-m", "workers.workflow.cli", "run", SENTENCE],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
        env=env,
    )
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    if proc.returncode != 0:
        return proc.returncode or 1
    result = _result_line(proc.stdout)
    if result.get("status") == "needs_human_review":
        if result.get("deliverable"):
            print("held project already had a deliverable", file=sys.stderr)
            return 1
        released = subprocess.run(
            [sys.executable, "-m", "workers.workflow.cli", "release", str(result["project_id"])],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
            env=env,
        )
        sys.stdout.write(released.stdout)
        sys.stderr.write(released.stderr)
        if released.returncode != 0:
            return released.returncode or 1
        result = _result_line(released.stdout)
    if result.get("status") != "completed":
        print("workflow did not complete", file=sys.stderr)
        return 1
    if result.get("timing_recorded") is not True:
        print("elapsed time was not recorded", file=sys.stderr)
        return 1
    elapsed = result.get("elapsed_s")
    if not isinstance(elapsed, (int, float)) or elapsed < 0:
        print(f"elapsed_s is missing: {elapsed}", file=sys.stderr)
        return 1
    if result.get("live") is not False:
        print("accept-t10 must run with live calls off", file=sys.stderr)
        return 1
    if result.get("phase") != "成片":
        print(f"phase is {result.get('phase')}", file=sys.stderr)
        return 1
    deliverable = Path(str(result["deliverable"]))
    duration = _playable(deliverable)
    from workers.workflow.store import read_events

    events = read_events(str(result["project_id"]))
    messages = [str(item.get("message") or "") for item in events]
    if not any(SHOT_LINE.search(message) for message in messages):
        print("missing per-shot progress\n" + "\n".join(messages), file=sys.stderr)
        return 1
    phases = {item.get("phase") for item in events}
    missing = [phase for phase in PHASES if phase not in phases]
    if missing:
        print(f"missing phases {missing}", file=sys.stderr)
        return 1
    if not any("你帮我选" in message for message in messages):
        print("N3 did not auto-select 你帮我选", file=sys.stderr)
        return 1
    _websocket(str(result["project_id"]), identity.token)
    print(f"accept-t10 ok duration_s={duration:.3f} elapsed_s={elapsed}")
    return 0


def _result_line(stdout: str) -> dict:
    found = [line for line in stdout.splitlines() if line.startswith("HILATV_RESULT ")]
    if not found:
        print("CLI did not print HILATV_RESULT", file=sys.stderr)
        raise SystemExit(1)
    return json.loads(found[-1].removeprefix("HILATV_RESULT "))


def _playable(path: Path) -> float:
    if not path.is_file() or path.stat().st_size == 0:
        print(f"missing master {path}", file=sys.stderr)
        raise SystemExit(1)
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_name",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        print(probe.stderr, file=sys.stderr)
        raise SystemExit(1)
    data = json.loads(probe.stdout or "{}")
    streams = data.get("streams") or []
    codec = streams[0].get("codec_name") if streams else ""
    if codec != "h264":
        print(f"expected h264, got {codec}", file=sys.stderr)
        raise SystemExit(1)
    duration = float((data.get("format") or {}).get("duration") or 0)
    if duration <= 0:
        print("master duration is 0", file=sys.stderr)
        raise SystemExit(1)
    decode = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"],
        capture_output=True,
        text=True,
        check=False,
    )
    if decode.returncode != 0:
        print(decode.stderr[-400:], file=sys.stderr)
        raise SystemExit(1)
    return duration


def _websocket(project_id: str, token: str) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    headers = {"Authorization": f"Bearer {token}"}
    with TestClient(app) as client:
        with client.websocket_connect(
            f"/v1/projects/{project_id}/progress",
            headers=headers,
        ) as socket:
            seen: list[dict] = []
            while True:
                item = socket.receive_json()
                seen.append(item)
                if item.get("status") == "completed":
                    break
    if not any(SHOT_LINE.search(str(item.get("message") or "")) for item in seen):
        print("websocket did not send a per-shot line", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    raise SystemExit(main())
