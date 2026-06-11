#!/usr/bin/env python3
import re
import shutil
import sys
import urllib.parse
import urllib.error
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from paths import AUTOMATION_DIR, CONFIG_PATH, METADATA_DIR, PREPARED_DIR, REPO_ROOT

ROOT_DIR = REPO_ROOT
CONFIG_YAML = CONFIG_PATH
CONFIG_ENV = REPO_ROOT / "config.env"
PREPARED_SCREENSHOTS_DIR = PREPARED_DIR / "screenshots"
PREPARED_SUBSCRIPTION_PATH = PREPARED_DIR / "subscription_localizations.json"
GOOGLE_SHEET_XLSX_PATH = PREPARED_DIR / "google_sheet_aso.xlsx"
GOOGLE_SHEET_XLSX_DOWNLOADED = False
DOWNLOADED_SCREENSHOTS_ZIP = PREPARED_DIR / "downloaded_screenshots.zip"
SCREENSHOTS_ZIP_DOWNLOADED = False

LOCALE_RE = re.compile(r"^[a-z]{2}(?:-[A-Za-z]{2,4})?$")
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}
ASO_LABELS = {
    "название": "title",
    "title": "title",
    "name": "title",
    "подзаголовок": "subtitle",
    "subtitle": "subtitle",
    "ключи": "keywords",
    "keywords": "keywords",
}
DESCRIPTION_LABELS = {
    "описание",
    "description",
    "desc",
}
SUBSCRIPTION_LABELS = {
    "название": "name",
    "title": "name",
    "name": "name",
    "описание": "description",
    "description": "description",
    "desc": "description",
    "подзаголовок": "description",
    "subtitle": "description",
}
SUBSCRIPTION_SHEET_NAMES = ("Subs", "Subscription")
SUBSCRIPTION_ROW_LABELS = {"подписка", "subscription", "product", "productid", "product_id"}
SUBSCRIPTION_BLOCK_WIDTH = 3
LANGUAGE_TO_LOCALES = {
    "arabic": ["ar-SA"],
    "us uk au ca": ["en-US", "en-GB", "en-AU", "en-CA"],
    "catalan": ["ca"],
    "chinese simplified": ["zh-Hans"],
    "chinese traditional": ["zh-Hant"],
    "croatian": ["hr"],
    "czech": ["cs"],
    "danish": ["da"],
    "dutch": ["nl-NL"],
    "english": ["en-US", "en-GB", "en-AU", "en-CA"],
    "english au": ["en-AU"],
    "english ca": ["en-CA"],
    "english uk": ["en-GB"],
    "english us": ["en-US"],
    "finnish": ["fi"],
    "french": ["fr-FR", "fr-CA"],
    "french ca": ["fr-CA"],
    "german": ["de-DE"],
    "greek": ["el"],
    "hebrew": ["he"],
    "hindi": ["hi"],
    "hungarian": ["hu"],
    "indonesian": ["id"],
    "italian": ["it"],
    "japanese": ["ja"],
    "korean": ["ko"],
    "malay": ["ms"],
    "norwegian": ["no"],
    "polish": ["pl"],
    "portuguese br": ["pt-BR"],
    "portuguese pt": ["pt-PT"],
    "romanian": ["ro"],
    "russian": ["ru"],
    "slovak": ["sk"],
    "spanish": ["es-ES", "es-MX"],
    "spanish es": ["es-ES"],
    "spanish mx": ["es-MX"],
    "swedish": ["sv"],
    "thai": ["th"],
    "turkish": ["tr"],
    "ukranian": ["uk"],
    "ukrainian": ["uk"],
    "vietnamese": ["vi"],
}


def _normalize_config(raw: dict) -> dict[str, str]:
    def pick(*keys: str) -> str:
        for key in keys:
            if key not in raw or raw[key] is None:
                continue
            value = raw[key]
            if isinstance(value, str):
                return value.strip()
            return str(value).strip()
        return ""

    return {
        "RUN_MODE": pick("RUN_MODE", "run_mode"),
        "GOOGLE_SHEET_URL": pick("GOOGLE_SHEET_URL", "google_sheet_url"),
        "SCREENSHOTS_ZIP_URL": pick("SCREENSHOTS_ZIP_URL", "screenshots_zip_url"),
        "RELEASE_NOTES": pick("RELEASE_NOTES", "release_notes"),
    }


def read_env_config(path: Path) -> dict[str, str]:
    raw: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise SystemExit(f"{path}:{line_number} must use KEY=VALUE format")

        key, value = line.split("=", 1)
        raw[key.strip()] = value.strip().strip('"').strip("'")
    return _normalize_config(raw)


