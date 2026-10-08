"""Поле длиннее предела Apple не заливается, остальные уезжают."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from build_metadata import build  # noqa: E402

listing = {
    "meta": {"locale": "en-US"},
    "app_information": {
        "name": {"value": "Short", "status": "confirmed"},
        "subtitle": {"value": "x" * 31, "status": "confirmed"},
    },
    "version": {
        "keywords": {"value": "a, b ,c", "status": "confirmed"},
        "description": {"value": "😀" * 4000, "status": "confirmed"},
    },
}

with tempfile.TemporaryDirectory() as out:
    result = build(listing, Path(out))
    meta = Path(out) / "metadata" / "en-US"
    checks = [
        ("подзаголовок 31 знак пропущен", any("subtitle: длиннее 30" in s for s in result["skipped"])),
        ("подзаголовок не записан", not (meta / "subtitle.txt").exists()),
        ("название записано", (meta / "name.txt").read_text().strip() == "Short"),
        ("пробелы в ключах убраны", (meta / "keywords.txt").read_text().strip() == "a,b,c"),
        ("4000 эмодзи — в пределах", (meta / "description.txt").exists()),
    ]

ok = True
for label, cond in checks:
    ok &= cond
    print(("OK   " if cond else "ПЛОХО") + " " + label)
sys.exit(0 if ok else 1)
