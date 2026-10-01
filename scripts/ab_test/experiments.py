#!/usr/bin/env python3
"""Работа с A/B-тестами продуктовой страницы (Product Page Optimization).

Что важно знать про эти ресурсы у Apple, прежде чем читать код:

* **Читаются тесты от версии, а создаются от приложения.** Список лежит по
  `GET /v1/appStoreVersions/{id}/appStoreVersionExperimentsV2`, а создание —
  `POST /v2/appStoreVersionExperiments` со связью на `apps`. Несимметрично, но
  так в документации.
* **Вариант по умолчанию — копия основной страницы.** Размер экрана, которому
  не дали своих кадров, вариант берёт с оригинала. Поэтому заливать все
  размеры не нужно, и пустой набор создавать тоже не нужно: отсутствие набора
  и есть «как у оригинала».
* **Удалить тест можно только до старта.** После — лишь остановить
  (`started: false`). Поэтому удаление здесь всегда проверяет состояние.
* **Варианты сверяем по идентификатору Apple, а не по имени.** Имя ПМ может
  поменять в App Store Connect, и сверка по нему порвалась бы молча.

Приложение должно быть опубликовано: тесты доступны только в состоянии
Ready for Distribution. Для приложения, которого нет в сторе, Apple вернёт
ошибку, и это правильное место, чтобы остановиться.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parent))
sys.path.insert(0, str(SCRIPT_DIR.parent / "lib"))

from upload_screenshots_api import (  # noqa: E402
    AppStoreConnectClient,
    AppStoreConnectError,
)

EXPERIMENT_FIELDS = (
    "name,state,trafficProportion,reviewRequired,startDate,endDate,platform"
)
TREATMENT_FIELDS = "name,promotedDate"

# Состояния, в которых тест ещё не показывался пользователям. Только из них
# Apple разрешает удаление.
NOT_STARTED = {"PREPARE_FOR_SUBMISSION", "READY_FOR_REVIEW", "WAITING_FOR_REVIEW",
               "IN_REVIEW", "REJECTED", "ACCEPTED"}


class Problem(Exception):
    pass


def live_version_id(client: AppStoreConnectClient, app_id: str) -> str:
    """Версия, к которой привязаны тесты, — та, что сейчас в сторе."""
    versions = client.get_all(
        f"/apps/{app_id}/appStoreVersions?filter[platform]=IOS"
        "&fields[appStoreVersions]=versionString,appStoreState&limit=20"
    )
    for version in versions:
        state = version["attributes"].get("appStoreState")
        if state in ("READY_FOR_SALE", "READY_FOR_DISTRIBUTION"):
            return version["id"]
    raise Problem(
        "у приложения нет версии в сторе — A/B-тесты доступны только для "
        "опубликованного приложения (состояние Ready for Distribution)")


def list_experiments(client: AppStoreConnectClient, app_id: str) -> list[dict[str, Any]]:
    """Тесты приложения вместе с вариантами, в виде, пригодном для консоли."""
    version_id = live_version_id(client, app_id)
    payload = client.request(
        "GET",
        f"/appStoreVersions/{version_id}/appStoreVersionExperimentsV2"
        f"?fields[appStoreVersionExperiments]={EXPERIMENT_FIELDS}"
        f"&include=appStoreVersionExperimentTreatments"
        f"&fields[appStoreVersionExperimentTreatments]={TREATMENT_FIELDS}&limit=50",
    )

    treatments_by_id = {
        item["id"]: item
        for item in payload.get("included", [])
        if item["type"] == "appStoreVersionExperimentTreatments"
    }

    out = []
    for row in payload.get("data", []):
        linked = (row.get("relationships", {})
                  .get("appStoreVersionExperimentTreatments", {})
                  .get("data") or [])
        out.append({
            "id": row["id"],
            "name": row["attributes"].get("name"),
            "state": row["attributes"].get("state"),
            "trafficProportion": row["attributes"].get("trafficProportion"),
            "reviewRequired": row["attributes"].get("reviewRequired"),
            "startDate": row["attributes"].get("startDate"),
            "endDate": row["attributes"].get("endDate"),
            "treatments": [
                {
                    "id": ref["id"],
                    "name": treatments_by_id.get(ref["id"], {})
                            .get("attributes", {}).get("name"),
                    "promotedDate": treatments_by_id.get(ref["id"], {})
                                    .get("attributes", {}).get("promotedDate"),
                }
                for ref in linked
            ],
        })
    return out


def create_experiment(client: AppStoreConnectClient, app_id: str, name: str,
                      traffic: int) -> dict[str, Any]:
    payload = client.request(
        "POST", "https://api.appstoreconnect.apple.com/v2/appStoreVersionExperiments",
        json={"data": {
            "type": "appStoreVersionExperiments",
            "attributes": {"platform": "IOS", "name": name,
                           "trafficProportion": int(traffic)},
            "relationships": {"app": {"data": {"type": "apps", "id": app_id}}},
        }})
    return payload["data"]


def create_treatment(client: AppStoreConnectClient, experiment_id: str,
                     name: str) -> dict[str, Any]:
    payload = client.request(
        "POST", "/appStoreVersionExperimentTreatments",
        json={"data": {
            "type": "appStoreVersionExperimentTreatments",
            "attributes": {"name": name},
            "relationships": {"appStoreVersionExperimentV2": {
                "data": {"type": "appStoreVersionExperiments", "id": experiment_id}}},
        }})
    return payload["data"]


def treatment_localizations(client: AppStoreConnectClient,
                            treatment_id: str) -> dict[str, str]:
    """Локаль → идентификатор локализации варианта."""
    rows = client.get_all(
        f"/appStoreVersionExperimentTreatments/{treatment_id}"
        "/appStoreVersionExperimentTreatmentLocalizations?limit=200")
    return {row["attributes"]["locale"]: row["id"] for row in rows}


def ensure_localization(client: AppStoreConnectClient, treatment_id: str,
                        locale: str, known: dict[str, str]) -> str:
    """Локализация варианта под локаль. Нет — заводим.

    Заводить приходится самим: вариант создаётся без локализаций, а кадры
    вешаются именно на локализацию.
    """
    if locale in known:
        return known[locale]

    payload = client.request(
        "POST", "/appStoreVersionExperimentTreatmentLocalizations",
        json={"data": {
            "type": "appStoreVersionExperimentTreatmentLocalizations",
            "attributes": {"locale": locale},
            "relationships": {"appStoreVersionExperimentTreatment": {
                "data": {"type": "appStoreVersionExperimentTreatments",
                         "id": treatment_id}}},
        }})
    known[locale] = payload["data"]["id"]
    return known[locale]


def set_started(client: AppStoreConnectClient, experiment_id: str,
                started: bool) -> None:
    client.request(
        "PATCH",
        f"https://api.appstoreconnect.apple.com/v2/appStoreVersionExperiments/{experiment_id}",
        json={"data": {
            "type": "appStoreVersionExperiments",
            "id": experiment_id,
            "attributes": {"started": started},
        }})


def delete_experiment(client: AppStoreConnectClient, experiment_id: str,
                      state: str | None) -> None:
    """Удаляет тест. Запущенный Apple удалять не даёт — объясняем это заранее."""
    if state and state not in NOT_STARTED:
        raise Problem(
            f"тест в состоянии {state} — удалить его Apple не даёт. "
            "Запущенный тест можно только остановить; он останется в истории "
            "вместе со своей статистикой")
    try:
        client.request(
            "DELETE",
            f"https://api.appstoreconnect.apple.com/v2/appStoreVersionExperiments/{experiment_id}")
    except AppStoreConnectError as error:
        raise Problem(f"Apple отказалась удалять тест: {error}") from error
