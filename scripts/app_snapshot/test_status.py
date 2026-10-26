#!/usr/bin/env python3
"""Статус в App Store: разбор версий и история смен, без запросов к Apple."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import status  # noqa: E402

ok = True


def check(label: str, cond: bool) -> None:
    global ok
    ok = ok and cond
    print(("OK   " if cond else "ПЛОХО") + " " + label)


def v(version: str, state: str, created: str, new: str | None = None) -> dict:
    attrs = {"versionString": version, "appStoreState": state, "createdDate": created}
    if new:
        attrs["appVersionState"] = new
    return {"attributes": attrs}


# Нет версий — приложения нет в сторе.
check("нет версий", status.summarize([])["status"] == "none")

# Новая версия на проверке, старая в продаже.
s = status.summarize([v("1.12", "READY_FOR_SALE", "2026-10-01T00:00:00Z"), v("1.13", "IN_REVIEW", "2026-10-20T00:00:00Z")])
check("на проверке", s["status"] == "review" and s["appVersion"] == "1.13" and s["live"] == "1.12")

# Порядок ответа Apple не важен — последняя по дате создания.
s = status.summarize([v("1.13", "WAITING_FOR_REVIEW", "2026-10-20T00:00:00Z"), v("1.12", "READY_FOR_SALE", "2026-10-01T00:00:00Z")])
check("ждёт проверки, порядок любой", s["status"] == "wait" and s["appVersion"] == "1.13")

check("отклонено", status.summarize([v("1.1", "REJECTED", "2026-10-20T00:00:00Z")])["status"] == "rej")
check("отклонены метаданные", status.summarize([v("1.1", "METADATA_REJECTED", "2026-10-20T00:00:00Z")])["status"] == "rej")
check("одобрено, ждёт выпуска", status.summarize([v("3.0", "PENDING_DEVELOPER_RELEASE", "2026-10-20T00:00:00Z")])["status"] == "ok")
check("готовится", status.summarize([v("1.6", "PREPARE_FOR_SUBMISSION", "2026-10-20T00:00:00Z")])["status"] == "prep")
s = status.summarize([v("2.1", "READY_FOR_SALE", "2026-10-20T00:00:00Z")])
check("в продаже — сама себе live", s["status"] == "sale" and s["live"] == "2.1")
# Новое поле appVersionState сильнее устаревшего appStoreState.
check("новое поле главнее", status.summarize([v("1.0", "READY_FOR_SALE", "2026-10-20T00:00:00Z", new="IN_REVIEW")])["status"] == "review")
check("незнакомое состояние", status.status_of("SOMETHING_NEW") == "unknown")

# История: смена статуса — новая строка, повторная проверка — нет.
cur = {"status": "wait", "appVersion": "1.13", "raw": "WAITING_FOR_REVIEW", "live": "1.12"}
st = status.record({}, cur, "2026-10-20T10:00:00Z", "pm")
check("первая запись", len(st["history"]) == 1 and st["changedAt"] == "2026-10-20T10:00:00Z")
st = status.record(st, cur, "2026-10-20T22:00:00Z", None)
check("тот же статус — без новой строки", len(st["history"]) == 1 and st["checkedAt"] == "2026-10-20T22:00:00Z" and st["changedAt"] == "2026-10-20T10:00:00Z")
st = status.record(st, {**cur, "status": "review", "raw": "IN_REVIEW"}, "2026-10-21T10:00:00Z", None)
check("смена статуса — новая строка сверху", len(st["history"]) == 2 and st["history"][0]["status"] == "review" and st["changedAt"] == "2026-10-21T10:00:00Z")

sys.exit(0 if ok else 1)
