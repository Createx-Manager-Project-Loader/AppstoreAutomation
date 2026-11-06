#!/usr/bin/env python3
"""Выпуск версии в App Store — по кнопке из консоли.

Действия:

    settings  способ выпуска версии, что готовится: вручную / сразу после
              одобрения / не раньше даты, и поэтапная раскатка на 7 дней.
              Задаётся вместе с обновлением; версию прогон обновления может
              создать позже нас, поэтому её ждём.
    release   выпустить одобренную версию (ждёт ручного выпуска).
    pause     поставить поэтапную раскатку на паузу.
    resume    продолжить раскатку.
    complete  раскатать на всех сразу.

Для release / pause / resume / complete консоль передаёт номер версии,
которую видел человек, и мы сверяем его со стором: нажали «Выпустить 1.6.1» —
выпустится только 1.6.1, и только если она действительно ждёт выпуска.

Выпуск отменить нельзя. Поэтому здесь нет догадок: любое расхождение —
остановка с понятной причиной, а не «сделаем, что получится».
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parent))
sys.path.insert(0, str(SCRIPT_DIR.parent / "lib"))

from upload_screenshots_api import (  # noqa: E402
    EDITABLE_STATES,
    AppStoreConnectClient,
    AppStoreConnectError,
    find_app,
    require_env,
)

ACTIONS = ("settings", "release", "pause", "resume", "complete")
RELEASE_TYPES = ("MANUAL", "AFTER_APPROVAL", "SCHEDULED")
PHASE_TARGET = {"pause": "PAUSED", "resume": "ACTIVE", "complete": "COMPLETE"}
# Из каких состояний раскатки какое действие имеет смысл.
PHASE_FROM = {"pause": {"ACTIVE"}, "resume": {"PAUSED"}, "complete": {"ACTIVE", "PAUSED"}}
LIVE_STATES = {"READY_FOR_SALE", "READY_FOR_DISTRIBUTION"}


class Stop(Exception):
    """Причина остановки — человеческим языком, для журнала и консоли."""


def state_of(version: dict) -> str:
    attributes = version.get("attributes") or {}
    return attributes.get("appVersionState") or attributes.get("appStoreState") or ""


def versions_of(client: AppStoreConnectClient, app_id: str) -> list[dict[str, Any]]:
    response = client.request(
        "GET",
        f"/apps/{app_id}/appStoreVersions?filter[platform]=IOS&limit=20"
        # Связь обязана стоять в fields — иначе Apple её не отдаст даже при include.
        "&fields[appStoreVersions]=versionString,appStoreState,appVersionState,createdDate,"
        "releaseType,earliestReleaseDate,appStoreVersionPhasedRelease"
        "&include=appStoreVersionPhasedRelease"
        "&fields[appStoreVersionPhasedReleases]=phasedReleaseState,currentDayNumber",
    )
    phased = {
        item["id"]: item
        for item in response.get("included") or []
        if item.get("type") == "appStoreVersionPhasedReleases"
    }
    versions = response.get("data") or []
    for version in versions:
        ref = ((version.get("relationships") or {}).get("appStoreVersionPhasedRelease") or {}).get("data")
        version["phased"] = phased.get(ref["id"]) if ref else None
    return sorted(versions, key=lambda v: (v.get("attributes") or {}).get("createdDate") or "", reverse=True)


def by_version(versions: list[dict], wanted: str) -> dict:
    found = next((v for v in versions if (v.get("attributes") or {}).get("versionString") == wanted), None)
    if not found:
        seen = ", ".join(f"{(v.get('attributes') or {}).get('versionString')} ({state_of(v)})" for v in versions[:5])
        raise Stop(f"Версии {wanted} в App Store Connect нет. Есть: {seen or 'ничего'}.")
    return found


# ── способ выпуска ─────────────────────────────────────────────────────────

def editable_version(client: AppStoreConnectClient, app_id: str, wait_seconds: int) -> dict:
    """Версия, что готовится. Нет — ждём: её может создать идущий прогон обновления."""
    deadline = time.time() + wait_seconds
    while True:
        versions = versions_of(client, app_id)
        editable = [v for v in versions if (v.get("attributes") or {}).get("appStoreState") in EDITABLE_STATES]
        if editable:
            return editable[0]
        if time.time() >= deadline:
            raise Stop(
                "Версии, которая готовится к отправке, так и не появилось. Способ выпуска "
                "задаётся только ей: запустите обновление или создайте версию в App Store Connect."
            )
        print("Версии, что готовится, ещё нет — ждём, её создаст прогон обновления...")
        time.sleep(30)


def apply_settings(client: AppStoreConnectClient, version: dict, release_type: str,
                   release_date: str | None, phased: bool | None) -> None:
    number = (version.get("attributes") or {}).get("versionString")
    attributes: dict[str, Any] = {"releaseType": release_type}
    # Дата нужна только «по дате»; в остальных режимах её снимаем, чтобы в
    # App Store Connect не висела старая.
    attributes["earliestReleaseDate"] = release_date if release_type == "SCHEDULED" else None
    client.request(
        "PATCH",
        f"/appStoreVersions/{version['id']}",
        json={"data": {"type": "appStoreVersions", "id": version["id"], "attributes": attributes}},
    )
    how = {"MANUAL": "вручную", "AFTER_APPROVAL": "сразу после одобрения",
           "SCHEDULED": f"не раньше {release_date} (UTC)"}[release_type]
    print(f"Версия {number}: выпуск — {how}")

    if phased is None:
        return
    current = version.get("phased")
    if phased and not current:
        client.request(
            "POST",
            "/appStoreVersionPhasedReleases",
            json={"data": {
                "type": "appStoreVersionPhasedReleases",
                "attributes": {"phasedReleaseState": "INACTIVE"},
                "relationships": {"appStoreVersion": {"data": {"type": "appStoreVersions", "id": version["id"]}}},
            }},
        )
        print(f"Версия {number}: поэтапная раскатка включена — 7 дней после выпуска")
    elif not phased and current:
        client.request("DELETE", f"/appStoreVersionPhasedReleases/{current['id']}")
        print(f"Версия {number}: поэтапная раскатка выключена — сразу всем")
    else:
        print(f"Версия {number}: поэтапная раскатка {'уже включена' if phased else 'и так выключена'}")


# ── выпуск и раскатка ──────────────────────────────────────────────────────

def release(client: AppStoreConnectClient, version: dict) -> None:
    number = (version.get("attributes") or {}).get("versionString")
    state = (version.get("attributes") or {}).get("appStoreState")
    if state != "PENDING_DEVELOPER_RELEASE":
        raise Stop(f"Версия {number} не ждёт выпуска — сейчас она {state}. Обновите данные на «Обзоре».")
    client.request(
        "POST",
        "/appStoreVersionReleaseRequests",
        json={"data": {
            "type": "appStoreVersionReleaseRequests",
            "relationships": {"appStoreVersion": {"data": {"type": "appStoreVersions", "id": version["id"]}}},
        }},
    )
    tail = "поэтапно, первый день — 1% автообновлений" if version.get("phased") else "сразу всем"
    print(f"Версия {number} отправлена в выпуск: {tail}. Apple выпускает её в течение нескольких минут.")


def phase(client: AppStoreConnectClient, version: dict, action: str) -> None:
    number = (version.get("attributes") or {}).get("versionString")
    phased = version.get("phased")
    if not phased:
        raise Stop(f"У версии {number} нет поэтапной раскатки — ставить на паузу и раскатывать нечего.")
    current = (phased.get("attributes") or {}).get("phasedReleaseState")
    if current not in PHASE_FROM[action]:
        raise Stop(f"Раскатка версии {number} сейчас {current} — «{action}» из этого состояния не делается.")
    target = PHASE_TARGET[action]
    client.request(
        "PATCH",
        f"/appStoreVersionPhasedReleases/{phased['id']}",
        json={"data": {"type": "appStoreVersionPhasedReleases", "id": phased["id"],
                       "attributes": {"phasedReleaseState": target}}},
    )
    done = {"PAUSED": "на паузе", "ACTIVE": "продолжается", "COMPLETE": "раскатано на всех"}[target]
    print(f"Раскатка версии {number}: {done}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", required=True, choices=ACTIONS)
    parser.add_argument("--version", default="", help="номер версии, которую видел человек")
    parser.add_argument("--release-type", default="", choices=("", *RELEASE_TYPES))
    parser.add_argument("--release-date", default="", help="ISO в UTC, для SCHEDULED")
    parser.add_argument("--phased", default="", choices=("", "on", "off"))
    parser.add_argument("--wait-seconds", type=int, default=1800)
    args = parser.parse_args()

    client = AppStoreConnectClient(
        key_id=require_env("ASC_KEY_ID"),
        issuer_id=require_env("ASC_ISSUER_ID"),
        key_path=Path(require_env("ASC_KEY_PATH")),
    )
    try:
        app = find_app(client, require_env("APP_IDENTIFIER"))
        if args.action == "settings":
            if not args.release_type:
                raise Stop("Не задан способ выпуска.")
            if args.release_type == "SCHEDULED" and not args.release_date:
                raise Stop("Для выпуска по дате нужна дата.")
            version = editable_version(client, app["id"], args.wait_seconds)
            phased = None if not args.phased else args.phased == "on"
            apply_settings(client, version, args.release_type, args.release_date or None, phased)
        else:
            if not args.version:
                raise Stop("Не задан номер версии.")
            version = by_version(versions_of(client, app["id"]), args.version)
            if args.action == "release":
                release(client, version)
            else:
                phase(client, version, args.action)
    except Stop as stop:
        print(f"ERROR: {stop}", file=sys.stderr)
        return 1
    except AppStoreConnectError as error:
        print(f"ERROR: App Store Connect отказал: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
