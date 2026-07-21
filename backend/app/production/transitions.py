"""Stable identity for generated transitions."""

from __future__ import annotations

import hashlib
import json

from app.production.types import TransitionSpec


def transition_signature(spec: TransitionSpec) -> str:
    """Same sources and creative parameters always address the same transition job."""

    payload = spec.model_dump(mode="json", exclude_none=True)
    payload["preserve_element_ids"] = sorted(payload.get("preserve_element_ids", []))
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
