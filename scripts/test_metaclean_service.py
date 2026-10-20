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

# Архив больше лимита: делится на части, каждая чистится отдельно, собирается обратно.
uploads = []


def echo_post(url, headers, files, timeout):
    name, handle = files["file"]
    uploads.append((name, handle.read()))
    return Resp(201, {"id": len(uploads)})


def echo_get(url, headers, timeout, stream=False):
    m = re.search(r"/media/(\d+)$", url)
    if m:
        return Resp(200, body=uploads[int(m.group(1)) - 1][1])
    n = int(re.search(r"/(\d+)/$", url).group(1))
    return Resp(200, {"status": "success", "result_url": f"https://svc/media/{n}"})


metaclean.requests.post, metaclean.requests.get = echo_post, echo_get
metaclean.requests.delete = lambda url, headers, timeout: Resp(200)
os.environ["METACLEAN_MAX_BYTES"] = "4000"
with tempfile.TemporaryDirectory() as tmp:
    names = [f"{loc}/{i}.png" for loc in ("en-US", "de-DE", "fr-FR") for i in (1, 2)]
    big = Path(tmp) / "downloaded_screenshots.zip"
    with zipfile.ZipFile(big, "w", zipfile.ZIP_STORED) as z:
        for i, n in enumerate(names):
            z.writestr(n, bytes([i]) * 1500)
    metaclean.strip_metadata(big, "screenshots")
    check(f"архив больше лимита ушёл частями: {len(uploads)}", len(uploads) >= 2)
    check("каждая часть меньше лимита", all(len(body) <= 4000 for _, body in uploads))
    with zipfile.ZipFile(big) as z:
        back = {n: z.read(n) for n in z.namelist()}
    check("собран обратно: все файлы, исходные имена и содержимое",
          sorted(back) == sorted(names) and all(back[n] == bytes([i]) * 1500 for i, n in enumerate(names)))

    huge = Path(tmp) / "one_big.zip"
    with zipfile.ZipFile(huge, "w", zipfile.ZIP_STORED) as z:
        z.writestr("en-US/1.png", b"x" * 5000)
    try:
        metaclean.strip_metadata(huge, "screenshots")
        check("один файл больше лимита останавливает прогон", False)
    except SystemExit as e:
        check("один файл больше лимита останавливает прогон с понятной причиной", "one file is" in str(e))
del os.environ["METACLEAN_MAX_BYTES"]

print("\nИтог:", "всё сходится" if not fails else f"ошибок {fails}")
sys.exit(1 if fails else 0)
