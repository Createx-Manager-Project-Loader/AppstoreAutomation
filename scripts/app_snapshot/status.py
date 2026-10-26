#!/usr/bin/env python3
"""Раздел «Статус в App Store» снимка: что с последней версией у Apple.

Чистые функции без запросов — разбор версий и история смен статуса.
Запросы делает snapshot.py. Текста ответа App Review здесь нет и быть не
может: ключ API к переписке с ревьюером не пускает.
"""

from __future__ import annotations

from datetime import datetime, timezone

# Сколько смен статуса помнить: ленте ревью в консоли больше не нужно.
KEEP_HISTORY = 30

# Состояние версии у Apple → статус в консоли. Поле appStoreState Apple
# объявила устаревшим, но отдаёт; appVersionState — новое, берём его, когда есть.
STATES = {
    "sale": {"READY_FOR_SALE", "READY_FOR_DISTRIBUTION"},
    "ok": {"PENDING_DEVELOPER_RELEASE", "PENDING_APPLE_RELEASE", "ACCEPTED", "PROCESSING_FOR_APP_STORE",
           "PROCESSING_FOR_DISTRIBUTION", "PREORDER_READY_FOR_SALE"},
    "review": {"IN_REVIEW"},
    "wait": {"WAITING_FOR_REVIEW", "READY_FOR_REVIEW", "WAITING_FOR_EXPORT_COMPLIANCE"},
    "rej": {"REJECTED", "METADATA_REJECTED", "INVALID_BINARY"},
    "prep": {"PREPARE_FOR_SUBMISSION", "DEVELOPER_REJECTED"},
    "removed": {"REMOVED_FROM_SALE", "DEVELOPER_REMOVED_FROM_SALE", "REPLACED_WITH_NEW_VERSION"},
}


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def status_of(raw: str | None) -> str:
    for status, names in STATES.items():
        if raw in names:
            return status
    return "unknown"


def raw_state(version: dict) -> str | None:
    attrs = version.get("attributes") or {}
    return attrs.get("appVersionState") or attrs.get("appStoreState")


def summarize(versions: list[dict]) -> dict:
    """Последняя версия, её статус и версия, которая сейчас в продаже."""
    if not versions:
        return {"status": "none", "appVersion": None, "raw": None, "live": None}
    ordered = sorted(versions, key=lambda v: (v.get("attributes") or {}).get("createdDate") or "", reverse=True)
    latest = ordered[0]
    live = next((v for v in ordered if status_of(raw_state(v)) == "sale"), None)
    raw = raw_state(latest)
    return {
        "status": status_of(raw),
        "appVersion": (latest.get("attributes") or {}).get("versionString"),
        "raw": raw,
        "live": (live.get("attributes") or {}).get("versionString") if live else None,
    }


def record(state: dict, current: dict, at: str, by: str | None) -> dict:
    """Раздел статуса: текущий статус и история смен (state — прошлый раздел)."""
    history = list(state.get("history") or [])
    last = history[0] if history else None
    if not last or (last.get("status"), last.get("appVersion")) != (current["status"], current["appVersion"]):
        history.insert(0, {"at": at, "status": current["status"], "appVersion": current["appVersion"], "raw": current["raw"]})
    return {
        **current,
        "checkedAt": at,
        "checkedBy": by,
        "changedAt": history[0]["at"],
        "history": history[:KEEP_HISTORY],
    }
