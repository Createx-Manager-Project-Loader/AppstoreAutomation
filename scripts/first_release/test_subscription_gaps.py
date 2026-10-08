"""Продукт без кадра для ревью — предупреждение, а не красный прогон.

Решение владельца: заливаем, что есть. Family Tree 15, 7 октября: группа,
продукт, доступность в 175 странах и 175 цен встали, а кадра для ревью не
было — ссылку на архив не передали, — и весь прогон краснел.
App Store Connect не трогаем.
"""
import contextlib
import io
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import setup_subscriptions as ss  # noqa: E402

LISTING = """meta: {locale: en-US}
subscriptions:
  group: { value: "Premium", status: confirmed }
  products:
    - id:           { value: "week.app", status: confirmed }
      duration: "1 week"
      display_name: { value: "Weekly", status: confirmed }
      description:  { value: "All features", status: confirmed }
      price:        { value: 6.99, status: confirmed }
"""


def run(gap, shots=None):
    """main() с подменённым Subscriptions: заводим «продукт» и задаём, чего не хватило."""
    class Fake:
        def __init__(self, client, app_id, listing, locale, shots_dir):
            self.shots = shots
            self.gaps = {}
            self.soft = []

        def grace_period(self):
            return "уже включён"

        def group(self, name):
            return "g1"

        def group_localization(self, group_id, name):
            pass

        def apply(self, group_id, product, notes):
            self.gaps["s1"] = gap
            return "s1"

        def state(self, sub_id):
            return "MISSING_METADATA"

    path = Path(tempfile.mkdtemp()) / "listing.yml"
    path.write_text(LISTING, encoding="utf-8")
    saved = {name: getattr(ss, name) for name in
             ("Subscriptions", "AppStoreConnectClient", "find_app", "require_env", "read_back")}
    ss.Subscriptions = Fake
    ss.AppStoreConnectClient = lambda **kw: None
    ss.find_app = lambda client, bundle: {"id": "1"}
    ss.require_env = lambda name: "x"
    ss.read_back = lambda step, attempts=4: (step.read(), step.read() == step.want)
    sys.argv = ["setup_subscriptions.py", "--listing", str(path)]
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = ss.main()
    finally:
        for name, value in saved.items():
            setattr(ss, name, value)
    return code, out.getvalue()


def check(label, condition):
    print(("OK   " if condition else "ПЛОХО") + " " + label)
    return bool(condition)


def main():
    ok = True
    code, text = run({"no_screenshot": True, "prices_short": False})
    ok &= check("нет только кадра, ссылки не было — прогон зелёный", code == 0)
    ok &= check("предупреждение для консоли", "WARNING: не залилось (некритично)" in text)
    ok &= check("итог не врёт про READY_TO_SUBMIT", "без кадра для ревью: 1" in text)

    code, text = run({"no_screenshot": True, "prices_short": True})
    ok &= check("не хватило цен — по-прежнему красный", code == 1)

    code, text = run({"no_screenshot": True, "prices_short": False}, shots=Path("/tmp/shots"))
    ok &= check("ссылку дали, а кадр не встал — красный", code == 1)

    print("\nИтог:", "всё сходится" if ok else "есть расхождения")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