def read_yaml_config(path: Path) -> dict[str, str]:
    try:
        import yaml
    except ImportError as error:
        raise SystemExit("PyYAML is required to read config.yaml. Run: python -m pip install -r automation/requirements.txt") from error

    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if loaded is None:
        loaded = {}
    if not isinstance(loaded, dict):
        raise SystemExit(f"{path} must contain key-value settings at the top level")
    return _normalize_config(loaded)


def read_user_config():
    if CONFIG_YAML.exists():
        return read_yaml_config(CONFIG_YAML)
    if CONFIG_ENV.exists():
        return read_env_config(CONFIG_ENV)

    raise SystemExit(f"Missing config file: {CONFIG_YAML} (recommended) or {CONFIG_ENV}")


def get_release_notes_fallback() -> str:
    import os

    env_value = os.environ.get("RELEASE_NOTES", "").strip()
    if env_value:
        return env_value
    return USER_CONFIG.get("RELEASE_NOTES", "").strip()


def release_notes_fallback_source() -> str:
    import os

    if os.environ.get("RELEASE_NOTES", "").strip():
        return "workflow_or_env"
    if USER_CONFIG.get("RELEASE_NOTES", "").strip():
        return "config"
    return "none"


def _env_or_config(env_key: str, config_key: str) -> str:
    import os

    env_value = os.environ.get(env_key, "").strip()
    if env_value:
        return env_value
    return USER_CONFIG.get(config_key, "").strip()


def get_google_sheet_url() -> str:
    return _env_or_config("GOOGLE_SHEET_URL", "GOOGLE_SHEET_URL")


def get_screenshots_zip_url() -> str:
    return _env_or_config("SCREENSHOTS_ZIP_URL", "SCREENSHOTS_ZIP_URL")


def google_sheet_url_source() -> str:
    import os

    if os.environ.get("GOOGLE_SHEET_URL", "").strip():
        return "workflow_or_env"
    if USER_CONFIG.get("GOOGLE_SHEET_URL", "").strip():
        return "config"
    return "none"


def screenshots_zip_url_source() -> str:
    import os

    if os.environ.get("SCREENSHOTS_ZIP_URL", "").strip():
        return "workflow_or_env"
    if USER_CONFIG.get("SCREENSHOTS_ZIP_URL", "").strip():
        return "config"
    return "none"


USER_CONFIG = read_user_config()
SOURCE_LINKS = USER_CONFIG
RUN_MODES = ("screenshots", "aso", "whats_new", "all")


def has_aso_source():
    return bool(get_google_sheet_url())


def has_screenshots_source():
    return bool(get_screenshots_zip_url())


def is_whats_new_only_mode():
    return read_run_mode() == "whats_new"


def read_run_mode():
    import os

    mode = os.environ.get("RUN_MODE", "").strip().lower()
    if not mode:
        mode = SOURCE_LINKS.get("RUN_MODE", "").strip().lower()
    if not mode:
        if not has_aso_source() and not has_screenshots_source():
            return "whats_new"
        return "all"
    if mode not in RUN_MODES:
        raise SystemExit(f"Invalid RUN_MODE '{mode}'. Use one of: {', '.join(RUN_MODES)}")
    return mode


def resolve_run_plan():
    mode = read_run_mode()
    has_aso = has_aso_source()
    has_shots = has_screenshots_source()

    plan = {
        "mode": mode,
        "prepare_aso": False,
        "prepare_screenshots": False,
        "run_metadata": False,
        "run_app_info": False,
        "run_subscriptions": False,
        "run_screenshots": False,
        "run_whats_new": False,
    }

    if mode == "whats_new":
        plan["run_whats_new"] = True
        return plan

    if mode == "screenshots":
        if not has_shots:
            raise SystemExit("RUN_MODE=screenshots requires screenshots_zip_url in config.yaml")
        plan["prepare_screenshots"] = True
        plan["run_screenshots"] = True
        plan["run_whats_new"] = True
        return plan

    if mode == "aso":
        if not has_aso:
            raise SystemExit("RUN_MODE=aso requires google_sheet_url in config.yaml")
        plan["prepare_aso"] = True
        plan["run_metadata"] = True
        plan["run_app_info"] = True
        plan["run_subscriptions"] = True
        plan["run_whats_new"] = True
        return plan

    if mode == "all":
        if not has_aso and not has_shots:
            raise SystemExit(
                "RUN_MODE=all requires google_sheet_url and/or screenshots_zip_url in config.yaml"
            )
        plan["prepare_aso"] = has_aso
        plan["prepare_screenshots"] = has_shots
        plan["run_metadata"] = has_aso
        plan["run_app_info"] = has_aso
        plan["run_subscriptions"] = has_aso
        plan["run_screenshots"] = has_shots
        plan["run_whats_new"] = True
        return plan

    raise SystemExit(f"Unsupported RUN_MODE '{mode}'")


