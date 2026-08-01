from __future__ import annotations

import ast
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from .models import QuantumMeasurementResult


BIT_ORDER_OPENQASM = "openqasm_high_classical_bit_left"
BIT_ORDER_QUBIT0_LEFT = "qubit0_left"
ALLOWED_SOURCES = {"hardware", "simulator", "replay", "manual_debug", "fallback"}
FORMAL_SOURCES = {"hardware"}
_SENSITIVE_KEYS = {
    "access_token",
    "api_token",
    "authorization",
    "cookie",
    "jwt",
    "password",
    "refresh_token",
    "secret",
    "token",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def redact_payload(value: Any) -> Any:
    """Remove authentication material while retaining result evidence structure."""
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            if key.lower().replace("-", "_") in _SENSITIVE_KEYS:
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = redact_payload(item)
        return redacted
    if isinstance(value, list):
        return [redact_payload(item) for item in value]
    if isinstance(value, tuple):
        return [redact_payload(item) for item in value]
    return value


def _parse_serialized(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text or text[0] not in "{[":
        return value
    try:
        return json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    try:
        return ast.literal_eval(text)
    except (SyntaxError, ValueError):
        return value


def _bitstring_key(value: Any) -> Optional[str]:
    text = str(value).replace(" ", "").replace("_", "")
    return text if re.fullmatch(r"[01]+", text) else None


def _find_counts_mapping(payload: Any) -> tuple[Optional[Mapping[Any, Any]], bool]:
    """Return the first count-like mapping and whether it is explicitly probabilities."""
    priority = (
        "counts",
        "count",
        "probabilities",
        "probability",
        "logicalq_res",
        "res",
        "result",
        "data",
    )
    pending: list[tuple[Any, bool]] = [(payload, False)]
    visited: set[int] = set()
    while pending:
        current, probability_hint = pending.pop(0)
        parsed = _parse_serialized(current)
        if parsed is not current:
            pending.insert(0, (parsed, probability_hint))
            continue
        marker = id(current)
        if marker in visited:
            continue
        visited.add(marker)
        if isinstance(current, Mapping):
            bit_keys = [_bitstring_key(key) for key in current]
            if any(bit_keys):
                return current, probability_hint
            for key in priority:
                if key in current:
                    pending.append(
                        (current[key], probability_hint or key in {"probabilities", "probability"})
                    )
            for key, value in current.items():
                if key not in priority:
                    pending.append((value, probability_hint))
        elif isinstance(current, (list, tuple)):
            pending.extend((item, probability_hint) for item in current)
    return None, False


def _probabilities_to_counts(probabilities: dict[str, float], shots: int) -> dict[str, int]:
    if shots <= 0:
        raise ValueError("shots_requested must be positive when converting probabilities to counts")
    total = sum(probabilities.values())
    if total <= 0:
        raise ValueError("probabilities must have a positive sum")
    normalized = {key: value / total for key, value in probabilities.items()}
    raw = {key: value * shots for key, value in normalized.items()}
    counts = {key: int(math.floor(value)) for key, value in raw.items()}
    remainder = shots - sum(counts.values())
    ranked = sorted(raw, key=lambda key: (raw[key] - counts[key], key), reverse=True)
    for key in ranked[:remainder]:
        counts[key] += 1
    return {key: value for key, value in counts.items() if value > 0}


def clean_counts(
    raw_counts: Mapping[Any, Any],
    *,
    shots_requested: int = 0,
    expected_bits: Optional[int] = None,
    probabilities: bool = False,
) -> tuple[dict[str, int], list[str]]:
    warnings: list[str] = []
    numeric: dict[str, float] = {}
    ignored = 0
    for raw_key, raw_value in raw_counts.items():
        bitstring = _bitstring_key(raw_key)
        if bitstring is None or (expected_bits is not None and len(bitstring) != expected_bits):
            ignored += 1
            continue
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            ignored += 1
            continue
        if not math.isfinite(value) or value < 0:
            ignored += 1
            continue
        numeric[bitstring] = numeric.get(bitstring, 0.0) + value
    if ignored:
        warnings.append(f"ignored {ignored} invalid count entr{'y' if ignored == 1 else 'ies'}")
    if not numeric:
        raise ValueError("payload does not contain valid measurement counts")

    has_fraction = any(abs(value - round(value)) > 1e-12 for value in numeric.values())
    probability_mode = probabilities or has_fraction
    if probability_mode:
        counts = _probabilities_to_counts(numeric, int(shots_requested))
        warnings.append("probabilities converted to integer counts using largest remainders")
    else:
        counts = {key: int(round(value)) for key, value in numeric.items() if value > 0}
    if not counts:
        raise ValueError("measurement counts are empty after cleaning")
    received = sum(counts.values())
    if shots_requested > 0 and received != shots_requested:
        warnings.append(
            f"shots mismatch: requested={int(shots_requested)}, received={received}"
        )
    return dict(sorted(counts.items())), warnings


def _find_single_bitstring(payload: Any, expected_bits: Optional[int]) -> Optional[str]:
    pending = [payload]
    visited: set[int] = set()
    while pending:
        current = pending.pop()
        parsed = _parse_serialized(current)
        if parsed is not current:
            pending.append(parsed)
            continue
        marker = id(current)
        if marker in visited:
            continue
        visited.add(marker)
        if isinstance(current, str):
            bitstring = _bitstring_key(current)
            if bitstring and (expected_bits is None or len(bitstring) == expected_bits):
                return bitstring
        elif isinstance(current, Mapping):
            pending.extend(current.values())
        elif isinstance(current, (list, tuple)):
            pending.extend(current)
    return None


def normalize_status(value: Any) -> str:
    text = str(value or "unknown").strip().lower()
    if text in {"finished", "complete", "completed", "done", "success", "succeeded"}:
        return "completed"
    if text in {"failed", "error", "cancelled", "canceled"}:
        return "failed"
    if text in {"queued", "pending", "waiting", "submitted"}:
        return "queued" if text != "submitted" else "submitted"
    if text in {"running", "executing", "processing"}:
        return "running"
    if text in {"timeout", "timed_out"}:
        return "timeout"
    return text or "unknown"


def measurement_from_payload(
    payload: Any,
    *,
    source: str,
    platform: str,
    status: Any = "unknown",
    task_id: Any = None,
    backend: Optional[str] = None,
    endpoint: Optional[str] = None,
    shots_requested: int = 0,
    selected_customer_ids: Optional[Iterable[int]] = None,
    bit_order: str = BIT_ORDER_OPENQASM,
    circuit: Optional[str] = None,
    evidence_path: Optional[str] = None,
    message: str = "",
    submitted_at: Optional[str] = None,
    completed_at: Optional[str] = None,
) -> QuantumMeasurementResult:
    if source not in ALLOWED_SOURCES:
        raise ValueError(f"unsupported measurement source: {source}")
    selected_ids = [int(value) for value in (selected_customer_ids or [])]
    expected_bits = len(selected_ids) or None
    mapping, probability_hint = _find_counts_mapping(payload)
    warnings: list[str] = []
    counts: dict[str, int] = {}
    if mapping is not None:
        try:
            counts, warnings = clean_counts(
                mapping,
                shots_requested=int(shots_requested or 0),
                expected_bits=expected_bits,
                probabilities=probability_hint,
            )
        except ValueError as exc:
            warnings.append(str(exc))
    if not counts:
        bitstring = _find_single_bitstring(payload, expected_bits)
        if bitstring:
            counts = {bitstring: 1}
            warnings.append("backend exposed only one sample; shots_received is 1")

    clean_payload = redact_payload(payload)
    normalized_status = normalize_status(status)
    if counts and normalized_status in {"unknown", "queued", "running", "submitted"}:
        normalized_status = "completed"
    return QuantumMeasurementResult(
        source=source,
        platform=platform,
        status=normalized_status,
        task_id=None if task_id in {None, ""} else str(task_id),
        backend=backend,
        endpoint=endpoint,
        shots_requested=max(0, int(shots_requested or 0)),
        shots_received=sum(counts.values()),
        counts=counts,
        selected_customer_ids=selected_ids,
        bit_order=bit_order,
        circuit_hash=hashlib.sha256(circuit.encode("utf-8")).hexdigest() if circuit else None,
        raw_payload_sha256=canonical_sha256(clean_payload),
        submitted_at=submitted_at,
        completed_at=completed_at or (now_iso() if counts else None),
        evidence_path=evidence_path,
        message=message,
        warnings=warnings,
    )


def measurement_from_evidence(
    path: Path | str,
    *,
    source: str = "replay",
    platform: str = "quarkstudio",
    selected_customer_ids: Optional[Iterable[int]] = None,
    bit_order: str = BIT_ORDER_OPENQASM,
) -> QuantumMeasurementResult:
    evidence_path = Path(path)
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    return measurement_from_payload(
        payload,
        source=source,
        platform=platform,
        status=payload.get("status", "unknown") if isinstance(payload, Mapping) else "unknown",
        task_id=payload.get("task_id") if isinstance(payload, Mapping) else None,
        backend=payload.get("backend") if isinstance(payload, Mapping) else None,
        shots_requested=int(payload.get("shots", 0)) if isinstance(payload, Mapping) else 0,
        selected_customer_ids=selected_customer_ids,
        bit_order=bit_order,
        circuit=payload.get("circuit") if isinstance(payload, Mapping) else None,
        evidence_path=str(evidence_path),
        message="Loaded from evidence replay.",
        submitted_at=payload.get("submitted_at") if isinstance(payload, Mapping) else None,
        completed_at=(payload.get("completed_at") or payload.get("result_received_at"))
        if isinstance(payload, Mapping)
        else None,
    )


def bitstring_to_customer_preferences(
    bitstring: str,
    selected_customer_ids: Iterable[int],
    *,
    bit_order: str = BIT_ORDER_OPENQASM,
) -> dict[int, int]:
    selected = [int(value) for value in selected_customer_ids]
    cleaned = _bitstring_key(bitstring)
    if cleaned is None:
        raise ValueError("bitstring must contain only 0 and 1")
    if len(cleaned) != len(selected):
        raise ValueError(
            f"bitstring length {len(cleaned)} does not match selected customers {len(selected)}"
        )
    if bit_order == BIT_ORDER_OPENQASM:
        qubit_order_bits = cleaned[::-1]
    elif bit_order == BIT_ORDER_QUBIT0_LEFT:
        qubit_order_bits = cleaned
    else:
        raise ValueError(f"unsupported bit_order: {bit_order}")
    return {customer_id: int(qubit_order_bits[index]) for index, customer_id in enumerate(selected)}


def formal_measurements(results: Iterable[QuantumMeasurementResult]) -> list[QuantumMeasurementResult]:
    """Exclude replay/debug/fallback data from live-hardware statistics."""
    return [result for result in results if result.formal_hardware_evidence]
