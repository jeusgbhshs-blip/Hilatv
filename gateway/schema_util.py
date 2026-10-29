"""Normalize caller schemas and fill a deterministic mock document."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from gateway.errors import AdapterError


def normalize_schema(
    schema: type[BaseModel] | dict[str, Any] | None,
) -> tuple[type[BaseModel] | None, dict[str, Any] | None, str | None]:
    if schema is None:
        return None, None, None
    if isinstance(schema, type) and issubclass(schema, BaseModel):
        return schema, schema.model_json_schema(), schema.__name__
    if isinstance(schema, dict):
        title = schema.get("title")
        name = title if isinstance(title, str) else None
        return None, schema, name
    raise TypeError("schema must be a Pydantic model class or a JSON Schema dict")


def coerce_output(
    raw: Any,
    model: type[BaseModel] | None,
    json_schema: dict[str, Any] | None,
) -> dict[str, Any]:
    if model is not None:
        value = raw
        if isinstance(value, str):
            import json

            value = json.loads(value)
        return model.model_validate(value).model_dump(mode="json")
    if json_schema is not None:
        import json

        import jsonschema

        value = raw
        if isinstance(value, str):
            value = json.loads(value)
        jsonschema.validate(instance=value, schema=json_schema)
        if not isinstance(value, dict):
            raise AdapterError("structured output must be a JSON object")
        return value
    if isinstance(raw, dict):
        return raw
    return {"text": "" if raw is None else str(raw)}


def fill_json_schema(schema: dict[str, Any]) -> Any:
    if not isinstance(schema, dict):
        raise AdapterError("JSON Schema must be an object")
    return _fill(schema, schema)


def _deref(schema: dict[str, Any], root: dict[str, Any]) -> dict[str, Any]:
    seen = 0
    while isinstance(schema, dict) and "$ref" in schema:
        ref = schema["$ref"]
        if not isinstance(ref, str) or not ref.startswith("#/"):
            break
        node: object = root
        for part in ref[2:].split("/"):
            if not isinstance(node, dict) or part not in node:
                return schema
            node = node[part]
        if not isinstance(node, dict):
            break
        schema = node
        seen += 1
        if seen > 20:
            break
    return schema


def _allows_null(schema: dict[str, Any]) -> bool:
    kind = schema.get("type")
    if kind == "null":
        return True
    if isinstance(kind, list) and "null" in kind:
        return True
    for key in ("anyOf", "oneOf"):
        for option in schema.get(key) or []:
            if isinstance(option, dict) and option.get("type") == "null":
                return True
    return False


def _fill(schema: dict[str, Any], root: dict[str, Any]) -> Any:
    schema = _deref(schema, root)
    if "default" in schema:
        default = schema["default"]
        if default is not None or _allows_null(schema):
            return default
    if "const" in schema:
        return schema["const"]
    if "enum" in schema and schema["enum"]:
        return schema["enum"][0]
    if schema.get("examples"):
        return schema["examples"][0]
    for key in ("anyOf", "oneOf"):
        options = schema.get(key)
        if options:
            for option in options:
                if isinstance(option, dict):
                    resolved = _deref(option, root)
                    if resolved.get("type") != "null":
                        return _fill(resolved, root)
            return None
    if "allOf" in schema and schema["allOf"]:
        merged: dict[str, Any] = {}
        for part in schema["allOf"]:
            if isinstance(part, dict):
                merged.update(_deref(part, root))
        merged.update({k: v for k, v in schema.items() if k != "allOf"})
        return _fill(merged, root)

    kind = schema.get("type")
    if isinstance(kind, list):
        kind = next((item for item in kind if item != "null"), kind[0] if kind else None)
    if kind == "object" or "properties" in schema:
        props = schema.get("properties") or {}
        required = set(schema.get("required") or [])
        out: dict[str, Any] = {}
        for name, sub in props.items():
            if not isinstance(sub, dict):
                continue
            resolved = _deref(sub, root)
            if name in required or "default" in resolved:
                out[name] = _fill(resolved, root)
        return out
    if kind == "array":
        items = schema.get("items") if isinstance(schema.get("items"), dict) else {"type": "string"}
        count = int(schema.get("minItems") or 0)
        return [_fill(items, root) for _ in range(count)]
    if kind == "string":
        if schema.get("format") == "uuid":
            value = "00000000-0000-4000-8000-000000000001"
        elif schema.get("format") == "date-time":
            value = "2026-01-01T00:00:00Z"
        else:
            value = "mock"
        min_len = int(schema.get("minLength") or 0)
        if len(value) < min_len:
            value = value + ("x" * (min_len - len(value)))
        return value
    if kind == "integer":
        if isinstance(schema.get("minimum"), (int, float)):
            return int(schema["minimum"])
        if isinstance(schema.get("exclusiveMinimum"), (int, float)):
            return int(schema["exclusiveMinimum"]) + 1
        return 0
    if kind == "number":
        if isinstance(schema.get("minimum"), (int, float)):
            return float(schema["minimum"])
        return 0.0
    if kind == "boolean":
        return False
    if kind == "null":
        return None
    return None