def google_sheet_export_url(url):
    match = re.search(r"/spreadsheets/d/([^/]+)", url)
    if not match:
        raise SystemExit(f"Invalid Google Sheets URL: {url}")
    spreadsheet_id = match.group(1)
    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=xlsx"


def google_drive_file_id(url):
    match = re.search(r"/(?:file|spreadsheets)/d/([^/]+)", url)
    if match:
        return match.group(1)

    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)
    file_ids = query.get("id")
    if file_ids:
        return file_ids[0]

    raise SystemExit(f"Invalid Google Drive or Sheets file URL: {url}")


def download_url(url, timeout=60):
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def download_google_drive_file(url, target_path, label="Google Drive file"):
    try:
        from google_drive_auth import download_via_service_account, service_account_configured
    except ImportError:
        service_account_configured = lambda: False  # type: ignore[assignment]
        download_via_service_account = None  # type: ignore[assignment]

    if service_account_configured():
        print(f"Downloading {label} via Google Service Account (Drive API)...")
        return download_via_service_account(url, Path(target_path), label)

    print(f"Downloading {label} via public Google Drive link...")
    file_id = google_drive_file_id(url)
    first_url = f"https://drive.google.com/uc?export=download&id={file_id}"

    try:
        data = download_url(first_url, timeout=60)
    except urllib.error.URLError as error:
        raise SystemExit(f"Failed to download {label}: {error}") from error

    if data.startswith(b"PK"):
        target_path.write_bytes(data)
        return target_path

    html = data.decode("utf-8", errors="ignore")
    uuid_match = re.search(r'name="uuid" value="([^"]+)"', html)
    confirm_match = re.search(r'name="confirm" value="([^"]+)"', html)
    if not uuid_match or not confirm_match:
        raise SystemExit(
            f"Google Drive did not return a downloadable {label}. "
            "Set GOOGLE_SERVICE_ACCOUNT_JSON and share the file with the service account, "
            "or share the file with anyone who has the link."
        )

    confirm_url = (
        "https://drive.usercontent.google.com/download"
        f"?id={urllib.parse.quote(file_id)}"
        "&export=download"
        f"&confirm={urllib.parse.quote(confirm_match.group(1))}"
        f"&uuid={urllib.parse.quote(uuid_match.group(1))}"
    )
    try:
        data = download_url(confirm_url, timeout=300)
    except urllib.error.URLError as error:
        raise SystemExit(f"Failed to confirm {label} download: {error}") from error

    if not data.startswith(b"PK"):
        raise SystemExit(f"Google Drive confirmation did not return a downloadable {label}.")

    target_path.write_bytes(data)
    return target_path


def download_google_sheet_xlsx():
    if not has_aso_source():
        raise SystemExit("google_sheet_url is empty in config.yaml")

    global GOOGLE_SHEET_XLSX_DOWNLOADED
    if GOOGLE_SHEET_XLSX_DOWNLOADED and GOOGLE_SHEET_XLSX_PATH.exists():
        return GOOGLE_SHEET_XLSX_PATH

    GOOGLE_SHEET_XLSX_PATH.parent.mkdir(parents=True, exist_ok=True)
    sheet_url = get_google_sheet_url()
    print(
        f"Downloading ASO workbook ({google_sheet_url_source()}) into {GOOGLE_SHEET_XLSX_PATH}..."
    )
    download_google_drive_file(sheet_url, GOOGLE_SHEET_XLSX_PATH, "ASO workbook")
    GOOGLE_SHEET_XLSX_DOWNLOADED = True
    return GOOGLE_SHEET_XLSX_PATH


def aso_xlsx_path():
    return download_google_sheet_xlsx()


def screenshots_zip_path():
    if not has_screenshots_source():
        raise SystemExit("screenshots_zip_url is empty in config.yaml")

    global SCREENSHOTS_ZIP_DOWNLOADED
    if SCREENSHOTS_ZIP_DOWNLOADED and DOWNLOADED_SCREENSHOTS_ZIP.exists():
        return DOWNLOADED_SCREENSHOTS_ZIP

    DOWNLOADED_SCREENSHOTS_ZIP.parent.mkdir(parents=True, exist_ok=True)
    zip_url = get_screenshots_zip_url()
    print(
        f"Downloading screenshots ZIP ({screenshots_zip_url_source()}) into {DOWNLOADED_SCREENSHOTS_ZIP}..."
    )
    download_google_drive_file(zip_url, DOWNLOADED_SCREENSHOTS_ZIP, "screenshots ZIP")
    SCREENSHOTS_ZIP_DOWNLOADED = True
    return DOWNLOADED_SCREENSHOTS_ZIP


