#!/usr/bin/env python3
"""Дозаполняет описания в ASO-таблице машинным переводом.

Набор языков задаёт сам файл: берём те, что перечислены на листе ASO. Для
каждого, где описание пустое, переводим с английского и дописываем в таблицу.
Английские варианты (AU/CA/UK) не переводим — им кладём английский текст.

Заполненные ячейки не трогаем никогда: чужую работу перезаписывать нельзя.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR / "lib"))

DESCRIPTION_LIMIT = 4000

# Значение должно совпадать с тем, что проверяет дашборд.
PASSPORT_AUDIENCE = "asc-console"

# Язык в таблице → код переводчика. Проверено запросами к сервису: работают
# все, кроме мексиканского испанского — для него берём обычный испанский.
TRANSLATOR_CODES = {
    "arabic": "AR",
    "catalan": "CA",
    "chinese simplified": "ZH-HANS",
    "chinese traditional": "ZH-HANT",
    "croatian": "HR",
    "czech": "CS",
    "danish": "DA",
    "dutch": "NL",
    "finnish": "FI",
    "french": "FR",
    "french ca": "FR-CA",
    "german": "DE",
    "greek": "EL",
    "hebrew": "HE",
    "hindi": "HI",
    "hungarian": "HU",
    "indonesian": "ID",
    "italian": "IT",
    "japanese": "JA",
    "korean": "KO",
    "malay": "MS",
    "norwegian": "NB",
    "polish": "PL",
    "portuguese br": "PT-BR",
    "portuguese pt": "PT-PT",
    "romanian": "RO",
    "russian": "RU",
    "slovak": "SK",
    # Мексиканского испанского у сервиса нет — переводим общим испанским.
    "spanish mx": "ES",
    "spanish es": "ES",
    "swedish": "SV",
    "thai": "TH",
    "turkish": "TR",
    "ukranian": "UK",
    "ukrainian": "UK",
    "vietnamese": "VI",
}


def log(message: str) -> None:
    print(f"[translate] {message}", flush=True)


# Паспорт живёт минуты — на один прогон его достаточно, кешируем в процессе.
_PASSPORT: str | None = None


def request_passport() -> str:
    """Удостоверение прогона от GitHub.

    Секрета у экшена нет: он просит GitHub подтвердить, кто он такой, и
    предъявляет это дашборду. Тот проверяет подпись и организацию.
    """
    global _PASSPORT
    if _PASSPORT:
        return _PASSPORT

    url = os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL", "").strip()
    token = os.environ.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN", "").strip()

    if not url or not token:
        raise SystemExit(
            "GitHub не выдал удостоверение. В workflow должно стоять "
            "permissions: id-token: write"
        )

    request = urllib.request.Request(
        f"{url}&audience={PASSPORT_AUDIENCE}",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))

    value = (data.get("value") or "").strip()
    if not value:
        raise SystemExit("GitHub вернул пустое удостоверение")

    _PASSPORT = value
    return value


def translate(text: str, code: str, attempts: int = 3) -> str:
    """Просит дашборд перевести текст. Токен переводчика остаётся у него."""
    dashboard = os.environ.get("DASHBOARD_URL", "").strip().rstrip("/")
    if not dashboard:
        raise SystemExit("Не задан DASHBOARD_URL — перевод невозможен")

    payload = json.dumps({"text": text, "code": code}).encode("utf-8")
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        request = urllib.request.Request(
            f"{dashboard}/api/translate",
            data=payload,
            headers={
                "Authorization": f"Bearer {request_passport()}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                data = json.loads(response.read().decode("utf-8"))
            result = (data.get("translation") or "").strip()
            if result:
                return result
            last_error = RuntimeError("пустой перевод")
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", "replace")[:200]
            # 401/403 — дело не во временном сбое, повторять бессмысленно.
            if error.code in (401, 403):
                raise RuntimeError(f"доступ отклонён ({error.code}): {body}") from error
            last_error = RuntimeError(f"HTTP {error.code}: {body}")
        except (urllib.error.URLError, TimeoutError, ValueError) as error:
            last_error = error

        if attempt < attempts:
            time.sleep(2 * attempt)

    raise RuntimeError(f"{last_error}")


def normalize_column_format(service, spreadsheet_id: str, sheet_name: str) -> None:
    """Приводит колонку описаний в читаемый вид: выравнивание и перенос строк.

    Выравнивание. Блоки дописываются с insertDataOption=INSERT_ROWS, а
    вставленная строка в Google Sheets наследует формат строки над собой. Над
    первым дописанным блоком стоит счётчик символов — число с выравниванием
    вправо, — и «вправо» расползалось по цепочке на все языки подряд. Выглядело
    так, будто виноват арабский: он просто первый по алфавиту.

    Сбрасываем не в LEFT, а в «не задано»: тогда Sheets сам ставит текст влево,
    числа вправо, а арабский и иврит разворачивает как положено.

    Перенос строк. Описание длиной за тысячу символов по умолчанию вылезает на
    соседние столбцы и закрывает их. WRAP держит текст внутри своей ячейки.
    """
    try:
        meta = (
            service.spreadsheets()
            .get(spreadsheetId=spreadsheet_id, fields="sheets(properties(sheetId,title))")
            .execute()
        )
        sheet_id = next(
            sheet["properties"]["sheetId"]
            for sheet in meta.get("sheets", [])
            if sheet["properties"]["title"] == sheet_name
        )

        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={
                "requests": [
                    {
                        "repeatCell": {
                            # Вся колонка B этого листа — там и живут блоки.
                            "range": {
                                "sheetId": sheet_id,
                                "startColumnIndex": 1,
                                "endColumnIndex": 2,
                            },
                            # Выравнивание очищаем — по канону Sheets это
                            # отсутствие поля в ячейке плюс маска. Имя значения
                            # перечисления не указываем вовсе: именно на
                            # выдуманной константе первая попытка словила 400.
                            # Перенос строк, наоборот, выставляем явно.
                            "cell": {"userEnteredFormat": {"wrapStrategy": "WRAP"}},
                            "fields": (
                                "userEnteredFormat.horizontalAlignment,"
                                "userEnteredFormat.wrapStrategy"
                            ),
                        }
                    }
                ]
            },
        ).execute()
        log("Колонка описаний приведена в порядок: выравнивание и перенос строк")
    except Exception as error:  # noqa: BLE001
        # Косметика не должна ронять заливку: переводы уже записаны.
        log(f"ВНИМАНИЕ: не удалось поправить формат колонки — {error}")


def main() -> int:
    from prepare_metadata import (
        aso_xlsx_path,
        get_google_sheet_url,
        locales_for_name,
        normalize_name,
        read_xlsx_sheet,
        resolve_sheet_name,
        xlsx_sheet_paths,
    )
    import zipfile
    from google_drive_auth import build_sheets_service, google_drive_file_id

    if os.environ.get("ASC_TRANSLATE", "true").strip().lower() in {"0", "false", "no", "off"}:
        log("Перевод выключен (ASC_TRANSLATE=false)")
        return 0

    sheet_url = get_google_sheet_url()
    if not sheet_url:
        log("Нет ссылки на ASO-таблицу — пропускаем")
        return 0

    xlsx = aso_xlsx_path()
    if not Path(xlsx).is_file():
        log("Таблица ещё не скачана — пропускаем")
        return 0

    # 1. Языки, ради которых всё затевается, берём с листа ASO.
    aso_rows = read_xlsx_sheet(xlsx, ["ASO", "Aso", "АСО"])
    aso_languages: list[str] = []
    for row in aso_rows:
        cells = [(cell or "").strip() for cell in row]
        while len(cells) < 2:
            cells.append("")
        if not cells[0] and cells[1] and locales_for_name(cells[1]):
            if cells[1] not in aso_languages:
                aso_languages.append(cells[1])

    if not aso_languages:
        log("На листе ASO не нашлось языков — пропускаем")
        return 0

    # 2. Что уже есть в описаниях и в каких строках.
    # Настоящее имя вкладки нужно для адресов ячеек при записи.
    with zipfile.ZipFile(xlsx) as archive:
        sheet_name = resolve_sheet_name(
            xlsx_sheet_paths(archive),
            ["Description", "Descriptions", "Descriprion", "Описание", "Описания"],
        )
    if not sheet_name:
        log("В таблице нет листа описаний — пропускаем")
        return 0

    description_rows = read_xlsx_sheet(xlsx, [sheet_name])
    column: list[str] = []
    for row in description_rows:
        cells = [(cell or "").strip() for cell in row]
        while len(cells) < 2:
            cells.append("")
        column.append(cells[1])

    existing: dict[str, dict] = {}
    for index, value in enumerate(column):
        if not value or not locales_for_name(value):
            continue
        nxt = column[index + 1] if index + 1 < len(column) else ""
        filled = bool(nxt) and not nxt.isdigit()
        existing[normalize_name(value)] = {
            "row": index + 2,  # строка с текстом, 1-based
            "filled": filled,
        }

    source_key = normalize_name("English US")
    source_info = existing.get(source_key)
    if not source_info or not source_info["filled"]:
        log("Английское описание не заполнено — переводить не с чего")
        return 0

    source_text = column[source_info["row"] - 1]
    log(f"Источник: English US, {len(source_text)} символов")

    # 3. Считаем, чего не хватает.
    updates: list[tuple[int, str, str]] = []  # (строка, язык, текст)
    appends: list[tuple[str, str]] = []  # (язык, текст) — блока в листе нет
    skipped_known: list[str] = []
    failures: list[str] = []
    too_long: list[str] = []

    for language in aso_languages:
        key = normalize_name(language)
        if key == source_key:
            continue

        info = existing.get(key)
        if info and info["filled"]:
            skipped_known.append(language)
            continue

        # Английские варианты переводить не нужно — кладём исходный текст.
        if key.startswith("english"):
            text = source_text
        else:
            code = TRANSLATOR_CODES.get(key)
            if not code:
                failures.append(f"{language}: нет кода переводчика")
                continue
            try:
                text = translate(source_text, code)
            except Exception as error:  # noqa: BLE001 — причину показываем в отчёте
                failures.append(f"{language}: {error}")
                continue

        if len(text) > DESCRIPTION_LIMIT:
            too_long.append(f"{language} ({len(text)})")

        if info:
            updates.append((info["row"], language, text))
        else:
            appends.append((language, text))

        log(f"{language}: {len(text)} символов")

    if not updates and not appends:
        log(f"Всё уже заполнено ({len(skipped_known)} языков) — писать нечего")
        return 0

    # 4. Пишем в таблицу.
    service = build_sheets_service()
    spreadsheet_id = google_drive_file_id(sheet_url)

    data = []
    for row, _language, text in updates:
        data.append({"range": f"'{sheet_name}'!B{row}", "values": [[text]]})
        data.append({"range": f"'{sheet_name}'!B{row + 1}", "values": [[len(text)]]})

    if data:
        service.spreadsheets().values().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"valueInputOption": "RAW", "data": data},
        ).execute()

    if appends:
        rows: list[list[str | int]] = []
        for language, text in appends:
            rows.extend([[language], [text], [len(text)], [""]])
        service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=f"'{sheet_name}'!B:B",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": rows},
        ).execute()

    normalize_column_format(service, spreadsheet_id, sheet_name)

    log(
        f"Записано: {len(updates) + len(appends)} языков "
        f"(дописано блоков: {len(appends)}), пропущено готовых: {len(skipped_known)}"
    )

    try:
        from automation_report import merge_section

        merge_section(
            "translation",
            {
                "translated": len(updates) + len(appends),
                "skipped_existing": len(skipped_known),
                "failed": failures,
                "over_limit": too_long,
            },
        )
    except Exception:  # noqa: BLE001 — отчёт не должен ронять прогон
        pass

    if too_long:
        log(f"ВНИМАНИЕ: длиннее {DESCRIPTION_LIMIT} символов — {', '.join(too_long)}")
    for failure in failures:
        log(f"ОШИБКА {failure}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
