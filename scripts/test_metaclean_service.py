"""Обмен с сервисом очистки: имя загрузки, «file deleted», удаление после скачивания.

Сервис не вызываем — requests подменён. Запуск: python3 scripts/test_metaclean_service.py
"""
import os
import re
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import metaclean  # noqa: E402

metaclean.POLL_SECONDS = 0
os.environ["METACLEAN_TOKEN"] = "t"


class Resp:
    def __init__(self, status, payload=None, body=b""):
        self.status_code, self._payload, self._body = status, payload or {}, body
        self.text = str(payload)

    def json(self):
        return self._payload

    def iter_content(self, chunk_size):
        yield self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake(statuses, result=b""):
    """Сервис, который отдаёт статусы по очереди и файл result."""
    calls = {"names": [], "deleted": []}

    def post(url, headers, files, timeout):
        calls["names"].append(files["file"][0])
        return Resp(201, {"id": 7})

    def get(url, headers, timeout, stream=False):
        if url.endswith("/media/7"):
            return Resp(200, body=result)
        status = statuses.pop(0) if len(statuses) > 1 else statuses[0]
        return Resp(200, {"status": status, "result_url": "https://svc/media/7" if status == "success" else None})

    def delete(url, headers, timeout):
        calls["deleted"].append(url)
        return Resp(200, {"status": "file deleted"})

    metaclean.requests.post, metaclean.requests.get, metaclean.requests.delete = post, get, delete
    return calls


def zip_with(path, names):
    with zipfile.ZipFile(path, "w") as z:
        for n in names:
            z.writestr(n, b"x")
    return path


fails = 0


def check(what, ok):
    global fails
    print(("ok   " if ok else "FAIL ") + what)
    fails += not ok


with tempfile.TemporaryDirectory() as tmp:
    src = zip_with(Path(tmp) / "downloaded_screenshots.zip", ["en-US/1.png", "de-DE/1.png"])
    cleaned = zip_with(Path(tmp) / "svc.zip", ["0001.png", "0002.png"]).read_bytes()
    calls = fake(["processing...", "success"], cleaned)
    metaclean.strip_metadata(src, "screenshots")
    name = calls["names"][0]
    check("в сервис уходит имя с уникальной меткой: " + name, re.fullmatch(r"[0-9a-f]{8}_downloaded_screenshots\.safe\.zip", name) is not None)
    calls2 = fake(["success"], cleaned)
    metaclean.strip_metadata(zip_with(Path(tmp) / "downloaded_screenshots.zip", ["en-US/1.png", "de-DE/1.png"]), "screenshots")
    check("у двух прогонов разные имена", calls2["names"][0] != name)
    check("после скачивания файл удаляется с сервиса", calls["deleted"] == ["https://aso.attrifire.com/metaclean/api/delete-metadata/7/"] or (len(calls["deleted"]) == 1 and calls["deleted"][0].endswith("/delete-metadata/7/")))
    check("имена в архиве вернулись", sorted(zipfile.ZipFile(src).namelist()) == ["de-DE/1.png", "en-US/1.png"])

    fake(["processing...", "file deleted"])
    try:
        metaclean.strip_metadata(zip_with(Path(tmp) / "a.zip", ["en-US/1.png"]), "screenshots")
        check("«file deleted» останавливает прогон", False)
    except SystemExit as e:
        check("«file deleted» останавливает прогон с понятной причиной", "deleted on the service" in str(e))

print("\nИтог:", "всё сходится" if not fails else f"ошибок {fails}")
sys.exit(1 if fails else 0)
