"""Снятие метаданных с файлов архива перед заливкой в App Store.

Архив со скриншотами приходит с Google Drive таким, каким его собрали руками:
в кадрах остаются EXIF-поля — модель устройства, имя ретушёра, дата съёмки,
название редактора. В стор это уезжать не должно, поэтому перед распаковкой
архив целиком прогоняется через сервис очистки.

Почему архивом, а не по файлу: сервис принимает ZIP и возвращает ZIP с той же
структурой путей — проверено живым прогоном на вложенных папках
(`de-DE/6.9/Screen 01.jpg` вернулся тем же путём). Один вызов на прогон вместо
сотни, и разбору архива ниже по течению ничего менять не нужно.

Проверено там же: сервис вырезает только служебный сегмент, картинку не
пережимает — 6 тегов EXIF стало 0, а пиксели остались идентичными.

**Очистка обязательна.** Любой сбой — нет токена, архив больше лимита, сервис
не отвечает, вернулся не тот набор путей — останавливает прогон. Решение
владельца: лучше не залить ничего, чем залить неочищенное и не узнать об этом.
"""

import os
import time
import unicodedata
import zipfile
from pathlib import Path

import requests

# Сервис переехал на домен с TLS. Голый IP с него редиректит сюда 308-м,
# но полагаться на редирект нельзя: архив уходит POST-ом, и не каждый
# клиент повторит его после редиректа.
DEFAULT_URL = "https://aso.attrifire.com"

# Лимит сервиса на файл. Наши архивы к нему близко: 39 локалей по 4 кадра —
# это уже около 200 МБ, и картинки в ZIP практически не сжимаются.
DEFAULT_MAX_BYTES = 300 * 1024 * 1024

POLL_SECONDS = 3
# Потолок ожидания: 200 МБ заливаются и обрабатываются заметно дольше пробных
# мегабайт, но вечно ждать нельзя — прогон должен упасть, а не висеть.
TIMEOUT_SECONDS = 900


def _fail(message: str) -> None:
    raise SystemExit(f"ERROR: metadata cleaning — {message}")


def _mb(size: int) -> str:
    return f"{size / 1024 / 1024:.1f} MB"


def _base_url() -> str:
    return (os.environ.get("METACLEAN_URL") or DEFAULT_URL).rstrip("/")


def _max_bytes() -> int:
    raw = os.environ.get("METACLEAN_MAX_BYTES", "").strip()
    return int(raw) if raw.isdigit() else DEFAULT_MAX_BYTES


def canonical_name(item: zipfile.ZipInfo) -> str:
    """Имя записи архива в одном виде, как бы его ни записал архиватор.

    Архивы от ПМов приходят двух видов. В одних выставлен флаг UTF-8 (бит
    0x0800), и zipfile отдаёт имя как есть. В других флага нет, а байты имени
    всё равно UTF-8 — так жмут некоторые архиваторы; zipfile по стандарту
    читает такое имя как cp437 и отдаёт мохабайт («Часть» → «╨º╨░╤ü╤é╤î»).

    Сервис очистки кириллицу распознаёт и возвращает архив уже с флагом, то
    есть с правильными именами. Дословное сравнение «до/после» на этом ломалось
    на ровном месте: файлы те же, имена с виду разные — прогон падал с
    «service changed the archive structure», хотя не потерялось ничего.

    Поэтому имя возвращается к байтам и декодируется одинаково для обеих
    сторон. NFC — на случай macOS: он пишет разложенные формы, и «й» из двух
    кодовых точек иначе не равно «й» из одной.
    """
    name = item.orig_filename
    raw = name.encode("utf-8") if item.flag_bits & 0x800 else name.encode("cp437", "replace")
    try:
        name = raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    return unicodedata.normalize("NFC", name.replace("\\", "/"))


def zip_paths(path: Path) -> list:
    with zipfile.ZipFile(path) as archive:
        return sorted(canonical_name(item) for item in archive.infolist()
                      if not item.is_dir())


def strip_metadata(path: Path, label: str = "archive") -> Path:
    """Прогоняет файл через сервис очистки и подменяет его очищенным.

    Возвращает тот же путь: вызывающему коду не нужно знать, что файл менялся.

    **Имена в сервис не отправляем.** Архив уходит туда под безопасными
    латинскими именами (`0001.jpg`, `0002.jpg`…), а после очистки файлам
    возвращаются исходные. Сервис портит нелатинские имена: «01 · Resemblance.jpg»
    вернулся как «01 ú Resemblance.jpg» из архива с флагом UTF-8 и как
    «01 Â· Resemblance.jpg» без флага — проверено живым вызовом 7 октября на
    именах из Family Tree 15. Кириллицу при этом он пропускал верно, так что
    поломка зависит от символа, и угадывать, какой следующий, бессмысленно.
    Имена — наши: в них локали и порядок кадров, сервису они не нужны.
    """
    if not zipfile.is_zipfile(path):
        _clean_via_service(path, label)
        print(f"Metadata stripped: {label} is now {_mb(path.stat().st_size)}.")
        return path

    safe = path.with_name(path.stem + ".safe.zip")
    names = _write_safe_copy(path, safe)
    try:
        _clean_via_service(safe, label)
        _restore_names(safe, path, names)
    finally:
        safe.unlink(missing_ok=True)

    print(f"Metadata stripped: {label} is now {_mb(path.stat().st_size)}.")
    return path


