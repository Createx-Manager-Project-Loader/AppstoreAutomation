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
    """Один шаг: применить, потом прочитать обратно и сверить."""

    def __init__(self, name: str, want: Any, apply, read) -> None:
        self.name, self.want, self.apply, self.read = name, want, apply, read


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
                                self.set_content_rights, self.get_content_rights))

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
                            self.set_age_rating, self.get_age_rating))

        tier = self.field("pricing.tier", required=False)
        if tier:
            out.append(Step("цена", str(tier).strip().lower(), self.set_price, self.get_price))

        countries = self.field("pricing.countries", required=False)
        if countries:
            # Ожидание разворачивается здесь, а не при сверке: «worldwide» это
            # список территорий, который ASC выдаёт сам, и сверять строку с
            # множеством кодов было бы сравнением разного с разным.
            out.append(Step("страны", set(self.wanted_territories(countries)),
                            lambda want: self.set_countries(countries),
                            self.get_countries))

        idfa = self.field("declarations.uses_idfa", required=False)
        if idfa is not None:
            try:
                want = self.as_bool(idfa, "declarations.uses_idfa")
                out.append(Step("рекламный идентификатор", want, self.set_idfa, self.get_idfa))
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
        if isinstance(want, str) and want.strip().lower() == "worldwide":
            return [t["id"] for t in self.client.get_all("/territories?limit=200")]
        codes = want if isinstance(want, list) else str(want).replace(",", " ").split()
        return [str(code).strip().upper() for code in codes if str(code).strip()]

    def territory_rows(self) -> dict[str, dict]:
        """Текущая доступность по странам: код ISO-3 → строка ASC.

        include=territory обязателен: без него ASC отдаёт строки вообще без
        связей, и понять, к какой стране относится строка, становится нечем —
        разве что расшифровывать её непрозрачный id, чего делать не стоит.
        """
        payload = self.client.request(
            "GET", f"https://api.appstoreconnect.apple.com/v2/appAvailabilities/"
                   f"{self.app_id}/territoryAvailabilities?limit=200&include=territory")
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

    failures = []
    for step in steps:
        try:
            if args.dry_run:
                print(f"  — {step.name}: поставил бы {short(step.want)}")
                continue
            if not args.verify:
                step.apply(step.want)
            got, ok = read_back(step, attempts=1 if args.verify else 4)
            mark = "OK " if ok else "НЕТ"
            if isinstance(step.want, dict):
                matched = sum(1 for k, v in step.want.items()
                              if isinstance(got, dict) and str(got.get(k)).lower() == str(v).lower())
                print(f"  {mark} {step.name}: совпало {matched} из {len(step.want)} ответов анкеты")
            else:
                print(f"  {mark} {step.name}: хотели {short(step.want)}, в сторе {short(got)}")
            if not ok:
                failures.append(step.name)
        except (Problem, AppStoreConnectError) as error:
            print(f"  НЕТ {step.name}: {error}", file=sys.stderr)
            failures.append(step.name)

    if failures:
        print(f"ERROR: не встало: {', '.join(failures)}", file=sys.stderr)
        return 1
    if setup.skipped:
        print(f"\nПропущено: {len(setup.skipped)} — в стор не уедет, останется пустым:")
        for line in setup.skipped:
            print(f"  - {line}")

    if not args.dry_run:
        print(f"Проверено обратным чтением: {len(steps)} из {len(steps)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