def normalize_name(value):
    return re.sub(r"\s+", " ", value.strip().lower())


def locales_for_name(name):
    normalized = normalize_name(name)
    if LOCALE_RE.match(name.strip()):
        return [name.strip()]
    return LANGUAGE_TO_LOCALES.get(normalized, [])


def column_index(cell_reference):
    letters = "".join(character for character in cell_reference if character.isalpha())
    index = 0
    for character in letters:
        index = index * 26 + (ord(character.upper()) - ord("A") + 1)
    return index - 1


def read_xlsx_shared_strings(zip_file):
    try:
        xml = zip_file.read("xl/sharedStrings.xml")
    except KeyError:
        return []

    root = ET.fromstring(xml)
    namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    strings = []
    for item in root.findall("x:si", namespace):
        text_parts = [node.text or "" for node in item.findall(".//x:t", namespace)]
        strings.append("".join(text_parts))
    return strings


def xlsx_sheet_paths(zip_file):
    workbook_root = ET.fromstring(zip_file.read("xl/workbook.xml"))
    rels_root = ET.fromstring(zip_file.read("xl/_rels/workbook.xml.rels"))
    workbook_ns = {
        "x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    }
    rels_ns = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}

    relationships = {}
    for rel in rels_root.findall("r:Relationship", rels_ns):
        target = rel.attrib["Target"]
        if not target.startswith("/"):
            target = "xl/" + target
        relationships[rel.attrib["Id"]] = target.lstrip("/")

    paths = {}
    for sheet in workbook_root.findall("x:sheets/x:sheet", workbook_ns):
        sheet_name = sheet.attrib["name"]
        relationship_id = sheet.attrib[f"{{{workbook_ns['r']}}}id"]
        paths[sheet_name] = relationships[relationship_id]
    return paths


def resolve_sheet_name(sheet_paths, preferred_names):
    """Match workbook tab names case-insensitively (ASO == Aso == aso)."""
    by_lower = {name.lower(): name for name in sheet_paths}
    for preferred in preferred_names:
        actual = by_lower.get(preferred.lower())
        if actual:
            return actual
    return None


def read_xlsx_sheet(path, preferred_names):
    with zipfile.ZipFile(path) as zip_file:
        shared_strings = read_xlsx_shared_strings(zip_file)
        sheet_paths = xlsx_sheet_paths(zip_file)
        sheet_name = resolve_sheet_name(sheet_paths, preferred_names)
        if sheet_name is None:
            return []

        root = ET.fromstring(zip_file.read(sheet_paths[sheet_name]))
        namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        rows = []
        for row in root.findall(".//x:sheetData/x:row", namespace):
            values = []
            for cell in row.findall("x:c", namespace):
                reference = cell.attrib.get("r", "")
                index = column_index(reference)
                while len(values) <= index:
                    values.append("")

                value_node = cell.find("x:v", namespace)
                inline_node = cell.find("x:is/x:t", namespace)
                value = ""
                if cell.attrib.get("t") == "s" and value_node is not None:
                    value = shared_strings[int(value_node.text)]
                elif inline_node is not None:
                    value = inline_node.text or ""
                elif value_node is not None:
                    value = value_node.text or ""
                values[index] = value.strip()
            rows.append(values)
        return rows


def aso_row_is_empty(row: dict) -> bool:
    return not any((row.get(field) or "").strip() for field in ("title", "subtitle", "keywords"))


def read_manager_aso_rows(rows, source_name):
    rows_by_locale = {}
    current_language = None
    current_values = {}

    def flush_current():
        nonlocal current_language, current_values
        if not current_language:
            return

        locales = locales_for_name(current_language)
        if not locales:
            raise SystemExit(f"Unsupported ASO language name in {source_name}: {current_language}")
        for locale in locales:
            rows_by_locale[locale] = {
                "locale": locale,
                "title": (current_values.get("title") or "").strip(),
                "subtitle": (current_values.get("subtitle") or "").strip(),
                "keywords": (current_values.get("keywords") or "").strip(),
            }
        current_language = None
        current_values = {}

    for row in rows:
        cells = [(cell or "").strip() for cell in row]
        while len(cells) < 3:
            cells.append("")

        first, second = cells[0], cells[1]
        label = ASO_LABELS.get(normalize_name(first))
        if not first and second:
            flush_current()
            current_language = second
            current_values = {}
        elif label and current_language:
            current_values[label] = second

    flush_current()
    return rows_by_locale


