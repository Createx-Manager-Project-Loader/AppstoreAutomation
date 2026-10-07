"""Некритичный шаг: его неудача не красит прогон. App Store Connect не трогаем.

Решение владельца: если не встала только информация для ревью (нет
телефона), прогон зелёный, а в отчёте предупреждение. Остальные неудачи —
цена, страны, рейтинг — по-прежнему валят прогон.
"""
import contextlib
import io
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import setup_app  # noqa: E402
from setup_app import Step  # noqa: E402
from upload_screenshots_api import AppStoreConnectError  # noqa: E402

REFUSAL = AppStoreConnectError(
    'PATCH /appStoreReviewDetails/x failed with 409: {"errors": [{"detail" : '
    '"You must provide a value for the attribute \'contactPhone\'"}]}')


def refuse(_want):
    raise REFUSAL


def run(steps):
    """main() на подставных шагах: клиент, приложение и Setup — заглушки."""
    class FakeSetup:
        skipped = []

        def __init__(self, *args, **kwargs):
            pass

        def steps(self):
            return steps

    listing = Path(tempfile.mkdtemp()) / "listing.yml"
    listing.write_text("meta: {locale: en-US}\n", encoding="utf-8")
    patches = {
        "Setup": FakeSetup,
        "AppStoreConnectClient": lambda **kwargs: None,
        "find_app": lambda client, bundle: {"id": "1"},
        "require_env": lambda name: "x",
        "read_back": lambda step, attempts=4: (step.want, True),
    }
    saved = {name: getattr(setup_app, name) for name in patches}
    for name, value in patches.items():
        setattr(setup_app, name, value)
    sys.argv = ["setup_app.py", "--listing", str(listing)]
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = setup_app.main()
    finally:
        for name, value in saved.items():
            setattr(setup_app, name, value)
    return code, out.getvalue() + err.getvalue()


def check(label, condition):
    print(("OK   " if condition else "ПЛОХО") + " " + label)
    return bool(condition)


def main():
    ok = True

    code, text = run([
        Step("информация для ревью", {"notes": "x"}, refuse, lambda: None, soft=True),
        Step("цена", "free", lambda want: None, lambda: "free"),
    ])
    ok &= check("не встал только контакт — прогон зелёный", code == 0)
    ok &= check("в логе предупреждение с причиной",
                "ПРЕДУПРЕЖДЕНИЕ информация для ревью" in text and "contactPhone" in text)
    ok &= check("строка-признак для консоли", "WARNING: не залилось (некритично)" in text)
    ok &= check("ошибки «не встало» нет", "ERROR: не встало" not in text)

    code, text = run([
        Step("информация для ревью", {"notes": "x"}, refuse, lambda: None, soft=True),
        Step("страны", ["USA"], refuse, lambda: None),
    ])
    ok &= check("не встали страны — прогон красный", code == 1)
    ok &= check("в ошибке только страны, контакт — предупреждением",
                "ERROR: не встало: страны" in text and "WARNING: не залилось" in text)

    print("\nИтог:", "всё сходится" if ok else "есть расхождения")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
