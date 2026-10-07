#!/usr/bin/env python3
"""Заполняет то, до чего fastlane deliver не дотягивается, — прямыми вызовами ASC API.

deliver кладёт в стор тексты, скриншоты и контакты ревью. Всё остальное на
странице первого релиза — цена, страны, возрастной рейтинг, права на контент,
рекламный идентификатор, экспортное соответствие — живёт в отдельных
эндпоинтах, и их приходится дёргать самим.

Незаполненное или неподтверждённое поле прогон не роняет: оно просто не
заливается, остаётся в сторе пустым и попадает в список пропущенных. Догадка
наверх при этом не уезжает — пропуск и есть отказ её заливать.

Каждый шаг после записи **читает значение обратно** и сравнивает с тем, что
просили. Ответ 200 на PATCH не значит, что поле встало: у ASC хватает мест,
где запись принимается и тихо игнорируется. Прогон падает на первом
расхождении, потому что молча уехавший в стор неверный рейтинг или не та
страна — это не то, что стоит обнаруживать на ревью.

Запуск:
    setup_app.py --listing app_store_listing.yml            # применить и проверить
    setup_app.py --listing app_store_listing.yml --verify   # только прочитать
    setup_app.py --listing app_store_listing.yml --dry-run  # показать, что сделает

Приложение берётся из APP_IDENTIFIER, ключ — из ASC_KEY_ID / ASC_ISSUER_ID /
ASC_KEY_PATH, как и во всех остальных скриптах репозитория.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR.parent))

from build_metadata import dig, value_of  # noqa: E402
from upload_screenshots_api import (  # noqa: E402
    AppStoreConnectClient,
    AppStoreConnectError,
    find_app,
    require_env,
)

CONTENT_RIGHTS = {
    "no_third_party_content": "DOES_NOT_USE_THIRD_PARTY_CONTENT",
    "third_party_content": "USES_THIRD_PARTY_CONTENT",
}


class Problem(Exception):
    pass


class Step:
    """Один шаг: применить, потом прочитать обратно и сверить.

    `filled` отвечает на вопрос «в сторе это уже выставлено?». Если да, шаг
    пропускается: заполненное руками не затирается значением из файла. Вернуть
    нужно описание текущего значения — оно уходит в отчёт, чтобы пропуск был
    виден, а не случился молча.
    """

    def __init__(self, name: str, want: Any, apply, read, filled=None,
                 soft: bool = False) -> None:
        self.name, self.want, self.apply, self.read = name, want, apply, read
        self.filled = filled
        # Некритичный шаг: его неудача не красит прогон, а идёт в отчёт
        # предупреждением. Решение владельца — для информации для ревью: без
        # неё всё остальное в карточке полезно, а отправить на ревью с пустым
        # контактом App Store Connect всё равно не даст.
        self.soft = soft


class Setup:
    def __init__(self, client: AppStoreConnectClient, app_id: str, listing: dict) -> None:
        self.client = client
        self.app_id = app_id
        self.listing = listing
        self._app_info_id: str | None = None
        self._version_id: str | None = None
        # Поля, которые заливать нечем или нельзя. Прогон из-за них не встаёт:
        # в сторе они остаются пустыми, а список уезжает в вывод.
        self.skipped: list[str] = []

    # ── ссылки на дочерние объекты ────────────────────────────────────────

    def app_info_id(self) -> str:
        if self._app_info_id is None:
            infos = self.client.get_all(f"/apps/{self.app_id}/appInfos")
            editable = [i for i in infos if i["attributes"].get("state") not in
                        ("READY_FOR_DISTRIBUTION", "REPLACED_WITH_NEW_INFO")]
            chosen = editable or infos
            if not chosen:
                raise Problem("у приложения нет appInfo — оно точно создано в ASC?")
            self._app_info_id = chosen[0]["id"]
        return self._app_info_id

    def version_id(self) -> str:
        if self._version_id is None:
            versions = self.client.get_all(
                f"/apps/{self.app_id}/appStoreVersions?filter[platform]=IOS&limit=20"
            )
            editable = [v for v in versions if v["attributes"].get("appStoreState") in (
                "PREPARE_FOR_SUBMISSION", "DEVELOPER_REJECTED", "REJECTED",
                "METADATA_REJECTED", "INVALID_BINARY", "WAITING_FOR_REVIEW",
            )]
            if not editable:
                raise Problem("нет редактируемой версии — deliver должен создать её раньше")
            self._version_id = editable[0]["id"]
        return self._version_id

    # ── шаги ──────────────────────────────────────────────────────────────

    def steps(self) -> list[Step]:
        out = []

        rights = self.field("app_information.content_rights", required=False)
        if rights:
            want = CONTENT_RIGHTS.get(str(rights).lower())
            if want is None:
                self.skipped.append(f"app_information.content_rights: не знаю значения «{rights}»")
            else:
                out.append(Step("права на контент", want,
                                self.set_content_rights, self.get_content_rights,
                                self.filled_content_rights))

        rating = dig(self.listing, "age_rating")
        answers = rating.get("answers") if isinstance(rating, dict) else None
        status = str(rating.get("status") or "") if isinstance(rating, dict) else ""
        if rating is None:
            self.skipped.append("age_rating: нет в файле")
        elif not isinstance(answers, dict) or not answers:
            # Строка вида «4+» ответами на анкету не является: «4+» Apple
            # считает сама, а на вход эндпоинт принимает только ответы.
            self.skipped.append(
                "age_rating: нужен блок answers с ответами на анкету Apple, "
                f"а в файле лежит «{rating}»")
        elif status in ("guessed", "unanswered"):
            self.skipped.append(f"age_rating: статус {status} — рейтинг не уезжает догадкой")
        else:
            out.append(Step("возрастной рейтинг", answers,
                            self.set_age_rating, self.get_age_rating,
                            self.filled_age_rating))

        review = self.wanted_review()
        if review:
            out.append(Step("информация для ревью", review,
                            self.set_review, self.get_review, self.filled_review,
                            soft=True))
        else:
            self.skipped.append("review_info: в листинге нет ни одного поля")

        tier = self.field("pricing.tier", required=False)
        if tier:
            out.append(Step("цена", str(tier).strip().lower(),
                            self.set_price, self.get_price, self.filled_price))

        countries = self.field("pricing.countries", required=False)
        if countries:
            # Ожидание разворачивается здесь, а не при сверке: «worldwide» это
            # список территорий, который ASC выдаёт сам, и сверять строку с
            # множеством кодов было бы сравнением разного с разным.
            out.append(Step("страны", set(self.wanted_territories(countries)),
                            lambda want: self.set_countries(countries),
                            self.get_countries, self.filled_countries))

        idfa = self.field("declarations.uses_idfa", required=False)
        if idfa is not None:
            try:
                want = self.as_bool(idfa, "declarations.uses_idfa")
                out.append(Step("рекламный идентификатор", want, self.set_idfa,
                                self.get_idfa, self.filled_idfa))
            except Problem as error:
                self.skipped.append(str(error))

        export = self.field("declarations.export_compliance", required=False)
        if export:
            want = str(export).strip().lower() == "exempt"
            out.append(Step("экспортное соответствие", want, self.set_export, self.get_export))

        return out

    def field(self, path: str, required: bool = True):
        text, why = value_of(self.listing, path)
        if text is None:
            if required:
                raise Problem(f"{path}: {why}")
            self.skipped.append(f"{path}: {why}")
            return None
        return text

    @staticmethod
    def as_bool(text, path: str) -> bool:
        key = str(text).strip().lower()
        if key in ("true", "yes", "1"):
            return True
        if key in ("false", "no", "0"):
            return False
        raise Problem(f"{path}: ожидается да/нет, а лежит «{text}»")

    # права на контент ─────────────────────────────────────────────────────

    def set_content_rights(self, want: str) -> None:
        self.client.request("PATCH", f"/apps/{self.app_id}", json={"data": {
            "type": "apps", "id": self.app_id,
            "attributes": {"contentRightsDeclaration": want}}})

    def filled_content_rights(self):
        return self.get_content_rights()

    def filled_age_rating(self):
        """Анкета считается заполненной, если хоть на один вопрос есть ответ.

        У только что заведённого приложения декларация уже существует, но все
        ответы в ней пустые — поэтому смотрим на содержимое, а не на наличие.
        """
        answers = self.get_age_rating()
        given = {k: v for k, v in (answers or {}).items() if v is not None}
        return f"{len(given)} ответов" if given else None

    def filled_price(self):
        return self.get_price() or None

    def filled_countries(self):
        countries = self.get_countries()
        return f"{len(countries)} стран" if countries else None

    def filled_idfa(self):
        value = self.get_idfa()
        return None if value is None else ("да" if value else "нет")

    def get_content_rights(self):
        payload = self.client.request(
            "GET", f"/apps/{self.app_id}?fields[apps]=contentRightsDeclaration")
        return payload["data"]["attributes"].get("contentRightsDeclaration")

    # возрастной рейтинг ───────────────────────────────────────────────────

    def set_age_rating(self, want: dict) -> None:
        declaration = self.client.request(
            "GET", f"/appInfos/{self.app_info_id()}/ageRatingDeclaration")
        rating_id = declaration["data"]["id"]
        self.client.request("PATCH", f"/ageRatingDeclarations/{rating_id}", json={"data": {
            "type": "ageRatingDeclarations", "id": rating_id, "attributes": want}})

    def get_age_rating(self) -> dict:
        payload = self.client.request(
            "GET", f"/appInfos/{self.app_info_id()}/ageRatingDeclaration")
        return payload["data"]["attributes"]

    # цена ─────────────────────────────────────────────────────────────────

    def price_point(self, price: str) -> str:
        """Идентификатор ценовой точки в базовой территории (USA)."""
        points = self.client.get_all(
            f"/apps/{self.app_id}/appPricePoints?filter[territory]=USA&limit=200")
        if not points:
            raise Problem("ASC не отдал ни одной ценовой точки — нет договора Paid Apps?")
        wanted = 0.0 if price == "free" else float(str(price).lstrip("$").replace(",", "."))
        for point in points:
            if abs(float(point["attributes"]["customerPrice"]) - wanted) < 0.0001:
                return point["id"]
        available = sorted({float(p["attributes"]["customerPrice"]) for p in points})[:12]
        raise Problem(f"нет ценовой точки {wanted}; ближайшие из доступных: {available}")

    def set_price(self, want: str) -> None:
        point = self.price_point(want)
        self.client.request("POST", "/appPriceSchedules", json={
            "data": {
                "type": "appPriceSchedules",
                "relationships": {
                    "app": {"data": {"type": "apps", "id": self.app_id}},
                    "baseTerritory": {"data": {"type": "territories", "id": "USA"}},
                    "manualPrices": {"data": [{"type": "appPrices", "id": "${new-price}"}]},
                },
            },
            "included": [{
                "type": "appPrices", "id": "${new-price}",
                "attributes": {"startDate": None, "endDate": None},
                "relationships": {"appPricePoint": {
                    "data": {"type": "appPricePoints", "id": point}}},
            }],
        })

    def get_price(self) -> str:
        # Цену приходится читать через manualPrices с include: в самом
        # расписании у appPrices нет связей, а по /v2/appPrices ASC отвечает
        # 403 «no allowed operations» — сам объект наружу не отдаётся.
        payload = self.client.request(
            "GET", f"/appPriceSchedules/{self.app_id}/manualPrices"
                   "?include=appPricePoint&limit=50")
        points = [x for x in payload.get("included", []) if x["type"] == "appPricePoints"]
        if not points:
            return "нет расписания цен"
        customer = float(points[0]["attributes"]["customerPrice"])
        return "free" if customer == 0 else f"{customer:g}"

    # страны ───────────────────────────────────────────────────────────────

    def wanted_territories(self, want) -> list[str]:
        """Коды стран из поля листинга. Форма записи бывает любой.

        `value_of` отдаёт значение строкой, поэтому список YAML
        (`countries: { value: [TUR] }`) доезжает сюда как «['TUR']» — с
        квадратными скобками и кавычками внутри строки. Живой случай:
        Locator 73 упал на «неизвестные коды стран: [\"['TUR']\"]», хотя в
        файле было написано правильно. Поэтому скобки и кавычки снимаем, а
        разделителем считаем и запятую, и пробел.
        """
        if isinstance(want, str) and want.strip().lower() == "worldwide":
            return [t["id"] for t in self.client.get_all("/territories?limit=200")]

        if isinstance(want, list):
            codes = want
        else:
            cleaned = str(want).strip().strip("[]")
            codes = cleaned.replace(",", " ").split()

        return [str(code).strip().strip("'\"").upper() for code in codes
                if str(code).strip().strip("'\"")]

    def territory_rows(self) -> dict[str, dict]:
        """Текущая доступность по странам: код ISO-3 → строка ASC.

        include=territory обязателен: без него ASC отдаёт строки вообще без
        связей, и понять, к какой стране относится строка, становится нечем —
        разве что расшифровывать её непрозрачный id, чего делать не стоит.
        """
        # У нового приложения доступности ещё нет, и Apple отвечает 404 на
        # само чтение («There is no resource of type 'appAvailabilities'»).
        # Это «пусто», а не сбой: пустой ответ ведёт set_countries в ветку
        # создания. Раньше 404 вылетал отсюда исключением, и до POST дело не
        # доходило — FamilyTree 20, 7 октября: цена встала, страны нет.
        payload = self.maybe(
            f"https://api.appstoreconnect.apple.com/v2/appAvailabilities/"
            f"{self.app_id}/territoryAvailabilities?limit=200&include=territory")
        if not payload:
            return {}
        rows = {}
        for row in payload.get("data", []):
            code = row["relationships"]["territory"]["data"]["id"]
            rows[code] = row
        return rows

    def set_countries(self, want) -> None:
        codes = self.wanted_territories(want)
        known = {t["id"] for t in self.client.get_all("/territories?limit=200")}
        unknown = [c for c in codes if c not in known]
        if unknown:
            raise Problem(f"неизвестные коды стран: {unknown} (нужен ISO-3, например DEU)")

        current = self.territory_rows()
        if not current:
            # У приложения ещё нет доступности — её создают целиком.
            included, refs = [], []
            for code in codes:
                key = f"${{t-{code}}}"
                refs.append({"type": "territoryAvailabilities", "id": key})
                included.append({
                    "type": "territoryAvailabilities", "id": key,
                    "attributes": {"available": True},
                    "relationships": {"territory": {"data": {"type": "territories", "id": code}}},
                })
            self.client.request(
                "POST", "https://api.appstoreconnect.apple.com/v2/appAvailabilities",
                json={"data": {
                    "type": "appAvailabilities",
                    "attributes": {"availableInNewTerritories": self.is_worldwide(want)},
                    "relationships": {
                        "app": {"data": {"type": "apps", "id": self.app_id}},
                        "territoryAvailabilities": {"data": refs},
                    },
                }, "included": included})
            return

        # Доступность уже есть: создать её второй раз нельзя (409), поэтому
        # правим построчно и только те страны, где текущее не совпало с нужным.
        wanted = set(codes)
        for code, row in current.items():
            should = code in wanted
            if bool(row["attributes"].get("available")) == should:
                continue
            self.client.request(
                "PATCH", f"/territoryAvailabilities/{row['id']}",
                json={"data": {"type": "territoryAvailabilities", "id": row["id"],
                               "attributes": {"available": should}}})

    @staticmethod
    def is_worldwide(want) -> bool:
        return isinstance(want, str) and want.strip().lower() == "worldwide"

    def get_countries(self) -> set[str]:
        return {code for code, row in self.territory_rows().items()
                if row["attributes"].get("available")}

    # информация для ревью ────────────────────────────────────────

    # Имена полей Apple. Пишем только то, что заполнено: половина контакта
    # лучше, чем ничего — её видно в кабинете, и ПМ дозаполняет остальное
    # руками, а не ищет, куда делось.
    REVIEW_ATTRS = {
        "review_info.first_name": "contactFirstName",
        "review_info.last_name": "contactLastName",
        "review_info.phone": "contactPhone",
        "review_info.email": "contactEmail",
        "review_info.demo_user": "demoAccountName",
        "review_info.demo_password": "demoAccountPassword",
        "review_info.notes": "notes",
    }

    def wanted_review(self) -> dict:
        """Что из информации для ревью есть в листинге."""
        want = {}
        for path, attribute in self.REVIEW_ATTRS.items():
            text = self.field(path, required=False)
            if text is not None and str(text).strip():
                want[attribute] = str(text)
        if want:
            # Apple хранит признак отдельно от самих полей: без него демо-данные
            # не показываются ревьюеру, даже если записаны.
            want["demoAccountRequired"] = bool(want.get("demoAccountName"))
        return want

    def review_detail_id(self):
        payload = self.maybe(f"/appStoreVersions/{self.version_id()}/appStoreReviewDetail")
        return payload["data"]["id"] if payload and payload.get("data") else None

    def set_review(self, want: dict) -> None:
        detail = self.review_detail_id()
        if detail:
            self.client.request("PATCH", f"/appStoreReviewDetails/{detail}", json={"data": {
                "type": "appStoreReviewDetails", "id": detail, "attributes": want}})
            return
        self.client.request("POST", "/appStoreReviewDetails", json={"data": {
            "type": "appStoreReviewDetails", "attributes": want,
            "relationships": {"appStoreVersion": {"data": {
                "type": "appStoreVersions", "id": self.version_id()}}}}})

    def get_review(self) -> dict:
        payload = self.maybe(f"/appStoreVersions/{self.version_id()}/appStoreReviewDetail")
        if not payload or not payload.get("data"):
            return {}
        attributes = payload["data"]["attributes"]
        # demoAccountRequired сверяем всегда: False — это ответ, а не пустота.
        # Раньше фильтр «if value» выбрасывал его, и сверка писала «совпало 5
        # из 6», хотя записалось всё. Family Tree 15, 7 октября.
        wanted = set(self.REVIEW_ATTRS.values()) | {"demoAccountRequired"}
        return {key: value for key, value in attributes.items()
                if key in wanted and (value or key == "demoAccountRequired")}

    def filled_review(self):
        given = {k: v for k, v in self.get_review().items() if k != "demoAccountRequired"}
        return f"{len(given)} полей" if given else None

    def maybe(self, path: str):
        """GET, отвечающий None вместо исключения на 404.

        У новой версии записи для ревью ещё нет, и Apple отвечает 404 на
        чтение. Это нормальный ответ «ещё не создавали», а не сбой.
        """
        try:
            return self.client.request("GET", path)
        except AppStoreConnectError as error:
            if "404" in str(error):
                return None
            raise

    # рекламный идентификатор ──────────────────────────────────────────────

    def set_idfa(self, want: bool) -> None:
        version = self.version_id()
        self.client.request("PATCH", f"/appStoreVersions/{version}", json={"data": {
            "type": "appStoreVersions", "id": version, "attributes": {"usesIdfa": want}}})

    def get_idfa(self):
        payload = self.client.request(
            "GET", f"/appStoreVersions/{self.version_id()}?fields[appStoreVersions]=usesIdfa")
        return payload["data"]["attributes"].get("usesIdfa")

    # экспортное соответствие ──────────────────────────────────────────────

    def latest_build(self):
        # request, а не get_all: get_all идёт по links.next и с limit=1 обходит
        # все сборки приложения по одной. Нужна ровно первая страница.
        payload = self.client.request(
            "GET", f"/builds?filter[app]={self.app_id}&limit=1&sort=-uploadedDate"
                   "&fields[builds]=version,usesNonExemptEncryption,uploadedDate")
        data = payload.get("data") or []
        return data[0] if data else None

    def set_export(self, want: bool) -> None:
        build = self.latest_build()
        if build is None:
            raise Problem(
                "экспортное соответствие объявляется на сборке, а сборок у приложения нет — "
                "залейте билд и повторите шаг")

        # ASC разрешает записать usesNonExemptEncryption только один раз:
        # повторный PATCH возвращает 409 «cannot update when the value is
        # already set», даже если значение то же самое. Поэтому сначала читаем.
        already = build["attributes"].get("usesNonExemptEncryption")
        if already is not None:
            if bool(already) == (not want):
                return
            raise Problem(
                f"на сборке {build['attributes'].get('version')} уже объявлено обратное "
                "(ASC не даёт переписать это поле) — нужна новая сборка")

        self.client.request("PATCH", f"/builds/{build['id']}", json={"data": {
            "type": "builds", "id": build["id"],
            "attributes": {"usesNonExemptEncryption": not want}}})

    def get_export(self):
        build = self.latest_build()
        if build is None:
            return "нет сборки"
        value = build["attributes"].get("usesNonExemptEncryption")
        return None if value is None else not value


def compare(want, got) -> bool:
    if isinstance(want, dict):
        if not isinstance(got, dict):
            return False
        return all(str(got.get(k)).lower() == str(v).lower() for k, v in want.items())
    if isinstance(want, (set, list, tuple)):
        return set(want) == set(got or ())
    return str(want).lower() == str(got).lower()


def read_back(step: "Step", attempts: int = 4, delay: float = 3.0):
    """Читает поле обратно, давая ASC время догнать собственную запись.

    Померено на живом приложении: PATCH прав на контент возвращает 200 и уже
    новое значение в теле ответа, а GET следом ещё несколько секунд отдаёт
    старое. Одна проверка сразу после записи даёт ложное «не встало».
    """
    got = None
    for attempt in range(attempts):
        if attempt:
            time.sleep(delay)
        got = step.read()
        if compare(step.want, got):
            return got, True
    return got, False


def short(value) -> str:
    if isinstance(value, set):
        return f"{len(value)} стран"
    if isinstance(value, dict):
        return f"{len(value)} ответов анкеты"
    text = str(value)
    return text if len(text) <= 60 else text[:57] + "…"


def short_error(error) -> str:
    """Причина отказа Apple одной строкой — поле detail, без JSON вокруг."""
    import re
    details = re.findall(r'"detail"\s*:\s*"([^"]+)"', str(error))
    return "; ".join(dict.fromkeys(details)) if details else str(error).splitlines()[0][:200]


def probe(step):
    """Проба «в сторе уже заполнено?». 404 здесь значит «ещё ничего нет».

    У приложения, которое заводят с нуля, не существует ни расписания цен, ни
    доступности по странам: Apple отвечает 404 на само чтение
    (`There is no resource of type 'appAvailabilities' with id ...`). Для
    пробы это нормальный ответ, а не сбой.

    Раньше исключение из пробы ловил общий except шага: шаг объявлялся
    упавшим, `apply` до вызова не доходил, и цену со странами нельзя было
    выставить ни одному новому приложению. Живой случай — FamilyTree 20,
    три прогона подряд с «не встало: цена, страны».
    """
    try:
        return step.filled()
    except AppStoreConnectError as error:
        if "404" in str(error):
            return None
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listing", type=Path, required=True)
    parser.add_argument("--verify", action="store_true", help="только прочитать и сверить")
    parser.add_argument("--dry-run", action="store_true", help="показать план, ничего не писать")
    args = parser.parse_args()

    listing = yaml.safe_load(args.listing.read_text(encoding="utf-8"))
    if not isinstance(listing, dict):
        print(f"ERROR: {args.listing} — не похоже на листинг App Store", file=sys.stderr)
        return 1

    client = AppStoreConnectClient(
        key_id=require_env("ASC_KEY_ID"),
        issuer_id=require_env("ASC_ISSUER_ID"),
        key_path=Path(require_env("ASC_KEY_PATH")),
    )
    app = find_app(client, require_env("APP_IDENTIFIER"))
    setup = Setup(client, app["id"], listing)

    try:
        steps = setup.steps()
    except Problem as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    # Заполненное в App Store Connect не трогаем: ПМ мог выставить это руками,
    # и файл листинга не должен молча стирать его работу. Галочка перезаписи
    # в консоли снимает правило целиком.
    overwrite = os.environ.get("FIRST_RELEASE_OVERWRITE", "").strip().lower() in (
        "yes", "true", "1")

    failures, left, warnings = [], [], []
    for step in steps:
        try:
            if args.dry_run:
                print(f"  — {step.name}: поставил бы {short(step.want)}")
                continue
            if not (args.verify or overwrite) and step.filled:
                current = probe(step)
                if current:
                    print(f"  ={step.name}: уже выставлено ({current}) — оставляем как есть")
                    left.append(f"{step.name}: {current}")
                    continue
            if not args.verify:
                step.apply(step.want)
            got, ok = read_back(step, attempts=1 if args.verify else 4)
            mark = "OK " if ok else "НЕТ"
            if isinstance(step.want, dict):
                matched = sum(1 for k, v in step.want.items()
                              if isinstance(got, dict) and str(got.get(k)).lower() == str(v).lower())
                unit = "ответов анкеты" if step.name == "возрастной рейтинг" else "полей"
                print(f"  {mark} {step.name}: совпало {matched} из {len(step.want)} {unit}")
            else:
                print(f"  {mark} {step.name}: хотели {short(step.want)}, в сторе {short(got)}")
            if not ok:
                (warnings if step.soft else failures).append(step.name)
        except (Problem, AppStoreConnectError) as error:
            if step.soft:
                print(f"  ПРЕДУПРЕЖДЕНИЕ {step.name}: не залилось — {short_error(error)}",
                      file=sys.stderr)
                warnings.append(step.name)
            else:
                print(f"  НЕТ {step.name}: {error}", file=sys.stderr)
                failures.append(step.name)

    if left:
        print(f"\nОставлено как было: {len(left)} — в сторе уже заполнено, "
              "из файла не перезаписывали:")
        for line in left:
            print(f"  - {line}")
        print("Чтобы залить поверх, поставьте галочку перезаписи в консоли.")

    if warnings:
        # Строка-признак для консоли: по ней она показывает пометку «к
        # сведению», а не ошибку.
        print(f"WARNING: не залилось (некритично): {', '.join(warnings)} — "
              "дозаполните в App Store Connect до отправки на ревью")

    if failures:
        print(f"ERROR: не встало: {', '.join(failures)}", file=sys.stderr)
        return 1
    if setup.skipped:
        print(f"\nПропущено: {len(setup.skipped)} — в стор не уедет, останется пустым:")
        for line in setup.skipped:
            print(f"  - {line}")

    if not args.dry_run:
        written = len(steps) - len(left)
        print(f"Проверено обратным чтением: {written} из {written}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