def _write_safe_copy(source: Path, target: Path) -> dict:
    """Копия архива с безопасными именами. Возвращает «безопасное → исходное».

    Расширение сохраняем: по нему сервис решает, картинка это или нет.
    Каталоги не переносим — путь целиком живёт в исходном имени файла.
    """
    names = {}
    with zipfile.ZipFile(source) as src, \
            zipfile.ZipFile(target, "w", zipfile.ZIP_STORED) as out:
        index = 0
        for item in src.infolist():
            if item.is_dir():
                continue
            index += 1
            # Исходное имя — в каноническом виде: у архива без флага UTF-8
            # zipfile отдаёт мохабайт (cp437), и записать его обратно значило
            # бы закрепить «╨º╨░…» вместо «Часть» уже в нашем же архиве.
            original = canonical_name(item)
            safe = f"{index:04d}{Path(original).suffix.lower()}"
            names[safe] = original
            out.writestr(safe, src.read(item))
    return names


def _restore_names(cleaned: Path, target: Path, names: dict) -> None:
    """Собирает итоговый архив: содержимое — очищенное, имена — исходные."""
    with zipfile.ZipFile(cleaned) as src:
        got = {item.filename for item in src.infolist() if not item.is_dir()}
        if got != set(names):
            lost = sorted(set(names) - got)
            _fail(
                f"service changed the archive structure: {len(names)} entries in, "
                f"{len(got)} out"
                + (f"; missing: {', '.join(names[n] for n in lost[:5])}" if lost else "")
            )
        result = target.with_name(target.stem + ".restored.zip")
        with zipfile.ZipFile(result, "w", zipfile.ZIP_STORED) as out:
            for safe, original in names.items():
                out.writestr(original, src.read(safe))
    result.replace(target)


def _clean_via_service(path: Path, label: str) -> Path:
    """Один проход через сервис: загрузка, ожидание, скачивание, сверка состава."""
    token = (os.environ.get("METACLEAN_TOKEN") or "").strip()
    if not token:
        _fail(
            "METACLEAN_TOKEN is not set. Metadata cleaning is mandatory, so the run "
            "stops here. Add the token to the repository or organization secrets."
        )

    size = path.stat().st_size
    limit = _max_bytes()
    if size > limit:
        _fail(
            f"{label} is {_mb(size)}, over the service limit of {_mb(limit)}. "
            "Split the archive or reduce the number of screenshots."
        )

    base = _base_url()
    headers = {"Authorization": f"Token {token}"}
    before = zip_paths(path) if zipfile.is_zipfile(path) else None

    print(f"Stripping metadata from {label} ({_mb(size)}) via {base}...")

    try:
        with path.open("rb") as handle:
            response = requests.post(
                f"{base}/metaclean/api/delete-metadata/",
                headers=headers,
                files={"file": (path.name, handle)},
                timeout=TIMEOUT_SECONDS,
            )
    except requests.RequestException as error:
        _fail(f"upload failed: {error}")

    if response.status_code == 401 or response.status_code == 403:
        _fail("service rejected the token (401/403). Check METACLEAN_TOKEN.")
    if response.status_code != 201:
        _fail(f"upload returned {response.status_code}: {response.text[:300]}")

    task_id = response.json().get("id")
    if not task_id:
        _fail(f"service did not return a task id: {response.text[:300]}")

    deadline = time.monotonic() + TIMEOUT_SECONDS
    status_url = f"{base}/metaclean/api/delete-metadata/{task_id}/"
    while True:
        if time.monotonic() > deadline:
            _fail(f"task {task_id} did not finish within {TIMEOUT_SECONDS} s")

        try:
            poll = requests.get(status_url, headers=headers, timeout=60)
        except requests.RequestException as error:
            _fail(f"status request failed: {error}")

        if poll.status_code != 200:
            _fail(f"status returned {poll.status_code}: {poll.text[:300]}")

        payload = poll.json()
        status = payload.get("status")
        if status == "success":
            break
        # Статусы сравниваются точно: «processing...» приходит с многоточием.
        if status == "error":
            _fail(f"service reported an error: {payload.get('error')}")
        time.sleep(POLL_SECONDS)

    result_url = payload.get("result_url")
    if not result_url:
        _fail("service reported success but returned no result_url")

    cleaned = path.with_suffix(path.suffix + ".cleaned")
    try:
        with requests.get(result_url, headers=headers, stream=True, timeout=TIMEOUT_SECONDS) as download:
            if download.status_code != 200:
                _fail(f"result download returned {download.status_code}")
            with cleaned.open("wb") as out:
                for chunk in download.iter_content(chunk_size=1024 * 1024):
                    out.write(chunk)
    except requests.RequestException as error:
        cleaned.unlink(missing_ok=True)
        _fail(f"result download failed: {error}")

    # Пути внутри архива — это локали. Если сервис вернёт другой набор, заливка
    # молча потеряет языки, поэтому сверяем состав до подмены файла.
    if before is not None:
        if not zipfile.is_zipfile(cleaned):
            cleaned.unlink(missing_ok=True)
            _fail("service returned something that is not a ZIP")
        after = zip_paths(cleaned)
        if after != before:
            lost = sorted(set(before) - set(after))
            cleaned.unlink(missing_ok=True)
            _fail(
                f"service changed the archive structure: {len(before)} entries in, "
                f"{len(after)} out"
                + (f"; missing: {', '.join(lost[:5])}" if lost else "")
            )

    cleaned.replace(path)
    return path