def read_manager_description_rows(rows, source_name):
    rows_by_locale = {}
    current_language = None
    current_description = ""

    def flush_current():
        nonlocal current_language, current_description
        if not current_language or not current_description:
            current_language = None
            current_description = ""
            return

        locales = locales_for_name(current_language)
        if not locales:
            raise SystemExit(f"Unsupported Description language name in {source_name}: {current_language}")
        for locale in locales:
            rows_by_locale[locale] = {
                "locale": locale,
                "description": current_description,
            }
        current_language = None
        current_description = ""

    for row in rows:
        cells = [(cell or "").strip() for cell in row]
        while len(cells) < 2:
            cells.append("")

        first, second = cells[0], cells[1]
        second_is_language = bool(second and locales_for_name(second))
        if not first and second_is_language:
            flush_current()
            current_language = second
        elif not first and second and current_language and not current_description:
            current_description = second
        elif normalize_name(first) in DESCRIPTION_LABELS and current_language:
            current_description = second

    flush_current()
    return rows_by_locale


def read_aso_rows():
    if not has_aso_source():
        return {}

    xlsx_path = aso_xlsx_path()
    rows = read_xlsx_sheet(xlsx_path, ["ASO", "New"])
    if not rows:
        raise SystemExit("Google Sheet must contain an ASO or New sheet")
    return read_manager_aso_rows(rows, str(xlsx_path))


def read_description_rows():
    if not has_aso_source():
        return {}

    xlsx_path = aso_xlsx_path()
    rows = read_xlsx_sheet(xlsx_path, ["Description", "Descriptions"])
    if not rows:
        return {}
    return read_manager_description_rows(rows, str(xlsx_path))


def detect_subscription_block_stride(rows):
    for row in rows[:30]:
        cells = [(cell or "").strip() for cell in row]
        name_label_indices = []
        for index, cell in enumerate(cells):
            if SUBSCRIPTION_LABELS.get(normalize_name(cell)) == "name":
                name_label_indices.append(index)
        if len(name_label_indices) >= 2:
            return name_label_indices[1] - name_label_indices[0]
    return SUBSCRIPTION_BLOCK_WIDTH


def subscription_block_label_index(block_index, stride):
    return stride * block_index


def subscription_block_value_index(block_index, stride):
    return stride * block_index + 1


def subscription_block_count(column_count, stride):
    if column_count <= 0:
        return 0
    return (column_count + stride - 1) // stride


def looks_like_subscription_product_id(value):
    value = (value or "").strip()
    if not value or " " in value:
        return False
    if "." in value:
        return True
    return bool(re.match(r"^[a-zA-Z0-9._-]{6,}$", value))


def subscription_sheet_is_multi(rows):
    stride = detect_subscription_block_stride(rows)
    for row in rows[:10]:
        cells = [(cell or "").strip() for cell in row]
        if cells and normalize_name(cells[0]) in SUBSCRIPTION_ROW_LABELS:
            return True
        name_labels = 0
        for block_index in range(subscription_block_count(len(cells), stride)):
            label_index = subscription_block_label_index(block_index, stride)
            if label_index < len(cells) and normalize_name(cells[label_index]) in SUBSCRIPTION_LABELS:
                name_labels += 1
        if name_labels >= 2:
            return True
    return False


def subscription_rows_by_product(rows):
    if not rows:
        return False
    sample = next(iter(rows))
    return looks_like_subscription_product_id(sample)


def parse_subscription_product_ids(rows, stride=None):
    stride = stride or detect_subscription_block_stride(rows)
    for row in rows[:8]:
        cells = [(cell or "").strip() for cell in row]
        if not cells or normalize_name(cells[0]) not in SUBSCRIPTION_ROW_LABELS:
            continue
        product_ids = []
        for block_index in range(subscription_block_count(len(cells), stride)):
            value_index = subscription_block_value_index(block_index, stride)
            if value_index >= len(cells):
                continue
            value = cells[value_index].strip()
            if value and looks_like_subscription_product_id(value):
                product_ids.append(value)
        return product_ids
    return []


def read_manager_subscription_rows(rows, source_name):
    rows_by_locale = {}
    current_language = None
    current_values = {}

    def flush_current():
        nonlocal current_language, current_values
        if not current_language:
            return
        if not current_values.get("name", "").strip():
            current_language = None
            current_values = {}
            return

        locales = locales_for_name(current_language)
        if not locales:
            raise SystemExit(f"Unsupported Subscription language name in {source_name}: {current_language}")
        for locale in locales:
            rows_by_locale[locale] = {
                "locale": locale,
                "name": current_values.get("name", "").strip(),
                "description": current_values.get("description", "").strip(),
            }
        current_language = None
        current_values = {}

    for row in rows:
        cells = [(cell or "").strip() for cell in row]
        while len(cells) < 3:
            cells.append("")

        first, second = cells[0], cells[1]
        label = SUBSCRIPTION_LABELS.get(normalize_name(first))
        language = subscription_language_from_row(cells, 1, SUBSCRIPTION_BLOCK_WIDTH)
        if language:
            flush_current()
            current_language = language
            current_values = {}
        elif label and current_language:
            current_values[label] = second

    flush_current()
    return rows_by_locale


