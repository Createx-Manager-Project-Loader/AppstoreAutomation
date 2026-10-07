"""Сверка состава архива «до/после» очистки. Сервис не вызываем.

Проверяем ровно то, на чём падал Locator 48: архив, где байты имён — UTF-8, а
флаг UTF-8 не выставлен. Сервис возвращает такой архив уже с флагом, и наивное
сравнение имён объявляло потерю файлов там, где не потерялось ничего.
"""
import struct
import sys
import tempfile
import zlib
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from metaclean import canonical_name, zip_paths

CYRILLIC = "Localization Часть 1/fr-FR/4.jpg"


def write_unflagged(path, names):
    """ZIP, где имена — сырые UTF-8 байты, а флаг UTF-8 не выставлен.

    Собираем вручную: zipfile такой архив записать не даёт — он сам ставит флаг,
    едва в имени появится не-ASCII.
    """
    out = bytearray()
    central = bytearray()
    for name in names:
        raw = name.encode("utf-8")
        data = b"body"
        crc = zlib.crc32(data) & 0xFFFFFFFF
        offset = len(out)
        out += struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, 0, 0, 0, 0,
                           crc, len(data), len(data), len(raw), 0)
        out += raw + data
        central += struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50, 20, 20, 0, 0, 0, 0,
                               crc, len(data), len(data), len(raw),
                               0, 0, 0, 0, 0, offset)
        central += raw
    cd_offset = len(out)
    out += central
    out += struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, len(names), len(names),
                       len(central), cd_offset, 0)
    Path(path).write_bytes(bytes(out))


def write_flagged(path, names):
    """ZIP, как его собирает сервис очистки: имена UTF-8, флаг выставлен."""
    with zipfile.ZipFile(path, "w") as archive:
        for name in names:
            archive.writestr(name, b"body")


def check(label, condition):
    print(("OK   " if condition else "ПЛОХО") + " " + label)
    return bool(condition)


def main():
    work = Path(tempfile.mkdtemp())
    ok = True

    unflagged = work / "unflagged.zip"
    flagged = work / "flagged.zip"
    write_unflagged(unflagged, [CYRILLIC])
    write_flagged(flagged, [CYRILLIC])

    with zipfile.ZipFile(unflagged) as archive:
        item = archive.infolist()[0]
        ok &= check("архив без флага читается как мохабайт",
                    item.orig_filename != CYRILLIC)
        ok &= check("имя приводится к читаемому виду",
                    canonical_name(item) == CYRILLIC)

    ok &= check("состав архивов совпадает, хотя записаны они по-разному",
                zip_paths(unflagged) == zip_paths(flagged))

    # Настоящую потерю файла проверка обязана ловить по-прежнему.
    lost = work / "lost.zip"
    write_flagged(lost, ["Localization Часть 1/fr-FR/9.jpg"])
    ok &= check("подмена файла всё ещё видна",
                zip_paths(unflagged) != zip_paths(lost))

    # Латиница ничего не меняет: имя как записали, так и прочли.
    plain_a = work / "plain_a.zip"
    plain_b = work / "plain_b.zip"
    write_unflagged(plain_a, ["en-US/1.jpg"])
    write_flagged(plain_b, ["en-US/1.jpg"])
    ok &= check("латинские имена совпадают", zip_paths(plain_a) == zip_paths(plain_b))

    # Разложенная форма с macOS и собранная — один и тот же файл.
    nfd = work / "nfd.zip"
    nfc = work / "nfc.zip"
    write_flagged(nfd, ["ru/Кадр й.jpg"])
    write_flagged(nfc, ["ru/Кадр й.jpg"])
    ok &= check("NFD и NFC считаются одним именем", zip_paths(nfd) == zip_paths(nfc))

    # Безопасные имена туда и обратно — без сервиса. Сервис портит
    # нелатинские имена («·» → «ú»), поэтому имена ему не отдаём вовсе.
    from metaclean import _restore_names, _write_safe_copy

    source = work / "dots.zip"
    write_unflagged(source, ["01 · Resemblance.jpg", "en-GB/Кадр 2.jpg"])
    safe = work / "dots.safe.zip"
    names = _write_safe_copy(source, safe)
    with zipfile.ZipFile(safe) as archive:
        sent = sorted(item.filename for item in archive.infolist())
    ok &= check("в сервис уходят только латинские имена",
                all(name.isascii() for name in sent))

    target = work / "dots.restored.zip"
    _restore_names(safe, target, names)
    ok &= check("после очистки имена исходные и читаемые",
                zip_paths(target) == ["01 · Resemblance.jpg", "en-GB/Кадр 2.jpg"])
    with zipfile.ZipFile(target) as archive:
        stored = sorted(item.filename for item in archive.infolist())
    ok &= check("мохабайт архива без флага не закрепился",
                stored == ["01 · Resemblance.jpg", "en-GB/Кадр 2.jpg"])

    # Сервис потерял файл — проверка состава по-прежнему ловит.
    broken = work / "broken.zip"
    with zipfile.ZipFile(safe) as archive, zipfile.ZipFile(broken, "w") as out:
        for item in archive.infolist()[1:]:
            out.writestr(item.filename, archive.read(item))
    try:
        _restore_names(broken, work / "never.zip", names)
        caught = False
    except SystemExit:
        caught = True
    ok &= check("потеря файла сервисом останавливает прогон", caught)

    print("\nИтог:", "всё сходится" if ok else "есть расхождения")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
