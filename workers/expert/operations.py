"""Durable identities for synchronous generation, without resubmitting unknown work.

The existing project lock serializes threads/processes. It intentionally remains
held during generation until HP12 introduces a durable asynchronous job runner.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from workers.expert.charge import BudgetExhausted
from workers.expert.gates import GateError
from workers.nodes.runtime import generation_scope
from workers.workflow.store import locked_project, read_snapshot, valid_project_id
from workers.workflow.versions import atomic_write

OPERATION_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"


class OperationConflict(GateError):
    def __init__(self, message: str, record: dict[str, Any], code: str):
        super().__init__(message, status=409)
        self.detail = {
            key: record.get(key)
            for key in (
                "operation_id",
                "generation_id",
                "input_revision",
                "input_hash",
            )
        }
        self.detail.update(message=message, code=code, operation_status=record.get("status"))


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


class GenerationOperation:
    def __init__(self, path: Path, record: dict[str, Any]):
        self.path, self.record = path, record
        self.dispatched = False
        self.lock = threading.RLock()

    @property
    def generation_id(self) -> str:
        return self.record["generation_id"]

    @property
    def operation_id(self) -> str:
        return self.record["operation_id"]

    def save(self) -> None:
        self.record["updated_at"] = time.time()
        atomic_write(
            self.path, (json.dumps(self.record, ensure_ascii=False, indent=2) + "\n").encode()
        )

    def capture(self, revision: int, inputs: dict[str, Any]) -> None:
        self.record.update(
            input_revision=revision,
            input_snapshot=copy.deepcopy(inputs),
            input_hash=_digest(inputs),
            status="prepared",
        )
        self.save()

    def metadata(self) -> dict[str, Any]:
        return {
            key: self.record.get(key)
            for key in ("operation_id", "generation_id", "input_revision", "input_hash")
        }

    def gateway(self, engine: Any) -> Any:
        return GenerationGateway(engine, self)

    def provenance(
        self, uri: str, *, node: str | None = None, seed: int | None = None
    ) -> dict[str, Any]:
        evidence = self.record.get("outputs", {}).get(uri)
        if evidence is None and node is not None:
            evidence = self.record.get("source_calls", {}).get(f"{node}:{seed}")
        return copy.deepcopy(evidence or {})


class GenerationGateway:
    def __init__(self, engine: Any, operation: GenerationOperation):
        self.engine, self.operation = engine, operation

    def __getattr__(self, name: str) -> Any:
        target = getattr(self.engine, name)
        if name not in {"generate_image", "generate_video", "music", "tts"}:
            return target

        def invoke(*args: Any, **kwargs: Any) -> Any:
            # Durable intent lands before any possible external submission.
            with self.operation.lock:
                self.operation.dispatched = True
                self.operation.record["status"] = "running"
                self.operation.save()
            kwargs["params"] = {**(kwargs.get("params") or {}), **self.operation.metadata()}
            output = target(*args, **kwargs)
            if isinstance(output, dict) and isinstance(output.get("uri"), str):
                row = {}
                store = getattr(self.engine, "store", None)
                try:
                    logs = (
                        store.list_logs(project_id=kwargs.get("project_id"))
                        if store is not None
                        else []
                    )
                except Exception:
                    logs = []
                if logs:
                    for item in reversed(logs):
                        params = item.get("params") or {}
                        if (
                            params.get("generation_id") == self.operation.generation_id
                            and params.get("seed") == kwargs.get("seed")
                            and item.get("node") == kwargs.get("node")
                            and item.get("shot_id") == kwargs.get("shot_id")
                        ):
                            row = item
                            break
                mock = output.get("mock")
                mock = mock if isinstance(mock, bool) else None
                mode = "mock" if mock is True else ("live" if mock is False else "unknown")
                cache_hit = row.get("cache_hit", output.get("cache_hit"))
                evidence = {
                    "mock": mock,
                    "execution_mode": mode,
                    "generation_source": output.get("generation_source") or mode,
                    "cache_hit": cache_hit if isinstance(cache_hit, bool) else None,
                    "fallback_reason": row.get("fallback_reason") or output.get("fallback_reason"),
                    "generation_source_uri": output["uri"],
                    "model": row.get("model")
                    or output.get("model")
                    or (
                        f"mock-{name.removeprefix('generate_')}"
                        if mock is True
                        else f"unknown-{name.removeprefix('generate_')}"
                    ),
                    "provider": row.get("provider") or output.get("provider"),
                }
                with self.operation.lock:
                    self.operation.record.setdefault("outputs", {})[output["uri"]] = evidence
                    self.operation.record.setdefault("source_calls", {})[
                        f"{kwargs.get('node')}:{kwargs.get('seed')}"
                    ] = evidence
                    self.operation.save()
            return output

        return invoke


def run_generation(
    project_id: str,
    *,
    operation_id: object,
    kind: str,
    target: str,
    request: dict[str, Any],
    action: Callable[[GenerationOperation], dict[str, Any]],
) -> dict[str, Any]:
    if not valid_project_id(project_id) or read_snapshot(project_id) is None:
        raise GateError("项目不存在", status=404)
    if operation_id is None:
        operation_id = str(uuid.uuid4())
    if not isinstance(operation_id, str) or re.fullmatch(OPERATION_PATTERN, operation_id) is None:
        raise GateError("operation_id 无效")
    fingerprint = _digest({"kind": kind, "target": target, "request": request})
    with locked_project(project_id) as directory:
        path = directory / "generation_operations" / (_digest(operation_id) + ".json")
        if path.exists():
            try:
                record = json.loads(path.read_text())
            except (OSError, ValueError) as exc:
                raise GateError("生成记录需要恢复，请保留这次操作编号", status=409) from exc
            if not isinstance(record, dict) or record.get("project_id") != project_id:
                raise GateError("生成记录不属于当前项目，请保留这次操作编号", status=409)
            if record.get("request_hash") != fingerprint:
                raise OperationConflict(
                    "同一 operation_id 的输入不能改变，请为新尝试使用新编号",
                    record,
                    "operation_input_conflict",
                )
            if record.get("status") == "succeeded":
                return {**copy.deepcopy(record["result"]), "replayed": True}
            if record.get("status") == "rejected":
                raise GateError(record["error"], status=record["error_status"])
            record["status"] = "unknown"
            GenerationOperation(path, record).save()
            raise OperationConflict(
                "这次生成结果尚未确认，已阻止重复提交；请保留 operation_id 等待恢复",
                record,
                "operation_result_unknown",
            )
        counter_path = directory / "generation_counter.json"
        try:
            counter = (
                json.loads(counter_path.read_text()) if counter_path.exists() else {"sequence": 0}
            )
            previous = counter["sequence"]
            if (
                isinstance(previous, bool)
                or not isinstance(previous, int)
                or not 0 <= previous < 2**32 - 1
            ):
                raise ValueError("invalid generation sequence")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise GateError("生成序号需要恢复，已停止提交新生成", status=409) from exc
        sequence = previous + 1
        atomic_write(counter_path, json.dumps({"sequence": sequence}).encode())
        generation_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"hilatv:{project_id}:{operation_id}"))
        operation = GenerationOperation(
            path,
            {
                "version": 1,
                "project_id": project_id,
                "operation_id": operation_id,
                "generation_id": generation_id,
                "sequence": sequence,
                "kind": kind,
                "target": target,
                "request_hash": fingerprint,
                "request": copy.deepcopy(request),
                "status": "accepted",
                "created_at": time.time(),
            },
        )
        operation.save()
        try:
            with generation_scope(generation_id, sequence):
                result = action(operation)
        except BaseException as exc:
            if operation.dispatched:
                operation.record.update(status="unknown", error="generation_result_unknown")
                operation.save()
                if not isinstance(exc, Exception):
                    raise
                raise OperationConflict(
                    "这次生成结果尚未确认，已阻止重复提交；请保留 operation_id 等待恢复",
                    operation.record,
                    "operation_result_unknown",
                ) from exc
            status = 409 if isinstance(exc, BudgetExhausted) else getattr(exc, "status", 422)
            operation.record.update(status="rejected", error=str(exc)[:400], error_status=status)
            operation.save()
            raise
        result = {
            **result,
            **operation.metadata(),
            "operation_status": "succeeded",
            "replayed": False,
        }
        operation.record.update(status="succeeded", result=copy.deepcopy(result))
        operation.save()
        return result