def subscription_language_from_row(cells, block_count, stride):
    if not cells:
        return None
    first = cells[0]
    if first and locales_for_name(first):
        return first
    second = cells[1] if len(cells) > 1 else ""
    if not first and second and locales_for_name(second):
        return second
    for block_index in range(block_count):
        value_index = subscription_block_value_index(block_index, stride)
        if value_index < len(cells) and cells[value_index]:
            candidate = cells[value_index]
            if locales_for_name(candidate):
                return candidate
    return None


def read_manager_subscription_rows_multi(rows, source_name):
    stride = detect_subscription_block_stride(rows)
    product_ids = parse_subscription_product_ids(rows, stride)
    max_columns = max((len(row) for row in rows), default=0)
    block_count = subscription_block_count(max_columns, stride)
    if block_count == 0:
        return {}

    rows_by_product = {product_id: {} for product_id in product_ids}
    current_language = None
    values_by_block = [{} for _ in range(block_count)]

    def flush_current():
        nonlocal current_language, values_by_block
        if not current_language:
            return

        locales = locales_for_name(current_language)
        if not locales:
            raise SystemExit(f"Unsupported Subscription language name in {source_name}: {current_language}")

        for block_index in range(block_count):
            block_values = values_by_block[block_index]
            name = block_values.get("name", "").strip()
            if not name:
                continue
            product_id = product_ids[block_index] if block_index < len(product_ids) else ""
            if not product_id:
                continue
            description = block_values.get("description", "").strip()
            for locale in locales:
                rows_by_product.setdefault(product_id, {})[locale] = {
                    "locale": locale,
                    "name": name,
                    "description": description,
                }

        current_language = None
        values_by_block = [{} for _ in range(block_count)]

    for row in rows:
        cells = [(cell or "").strip() for cell in row]
        if not cells:
            continue
        if normalize_name(cells[0]) in SUBSCRIPTION_ROW_LABELS:
            continue
        if not cells[0] and not cells[1] and any("in-app" in cell.lower() for cell in cells if cell):
            continue

        language = subscription_language_from_row(cells, block_count, stride)
        if language:
            flush_current()
            current_language = language
            values_by_block = [{} for _ in range(block_count)]
            continue

        if not current_language:
            continue

        for block_index in range(block_count):
            label_index = subscription_block_label_index(block_index, stride)
            value_index = subscription_block_value_index(block_index, stride)
            if label_index >= len(cells):
                continue
            label = SUBSCRIPTION_LABELS.get(normalize_name(cells[label_index]))
            if not label:
                continue
            value = cells[value_index].strip() if value_index < len(cells) else ""
            values_by_block[block_index][label] = value

    flush_current()
    result = {product_id: locales for product_id, locales in rows_by_product.items() if locales}
    if block_count > len(product_ids):
        missing = block_count - len(product_ids)
        print(
            f"WARNING: Subs sheet has {block_count} subscription column(s) but only "
            f"{len(product_ids)} product id(s) on the Подписка row. "
            f"Add {missing} more product id(s) in columns "
            + ", ".join(
                chr(ord("A") + subscription_block_value_index(index, stride))
                for index in range(len(product_ids), block_count)
            )
            + " to upload all subscriptions."
        )
    return result


def read_subscription_rows():
    if not has_aso_source():
        return {}

    xlsx_path = aso_xlsx_path()
    rows = read_xlsx_sheet(xlsx_path, list(SUBSCRIPTION_SHEET_NAMES))
    if not rows:
        return {}
    source_name = str(xlsx_path)
    if subscription_sheet_is_multi(rows):
        return read_manager_subscription_rows_multi(rows, source_name)
    return read_manager_subscription_rows(rows, source_name)


def subscription_locale_count(rows):
    if subscription_rows_by_product(rows):
        return sum(len(locales) for locales in rows.values())
    return len(rows)


def write_prepared_subscription_rows(rows):
    if not rows:
        if PREPARED_SUBSCRIPTION_PATH.exists():
            PREPARED_SUBSCRIPTION_PATH.unlink()
        return 0

    import json

    PREPARED_DIR.mkdir(parents=True, exist_ok=True)
    if subscription_rows_by_product(rows):
        payload = {
            product_id: {
                locale: {
                    "locale": locale,
                    "name": row.get("name", "").strip(),
                    "description": row.get("description", "").strip(),
                }
                for locale, row in sorted(locales.items())
            }
            for product_id, locales in sorted(rows.items())
        }
        locale_count = subscription_locale_count(rows)
    else:
        payload = {
            locale: {
                "locale": locale,
                "name": row.get("name", "").strip(),
                "description": row.get("description", "").strip(),
            }
            for locale, row in sorted(rows.items())
        }
        locale_count = len(payload)

    PREPARED_SUBSCRIPTION_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return locale_count


