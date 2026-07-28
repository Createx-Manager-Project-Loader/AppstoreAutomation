#!/usr/bin/env python3
import json
import os
import re
from pathlib import Path

DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
# Запись переводов обратно в ASO-таблицу. Документ должен быть расшарен
# сервисному аккаунту с правом редактирования.
SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
SPREADSHEET_MIME = "application/vnd.google-apps.spreadsheet"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _credentials_json_text() -> str:
    inline = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if inline:
        return inline

    path_value = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if not path_value:
        return ""

    key_path = Path(path_value).expanduser()
    if not key_path.is_file():
        raise SystemExit(f"GOOGLE_APPLICATION_CREDENTIALS file not found: {key_path}")
    return key_path.read_text(encoding="utf-8")


def service_account_configured() -> bool:
    return bool(_credentials_json_text())


def _service_account_email(credentials_info: dict) -> str:
    return str(credentials_info.get("client_email", "")).strip()


def build_drive_service():
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError as error:
        raise SystemExit(
            "Google Service Account download requires google-auth and google-api-python-client. "
            "Run: python -m pip install -r automation/requirements.txt"
        ) from error

    raw = _credentials_json_text()
    try:
        credentials_info = json.loads(raw)
    except json.JSONDecodeError as error:
        raise SystemExit("GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON") from error

    account_type = str(credentials_info.get("type", "")).strip()
    if account_type == "service_account":
        # Обычный ключ .json — как было раньше.
        credentials = service_account.Credentials.from_service_account_info(
            credentials_info,
            scopes=[DRIVE_READONLY_SCOPE],
        )
    else:
        # Workload Identity Federation (type=external_account): ключа-файла нет,
        # доступ выдаёт google-github-actions/auth через ADC, а
        # GOOGLE_APPLICATION_CREDENTIALS указывает на короткоживущие креды.
        import google.auth

        credentials, _ = google.auth.default(scopes=[DRIVE_READONLY_SCOPE])
    return build("drive", "v3", credentials=credentials, cache_discovery=False), credentials_info


def google_drive_file_id(url: str) -> str:
    match = re.search(r"/(?:file|spreadsheets)/d/([^/]+)", url)
    if match:
        return match.group(1)

    from urllib.parse import parse_qs, urlparse

    parsed = urlparse(url)
    file_ids = parse_qs(parsed.query).get("id")
    if file_ids:
        return file_ids[0]

    raise SystemExit(f"Invalid Google Drive or Sheets file URL: {url}")


def _execute_download(drive, file_id: str, mime_type: str) -> bytes:
    if mime_type == SPREADSHEET_MIME:
        request = drive.files().export_media(fileId=file_id, mimeType=XLSX_MIME)
    else:
        request = drive.files().get_media(fileId=file_id)
    return request.execute()


def download_via_service_account(url: str, target_path: Path, label: str = "Google Drive file") -> Path:
    try:
        from googleapiclient.errors import HttpError
    except ImportError:
        HttpError = Exception  # type: ignore[misc, assignment]

    drive, credentials_info = build_drive_service()
    file_id = google_drive_file_id(url)
    service_email = _service_account_email(credentials_info)

    try:
        metadata = (
            drive.files()
            .get(fileId=file_id, fields="name,mimeType", supportsAllDrives=True)
            .execute()
        )
        data = _execute_download(drive, file_id, metadata.get("mimeType", ""))
    except HttpError as error:
        status = getattr(getattr(error, "resp", None), "status", None)
        if status in {403, 404}:
            raise SystemExit(
                f"Failed to download {label} with Service Account (HTTP {status}). "
                f"Share the file with {service_email or 'the service account'} as Viewer."
            ) from error
        raise SystemExit(f"Failed to download {label} with Service Account: {error}") from error
    except Exception as error:
        raise SystemExit(f"Failed to download {label} with Service Account: {error}") from error

    if not data:
        raise SystemExit(f"Service Account download returned empty data for {label}.")

    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(data)
    return target_path


def build_sheets_service():
    """Клиент Google Sheets с правом записи — для дозаполнения переводов."""
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError as error:
        raise SystemExit(
            "Sheets access requires google-auth and google-api-python-client. "
            "Run: python -m pip install -r automation/requirements.txt"
        ) from error

    raw = _credentials_json_text()
    scopes = [DRIVE_READONLY_SCOPE, SHEETS_SCOPE]

    if raw:
        try:
            credentials_info = json.loads(raw)
        except json.JSONDecodeError as error:
            raise SystemExit("GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON") from error

        if str(credentials_info.get("type", "")).strip() == "service_account":
            credentials = service_account.Credentials.from_service_account_info(
                credentials_info, scopes=scopes
            )
            return build("sheets", "v4", credentials=credentials, cache_discovery=False)

    # Workload Identity Federation: короткоживущие креды выдаёт сам GitHub.
    import google.auth

    credentials, _ = google.auth.default(scopes=scopes)
    return build("sheets", "v4", credentials=credentials, cache_discovery=False)
