"""Ссылки на страницы проверяются до заливки. App Store Connect не трогаем.

AI Home 1 (16 октября): в листинге был Support URL «https://support@…com» —
почта вместо сайта. Apple ответил «The Support URL you entered is invalid» и
уронил всю заливку. Теперь такое поле пропускается с понятной причиной, а
остальное заливается.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from build_metadata import build, url_problem  # noqa: E402

ok = True


def check(label, condition):
    global ok
    ok &= bool(condition)
    print(("OK    " if condition else "ПЛОХО ") + label)


check("почта вместо сайта", "почту" in (url_problem("https://support@momentsofexcellenece.com") or ""))
check("без https://", "https://" in (url_problem("www.site.com/support") or ""))
check("пробел", "пробел" in (url_problem("https://site.com/my support") or ""))
check("без домена", "домена" in (url_problem("https://localhost/support") or ""))
check("нормальная ссылка", url_problem("https://momentsofexcellence.com/support") is None)
check("с портом и путём", url_problem("http://site.co.uk:8080/a/b?x=1") is None)

listing = {"meta": {"locale": "en-US"}, "version": {
    "support_url": {"value": "https://support@momentsofexcellenece.com", "status": "confirmed"},
    "marketing_url": {"value": "https://momentsofexcellence.com", "status": "confirmed"},
    "description": {"value": "Text", "status": "confirmed"}}}
out = Path(tempfile.mkdtemp())
result = build(listing, out)
check("плохой Support URL не записан", not (out / "metadata/en-US/support_url.txt").exists())
check("причина в пропусках", any("support_url" in s and "почту" in s for s in result["skipped"]))
check("остальное записано", (out / "metadata/en-US/marketing_url.txt").exists()
      and (out / "metadata/en-US/description.txt").exists())

print("\nИтог:", "всё сходится" if ok else "есть расхождения")
raise SystemExit(0 if ok else 1)