def write_text(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value.rstrip() + "\n", encoding="utf-8")


def list_prepared_screenshot_locales():
    if not PREPARED_SCREENSHOTS_DIR.exists():
        return []
    return sorted(
        path.name
        for path in PREPARED_SCREENSHOTS_DIR.iterdir()
        if path.is_dir() and LOCALE_RE.match(path.name)
    )


def prepare_metadata_files(aso_rows, description_rows, extra_locales=None):
    from release_notes import (
        apply_version_urls_to_metadata_dir,
        fetch_live_version_localization_attributes,
        resolve_app_info_for_locales,
        resolve_descriptions_for_locales,
        resolve_keywords_for_locales,
        resolve_release_notes_for_locales,
    )

    locales = sorted(set(aso_rows) | set(description_rows) | set(extra_locales or []))
    live_attributes = None
    try:
        live_attributes = fetch_live_version_localization_attributes(REPO_ROOT)
    except Exception as error:
        print(f"WARNING: Could not fetch live version localizations from App Store Connect: {error}", file=sys.stderr)

    release_notes_by_locale, _release_stats = resolve_release_notes_for_locales(
        locales,
        REPO_ROOT,
        get_release_notes_fallback(),
        live_attributes=live_attributes,
    )
    descriptions_by_locale, _description_stats = resolve_descriptions_for_locales(
        locales,
        description_rows,
        REPO_ROOT,
        live_attributes=live_attributes,
    )
    keywords_by_locale, _keywords_stats = resolve_keywords_for_locales(
        locales,
        aso_rows,
        REPO_ROOT,
        live_attributes=live_attributes,
    )
    app_info_by_locale, _app_info_stats = resolve_app_info_for_locales(
        locales,
        aso_rows,
        REPO_ROOT,
    )

    for locale in locales:
        locale_dir = METADATA_DIR / locale
        if locale in app_info_by_locale:
            app_info = app_info_by_locale[locale]
            if app_info.get("name"):
                write_text(locale_dir / "name.txt", app_info["name"])
            if app_info.get("subtitle"):
                write_text(locale_dir / "subtitle.txt", app_info["subtitle"])
        if locale in keywords_by_locale:
            write_text(locale_dir / "keywords.txt", keywords_by_locale[locale])
        if locale in descriptions_by_locale:
            write_text(locale_dir / "description.txt", descriptions_by_locale[locale])
        if locale in release_notes_by_locale:
            write_text(locale_dir / "release_notes.txt", release_notes_by_locale[locale])

    url_files, _url_stats = apply_version_urls_to_metadata_dir(
        METADATA_DIR,
        REPO_ROOT,
        locales,
        live_attributes=live_attributes,
    )
    if url_files:
        print(f"Prepared Support/Marketing URL file(s) for {url_files} field(s).")

    return locales, url_files


def safe_zip_members(zip_file):
    for member in zip_file.infolist():
        path = Path(member.filename)
        parts = [part for part in path.parts if part not in ("", ".")]
        if not parts or parts[0] == "__MACOSX":
            continue
        if any(part == ".." for part in parts):
            continue
        if member.is_dir():
            continue

        locale_index = next((index for index, part in enumerate(parts) if locales_for_name(part)), None)
        if locale_index is None:
            continue

        locale_name = parts[locale_index]
        locales = locales_for_name(locale_name)
        if not locales:
            continue
        if Path(parts[-1]).suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        for locale in locales:
            yield member, locale, Path(*parts[locale_index + 1:])


def clean_prepared_screenshots():
    if PREPARED_SCREENSHOTS_DIR.exists():
        shutil.rmtree(PREPARED_SCREENSHOTS_DIR)
    PREPARED_SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)


def prepare_screenshots_from_zip():
    if not has_screenshots_source():
        return [], 0, 0

    zip_path = screenshots_zip_path()
    if not zip_path.exists():
        print(
            f"WARNING: screenshots_zip_url is set but prepared zip was not found at {zip_path}. "
            "Check the Google Drive URL or download step output.",
            file=sys.stderr,
        )
        return [], 0, 0

    clean_prepared_screenshots()
    locales = set()
    copied = 0
    per_locale_counts = {}
    with zipfile.ZipFile(zip_path) as zip_file:
        for member, locale, relative_path in safe_zip_members(zip_file):
            per_locale_counts[locale] = per_locale_counts.get(locale, 0) + 1
            target_name = f"{per_locale_counts[locale]:02d}{Path(member.filename).suffix.lower()}"
            target = PREPARED_SCREENSHOTS_DIR / locale / target_name
            target.parent.mkdir(parents=True, exist_ok=True)
            with zip_file.open(member) as source, target.open("wb") as destination:
                shutil.copyfileobj(source, destination)
            locales.add(locale)
            copied += 1

    print(f"Prepared {copied} screenshot file(s) for {len(locales)} locale(s) from {zip_path}.")
    return sorted(locales), copied, len(locales)


