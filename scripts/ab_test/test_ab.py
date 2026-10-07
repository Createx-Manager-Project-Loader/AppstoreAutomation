#!/usr/bin/env python3
"""Проверка разбора архива и запретов на действия. App Store Connect не трогаем."""

from __future__ import annotations

import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import experiments as exp  # noqa: E402
import upload  # noqa: E402

OK = True


def check(label: str, got, want) -> None:
    global OK
    good = got == want
    OK = OK and good
    print(("  ok   " if good else "  FAIL ") + label + ("" if good else f"  → {got!r}"))


def archive(names: list[str]) -> Path:
    path = Path(tempfile.mkdtemp()) / "shots.zip"
    with zipfile.ZipFile(path, "w") as z:
        for name in names:
            z.writestr(name, b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    return path


# ── разбор архива ──────────────────────────────────────────────────────────
src = archive([
    "en-US/Screen 01.png",
    "en-US/Screen 02.png",
    "de-DE/Screen 01.png",
    "__MACOSX/en-US/._Screen 01.png",
    "en-US/.DS_Store",
    "readme.txt",
    "Screen без папки.png",
])
out = Path(tempfile.mkdtemp()) / "spread"
by_locale = upload.spread(src, "test", out)

check("локалей найдено", sorted(by_locale), ["de-DE", "en-US"])
check("кадров в en-US", len(by_locale["en-US"]), 2)
check("кадров в de-DE", len(by_locale["de-DE"]), 1)
check("__MACOSX не попал", any("__MACOSX" in str(p) for v in by_locale.values() for p in v), False)
check("скрытые файлы не попали", any(p.name.startswith(".") for v in by_locale.values() for p in v), False)
check("кадр без папки локали отброшен",
      any(p.name == "Screen без папки.png" for v in by_locale.values() for p in v), False)
check("порядок кадров сохранён",
      [p.name for p in by_locale["en-US"]], ["Screen 01.png", "Screen 02.png"])

# повторный разбор в ту же папку не копит мусор
again = upload.spread(src, "test", out)
check("повторный разбор не удваивает", len(again["en-US"]), 2)

# архив без папок локалей и без основного языка — ошибка с понятным текстом
flat = archive(["Screen 01.png", "Screen 02.png"])
try:
    upload.spread(flat, "плоский", Path(tempfile.mkdtemp()) / "flat")
    check("плоский архив без основного языка отвергнут", "не упал", "Problem")
except exp.Problem as error:
    check("плоский архив без основного языка отвергнут", "папки" in str(error), True)

# тот же архив, но основной язык известен — кадры уходят в него
# (Kegel Women 2, 7 октября: тест завёлся, кадры лежали в корне)
placed = upload.spread(flat, "плоский", Path(tempfile.mkdtemp()) / "flat2", "en-US")
check("кадры из корня ушли в основной язык", sorted(placed), ["en-US"])
check("в основном языке оба кадра", len(placed["en-US"]), 2)

# есть папка языка — лишний файл в корне не трогаем
mixed = archive(["de-DE/1.png", "stray.png"])
placed = upload.spread(mixed, "смешанный", Path(tempfile.mkdtemp()) / "mixed", "en-US")
check("при папке языка корень не трогаем", sorted(placed), ["de-DE"])

# папки названы словами, как их пишет команда (Kegel Women 2, 7 октября):
# «English» — это четыре английские локали, «Portuguese BR» — pt-BR
words = archive(["English/1.png", "Portuguese BR/1.png", "Chinese simplified/1.png"])
placed = upload.spread(words, "слова", Path(tempfile.mkdtemp()) / "words")
check("папки-слова поняты", sorted(placed),
      ["en-AU", "en-CA", "en-GB", "en-US", "pt-BR", "zh-Hans"])

# en-UK — так подписан язык в интерфейсе, у Apple это en-GB
uk = archive(["en-UK/1.png", "EN-us/2.png", "xx-YY/3.png"])
placed = upload.spread(uk, "uk", Path(tempfile.mkdtemp()) / "uk")
check("en-UK → en-GB, регистр не важен, выдуманное отсеяно",
      sorted(placed), ["en-GB", "en-US"])

# ── запрет на удаление запущенного теста ───────────────────────────────────
for state in ["ACCEPTED", "READY_FOR_REVIEW", "PREPARE_FOR_SUBMISSION"]:
    try:
        exp.delete_experiment(None, "x", state)  # до запроса не дойдёт
        check(f"удаление разрешено в {state}", "дошло до запроса", "дошло до запроса")
    except exp.Problem:
        check(f"удаление разрешено в {state}", "запрещено", "разрешено")
    except AttributeError:
        # client=None падает уже на самом запросе — значит проверка состояния пропустила
        check(f"удаление разрешено в {state}", "разрешено", "разрешено")

for state in ["RUNNING", "STOPPED", "COMPLETED"]:
    try:
        exp.delete_experiment(None, "x", state)
        check(f"удаление запрещено в {state}", "разрешено", "запрещено")
    except exp.Problem as error:
        check(f"удаление запрещено в {state}", "только остановить" in str(error), True)
    except AttributeError:
        check(f"удаление запрещено в {state}", "разрешено", "запрещено")

print("ИТОГ:", "всё ок" if OK else "ЕСТЬ ОШИБКИ")
raise SystemExit(0 if OK else 1)
