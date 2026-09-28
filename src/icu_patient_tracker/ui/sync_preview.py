"""Readable patient snapshots for side-by-side conflict review."""

from typing import Any


def describe_snapshot(payload: dict[str, object]) -> str:
    if payload.get("patient") is None:
        return "Patient deleted"
    lines: list[str] = []

    def render(value: Any, label: str, depth: int = 0) -> None:
        prefix = "  " * depth
        if isinstance(value, dict):
            if value.get("type") == "UUID":
                return
            if "fields" in value:
                lines.append(f"{prefix}{label}")
                for name, field in value["fields"].items():
                    if name in {"id", "created_at", "updated_at"} or name.endswith("_id"):
                        continue
                    render(field, name.replace("_", " ").strip().capitalize(), depth + 1)
            elif "value" in value:
                render(value["value"], label, depth)
        elif isinstance(value, list):
            lines.append(f"{prefix}{label}:" + (" None" if not value else ""))
            for index, item in enumerate(value, 1):
                render(item, str(index), depth + 1)
        else:
            text = "Not set" if value is None else str(value)
            lines.append(f"{prefix}{label}: {text}")

    render(payload["patient"], "Patient")
    return "\n".join(lines)
