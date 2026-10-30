"""Cross-enterprise checks against a running API. Status codes are the measurement."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
SECRET_SENTENCE = "SEC54-只有甲企业能看见这句话"
COMPANY = "SEC54隔离企业甲"
VOICE = "clone-sec54-voice"


def main() -> int:
    os.environ["HILATV_LIVE"] = "0"
    os.environ["HILATV_BUDGET_CNY"] = "0"
    os.environ["HILATV_DAILY_BUDGET_CNY"] = "0"
    os.environ["DATABASE_URL"] = ""
    os.environ["HILATV_SESSION_SECRET"] = "sec54-accept-secret"
    os.environ["HILATV_GATEWAY_STORE"] = "sqlite"
    work = Path(os.environ.get("TMPDIR", "/tmp")) / f"hilatv-sec54-{os.getpid()}"
    work.mkdir(parents=True, exist_ok=True)
    os.environ["HILATV_PROJECT_DIR"] = str(work / "projects")
    os.environ["HILATV_BRAND_DIR"] = str(work / "brands")
    os.environ["HILATV_SQLITE_PATH"] = str(work / "gateway.sqlite")
    port = _free_port()
    server = _start(port)
    rows: list[tuple[str, str, str]] = []
    try:
        _wait(port)
        rows.extend(_measure(port))
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
    passed = 0
    failed = 0
    print(f"{'endpoint':<56} {'result':<24} status")
    for name, result, detail in rows:
        print(f"{name:<56} {result:<24} {detail}")
        if result == "PASS":
            passed += 1
        else:
            failed += 1
    if failed:
        print(f"accept-sec54 failed pass={passed} fail={failed}")
        return 1
    print(f"accept-sec54 ok pass={passed}")
    return 0


def _measure(port: int) -> list[tuple[str, str, str]]:
    from workers.workflow.store import init_project, project_path

    base = f"http://127.0.0.1:{port}"
    rows: list[tuple[str, str, str]] = []
    with httpx.Client(base_url=base, timeout=60) as client:
        opened = client.post("/v1/session", json={})
        other = client.post("/v1/session", json={})
        rows.append(_status("POST /v1/session", opened, 200))
        forged = client.post("/v1/session", json={"enterprise_id": other.json()["enterprise_id"]})
        rows.append(
            _status("POST /v1/session body enterprise_id", forged, 422, contains="enterprise_id")
        )
        owner = opened.json()
        stranger = other.json()
        if owner["enterprise_id"] == stranger["enterprise_id"]:
            rows.append(("POST /v1/session distinct enterprises", "FAIL", "same id"))
        else:
            rows.append(("POST /v1/session distinct enterprises", "PASS", "two ids"))
        own = {"Authorization": f"Bearer {owner['token']}"}
        theirs = {"Authorization": f"Bearer {stranger['token']}"}
        logo = _logo()
        saved = client.post(
            "/v1/brands",
            headers=own,
            json={
                "company_name": COMPANY,
                "industry": "manufacturing",
                "logo_b64": logo,
                "people": [{"role": "保密工程师", "consent": True, "voice_id": VOICE}],
            },
        )
        rows.append(_status("POST /v1/brands", saved, 200, contains=COMPANY))
        body_brand = client.post(
            "/v1/brands",
            headers=own,
            json={
                "enterprise_id": stranger["enterprise_id"],
                "company_name": COMPANY,
                "industry": "manufacturing",
                "logo_b64": logo,
            },
        )
        rows.append(
            _status("POST /v1/brands body enterprise_id", body_brand, 422, contains="enterprise_id")
        )
        brand_path = Path(os.environ["HILATV_BRAND_DIR"])
        before_brand = _digest(brand_path)
        hidden_brand = client.get(f"/v1/brands/{owner['enterprise_id']}", headers=theirs)
        rows.append(
            _status(
                "GET /v1/brands/{other}",
                hidden_brand,
                404,
                absent=(COMPANY, VOICE, "保密工程师"),
            )
        )
        prefs = client.patch(
            f"/v1/brands/{owner['enterprise_id']}/preferences",
            headers=theirs,
            json={"drop_lines": ["泄漏"]},
        )
        rows.append(_status("PATCH /v1/brands/{other}/preferences", prefs, 404, absent=(COMPANY,)))
        if _digest(brand_path) != before_brand:
            rows.append(("brand archive after cross-enterprise writes", "FAIL", "bytes changed"))
        else:
            rows.append(("brand archive after cross-enterprise writes", "PASS", "unchanged"))
        seen = client.get(f"/v1/brands/{owner['enterprise_id']}", headers=own)
        rows.append(_status("GET /v1/brands/{self}", seen, 200, contains=COMPANY))
        queried = client.get(
            f"/v1/brands/{owner['enterprise_id']}",
            headers=own,
            params={"enterprise_id": stranger["enterprise_id"]},
        )
        rows.append(_status("GET /v1/brands query enterprise_id", queried, 422))
        bare = client.get(f"/v1/brands/{owner['enterprise_id']}")
        rows.append(_status("GET /v1/brands unauthenticated", bare, 401))
        concepts = client.post(
            "/v1/concepts",
            headers=theirs,
            json={"sentence": "做一条15秒宣传片", "enterprise_id": owner["enterprise_id"]},
        )
        rows.append(
            _status("POST /v1/concepts body enterprise_id", concepts, 422, absent=(COMPANY, VOICE))
        )
        own_concepts = client.post(
            "/v1/concepts",
            headers=own,
            json={"sentence": "给测试泵做一条15秒宣传片，面向采购，风格稳重"},
        )
        rows.append(_status("POST /v1/concepts", own_concepts, 200))

        project_id = "sec54proj"
        init_project(
            project_id,
            sentence=SECRET_SENTENCE,
            status="running",
            enterprise_id=owner["enterprise_id"],
            brand_id="brand-sec54",
        )
        snapshot = project_path(project_id) / "project.json"
        before = snapshot.read_bytes()
        rows.extend(_project_rows(client, project_id, own, theirs, before, snapshot))
        rows.append(_websocket(port, project_id, stranger["token"], SECRET_SENTENCE))
        rows.append(_cli(project_id, owner["token"], stranger["token"], snapshot))
        rows.extend(_human_review(client, project_id, own, theirs, snapshot))
    return rows


def _project_rows(client, project_id, own, theirs, before: bytes, snapshot: Path):
    rows = []
    hidden = client.get(f"/v1/projects/{project_id}", headers=theirs)
    rows.append(_status("GET /v1/projects/{other}", hidden, 404, absent=(SECRET_SENTENCE,)))
    visible = client.get(f"/v1/projects/{project_id}", headers=own)
    rows.append(_status("GET /v1/projects/{self}", visible, 200, contains=SECRET_SENTENCE))
    anonymous = client.get(f"/v1/projects/{project_id}")
    rows.append(_status("GET /v1/projects unauthenticated", anonymous, 401))
    body_id = client.post(
        "/v1/projects",
        headers=own,
        json={"sentence": "另一条", "enterprise_id": "66666666-6666-4666-8666-666666666666"},
    )
    rows.append(
        _status("POST /v1/projects body enterprise_id", body_id, 422, contains="enterprise_id")
    )
    checks = [
        ("POST", f"/v1/projects/{project_id}/rerun", {"node": "n01_brief"}),
        ("POST", f"/v1/projects/{project_id}/revisions", {"instruction": "改掉"}),
        ("GET", f"/v1/projects/{project_id}/revisions", None),
        ("POST", f"/v1/projects/{project_id}/revisions/{'ab' * 16}/restore", {}),
        ("POST", f"/v1/projects/{project_id}/storyboard/continue", {}),
        ("POST", f"/v1/projects/{project_id}/storyboard/S01", {"voiceover": "改旁白"}),
        ("GET", f"/v1/projects/{project_id}/storyboard/S01/frame", None),
        ("GET", f"/v1/projects/{project_id}/download", None),
        ("POST", f"/v1/projects/{project_id}/deliveries", {}),
        ("GET", f"/v1/projects/{project_id}/versions", None),
        ("GET", f"/v1/projects/{project_id}/versions/v1", None),
        ("GET", f"/v1/projects/{project_id}/versions/v1/download", None),
        ("POST", f"/v1/projects/{project_id}/versions/v1/share", {}),
    ]
    for method, path, payload in checks:
        response = client.request(method, path, headers=theirs, json=payload)
        rows.append(
            _status(f"{method} {path} other enterprise", response, 404, absent=(SECRET_SENTENCE,))
        )
    if snapshot.read_bytes() != before:
        rows.append(("project file after cross-enterprise calls", "FAIL", "bytes changed"))
    else:
        rows.append(("project file after cross-enterprise calls", "PASS", "unchanged"))
    upload = client.post(
        "/v1/uploads",
        headers=own,
        files={"file": ("a.png", base64.b64decode(_PNG), "image/png")},
    )
    rows.append(_status("POST /v1/uploads", upload, 200))
    if upload.status_code == 200:
        stolen = client.post(
            "/v1/projects",
            headers=theirs,
            json={
                "sentence": "用别人的图",
                "attachments": [{"kind": "image", "upload_id": upload.json()["upload_id"]}],
            },
        )
        rows.append(
            _status(
                "POST /v1/projects foreign upload",
                stolen,
                422,
                absent=(upload.json()["upload_id"],),
            )
        )
    form = client.post(
        "/v1/uploads",
        headers=own,
        data={"enterprise_id": "66666666-6666-4666-8666-666666666666"},
        files={"file": ("b.png", base64.b64decode(_PNG), "image/png")},
    )
    rows.append(_status("POST /v1/uploads form enterprise_id", form, 422, contains="enterprise_id"))
    return rows


def _human_review(
    client,
    project_id,
    owner,
    stranger,
    snapshot: Path,
) -> list[tuple[str, str, str]]:
    spec = client.get("/openapi.json")
    paths = spec.json().get("paths") or {}
    route = "/v1/projects/{project_id}/human-review/release"
    name = "POST /v1/projects/{id}/human-review/release"
    if route not in paths:
        return [(name, "FAIL", "route missing")]
    before = snapshot.read_bytes()
    hidden = client.post(f"/v1/projects/{project_id}/human-review/release", headers=stranger)
    rows = [_status(f"{name} other enterprise", hidden, 404, absent=(SECRET_SENTENCE,))]
    if snapshot.read_bytes() != before:
        rows.append((f"{name} other bytes", "FAIL", "changed"))
    else:
        rows.append((f"{name} other bytes", "PASS", "unchanged"))
    anonymous = client.post(f"/v1/projects/{project_id}/human-review/release")
    rows.append(_status(f"{name} unauthenticated", anonymous, 401))
    held_off = client.post(f"/v1/projects/{project_id}/human-review/release", headers=owner)
    rows.append(_status(f"{name} owner not in review", held_off, 409))
    if snapshot.read_bytes() != before:
        rows.append((f"{name} owner bytes", "FAIL", "changed"))
    else:
        rows.append((f"{name} owner bytes", "PASS", "unchanged"))
    return rows


def _websocket(port: int, project_id: str, token: str, secret: str) -> tuple[str, str, str]:
    import asyncio

    import websockets

    async def once() -> tuple[str, str, str]:
        uri = f"ws://127.0.0.1:{port}/v1/projects/{project_id}/progress?session={token}"
        async with websockets.connect(uri) as socket:
            raw = await asyncio.wait_for(socket.recv(), timeout=5)
        body = json.loads(raw)
        text = json.dumps(body, ensure_ascii=False)
        if secret in text:
            return ("WS /v1/projects/{other}/progress", "FAIL", "leaked sentence")
        if body.get("message") != "项目不存在":
            return ("WS /v1/projects/{other}/progress", "FAIL", text[:120])
        return ("WS /v1/projects/{other}/progress", "PASS", "4404")

    return asyncio.run(once())


def _cli(
    project_id: str,
    owner_token: str,
    other_token: str,
    snapshot: Path,
) -> tuple[str, str, str]:
    before = snapshot.read_bytes()
    env = os.environ.copy()
    env["HILATV_SESSION"] = other_token
    proc = subprocess.run(
        [sys.executable, "-m", "workers.workflow.cli", "rerun", project_id, "n01_brief"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode == 0 or "项目不存在" not in proc.stderr or SECRET_SENTENCE in proc.stderr:
        return ("CLI hilatv rerun other enterprise", "FAIL", proc.stderr[-200:])
    if snapshot.read_bytes() != before:
        return ("CLI hilatv rerun other enterprise", "FAIL", "bytes changed")
    env["HILATV_SESSION"] = owner_token
    owned = subprocess.run(
        [sys.executable, "-m", "workers.workflow.cli", "rerun", project_id, "n01_brief"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if "项目仍在运行" not in owned.stderr or snapshot.read_bytes() != before:
        return ("CLI hilatv rerun owner", "FAIL", owned.stderr[-200:])
    return ("CLI hilatv rerun other enterprise", "PASS", "项目不存在")


def _status(
    name: str,
    response: httpx.Response,
    expected: int,
    *,
    contains: str | None = None,
    absent: tuple[str, ...] = (),
) -> tuple[str, str, str]:
    if response.status_code != expected:
        return (name, "FAIL", f"{response.status_code} {response.text[:160]}")
    if contains and contains not in response.text:
        return (name, "FAIL", "missing expected text")
    for item in absent:
        if item and item in response.text:
            return (name, "FAIL", "leaked")
    return (name, "PASS", str(response.status_code))


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    if not path.exists():
        return ""
    for item in sorted(path.rglob("*")):
        if item.is_file():
            digest.update(item.relative_to(path).as_posix().encode())
            digest.update(item.read_bytes())
    return digest.hexdigest()


def _logo() -> str:
    from workers.brand_kit.tests.images import logo_png

    return base64.b64encode(logo_png()).decode("ascii")


def _start(port: int) -> subprocess.Popen:
    env = os.environ.copy()
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--app-dir",
            str(ROOT / "apps" / "api"),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )


def _wait(port: int) -> None:
    deadline = time.time() + 20
    last = ""
    while time.time() < deadline:
        try:
            response = httpx.get(f"http://127.0.0.1:{port}/health", timeout=1)
            if response.status_code == 200:
                return
        except httpx.HTTPError as exc:
            last = str(exc)
        time.sleep(0.2)
    raise SystemExit(f"API did not start: {last}")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


_PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


if __name__ == "__main__":
    raise SystemExit(main())