def prepare_screenshots():
    return prepare_screenshots_from_zip()


def record_prepare_report(
    *,
    aso_skipped: bool = False,
    aso_locales: int = 0,
    description_locales: int = 0,
    subscription_locales: int = 0,
    screenshots_skipped: bool = False,
    screenshot_locales: int = 0,
    screenshot_files: int = 0,
    version_url_files: int = 0,
) -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
    from automation_report import merge_section

    merge_section(
        "prepare",
        {
            "aso_skipped": aso_skipped,
            "aso_locales": aso_locales,
            "description_locales": description_locales,
            "aso_url_source": google_sheet_url_source(),
            "screenshots_skipped": screenshots_skipped,
            "screenshot_locales": screenshot_locales,
            "screenshot_files": screenshot_files,
            "screenshots_url_source": screenshots_zip_url_source(),
            "subscription_locales": subscription_locales,
            "version_url_files": version_url_files,
        },
    )


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
    from log import log_info, log_step, log_step_done, log_warn

    log_step("Prepare metadata and screenshots")
    if is_whats_new_only_mode():
        log_info("Source mode: What's New only. Skipping ASO and screenshot preparation.")
        log_step_done("Prepare metadata and screenshots", 0)
        return

    aso_skipped = not has_aso_source()
    screenshots_skipped = not has_screenshots_source()
    aso_locale_count = 0
    description_locale_count = 0
    screenshot_locale_count = 0
    screenshot_file_count = 0
    subscription_locale_count = 0
    version_url_files = 0

    screenshot_locales = []
    if has_screenshots_source():
        screenshot_locales, screenshot_file_count, screenshot_locale_count = prepare_screenshots()
        if screenshot_locales:
            print("Prepared screenshot locales: " + ", ".join(screenshot_locales))
    else:
        print("Skipping screenshot preparation: SCREENSHOTS_ZIP_URL is empty.")

    if has_aso_source():
        aso_rows = read_aso_rows()
        description_rows = read_description_rows()
        subscription_rows = read_subscription_rows()
        if not aso_rows:
            raise SystemExit("ASO input must contain at least one locale row")
        metadata_locales, version_url_files = prepare_metadata_files(
            aso_rows,
            description_rows,
            extra_locales=screenshot_locales,
        )
        aso_locale_count = len(aso_rows)
        description_locale_count = len(description_rows)
        subscription_locale_count = write_prepared_subscription_rows(subscription_rows)
        if subscription_locale_count:
            if subscription_rows_by_product(subscription_rows):
                parts = [
                    f"{product_id} ({len(locales)} locales)"
                    for product_id, locales in sorted(subscription_rows.items())
                ]
                print("Prepared subscription localizations: " + ", ".join(parts))
            else:
                print(
                    "Prepared subscription localizations: "
                    + ", ".join(sorted(subscription_rows))
                )
        else:
            print("No Subs/Subscription sheet found in ASO workbook. Skipping subscription upload.")
        print("Prepared metadata locales: " + ", ".join(metadata_locales))
    else:
        print("Skipping ASO/metadata preparation: GOOGLE_SHEET_URL is empty.")

    record_prepare_report(
        aso_skipped=aso_skipped,
        aso_locales=aso_locale_count,
        description_locales=description_locale_count,
        subscription_locales=subscription_locale_count,
        screenshots_skipped=screenshots_skipped,
        screenshot_locales=screenshot_locale_count,
        screenshot_files=screenshot_file_count,
        version_url_files=version_url_files,
    )
    log_info(
        "Prepare finished: "
        f"ASO locales={aso_locale_count}, descriptions={description_locale_count}, "
        f"screenshot locales={screenshot_locale_count}, screenshot files={screenshot_file_count}, "
        f"subscription locales={subscription_locale_count}, "
        f"Support/Marketing URL files={version_url_files}."
    )
    log_step_done("Prepare metadata and screenshots", 0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit as error:
        if error.code not in (0, None):
            message = error.args[0] if error.args else error.code
            if isinstance(message, str) and message and not message.startswith("ERROR:"):
                print(f"ERROR: {message}", file=sys.stderr)
        raise
    except zipfile.BadZipFile:
        print(f"ERROR: Invalid zip archive: {DOWNLOADED_SCREENSHOTS_ZIP}", file=sys.stderr)
        sys.exit(1)
