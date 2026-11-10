"""Порядок кадров: ставим его только после того, как Apple обработал весь набор.

Модель стора повторяет то, что видно в журналах прогонов: кадр сначала
UPLOAD_COMPLETE, потом COMPLETE; набор Apple выстраивает по времени, когда кадр
закончил обработку; порядок, поставленный во время обработки, отклоняется
409 «reorder Set» или потом переписывается.

Запуск: python3 scripts/test_screenshot_order.py
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import upload_screenshots_api as m  # noqa: E402

m.time.sleep = lambda _seconds: None

REORDER_BUSY = (
    'PATCH x failed with 409: {"errors": [{"code": "STATE_ERROR", '
    '"detail": "Can\'t Add/Remove Relationship when reorder Set: appScreenshotSets"}]}'
)


class FakeStore:
    """Один набор кадров. Обработка кончается в обратном порядке отправки."""

    def __init__(self, polls_to_finish=2, failed=None):
        self.order = []          # что Apple показывает сейчас
        self.state = {}
        self.finished = []       # в каком порядке закончилась обработка
        self.polls = 0
        self.polls_to_finish = polls_to_finish
        self.failed = failed
        self.next_id = 0
        self.patches = 0

    def _tick(self):
        self.polls += 1
        if self.polls < self.polls_to_finish:
            return
        for shot in reversed(list(self.state)):
            if self.state[shot] == "UPLOAD_COMPLETE":
                self.state[shot] = "FAILED" if shot == self.failed else "COMPLETE"
                self.finished.append(shot)
                # Apple пересобирает набор по времени готовности.
                self.order = list(self.finished) + [s for s in self.order if s not in self.finished]

    def busy(self):
        return any(state == "UPLOAD_COMPLETE" for state in self.state.values())

    def request(self, method, path, **kwargs):
        if method == "POST" and path == "/appScreenshots":
            self.next_id += 1
            shot = f"shot-{self.next_id}"
            self.state[shot] = "AWAITING_UPLOAD"
            self.order.append(shot)
            return {"data": {"id": shot, "attributes": {"uploadOperations": [{"op": 1}]}}}
        if method == "PATCH" and path.startswith("/appScreenshots/"):
            self.state[path.rsplit("/", 1)[1]] = "UPLOAD_COMPLETE"
            return {"data": {}}
        if method == "PATCH" and path.endswith("/relationships/appScreenshots"):
            self.patches += 1
            if self.busy():
                raise m.AppStoreConnectError(REORDER_BUSY)
            self.order = [item["id"] for item in kwargs["json"]["data"]]
            return {}
        raise AssertionError(f"unexpected {method} {path}")

    def get_all(self, path):
        if "assetDeliveryState" in path:
            self._tick()
            return [{"id": s, "attributes": {"assetDeliveryState": {"state": self.state[s]}}}
                    for s in self.order]
        return [{"id": s} for s in self.order]

    def upload_operation(self, operation, image_path):
        pass


class OrderTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.images = []
        for name in ("01.png", "02.png", "03.png", "04.png", "05.png"):
            path = Path(self.dir.name) / name
            path.write_bytes(b"png")
            self.images.append(path)

    def tearDown(self):
        self.dir.cleanup()

    def test_order_survives_reverse_processing(self):
        store = FakeStore()
        ids = m.upload_set(store, "set-1", self.images, 300, False, "en-US")
        self.assertEqual(ids, ["shot-1", "shot-2", "shot-3", "shot-4", "shot-5"])
        self.assertEqual(store.order, ids)
        self.assertTrue(all(state == "COMPLETE" for state in store.state.values()))

    def test_upload_complete_is_not_done(self):
        store = FakeStore(polls_to_finish=3)
        for image in self.images:
            m.upload_screenshot(store, "set-1", image, False)
        m.wait_for_processing(store, "set-1", list(store.state), 300, False)
        self.assertGreaterEqual(store.polls, 3)

    def test_failed_processing_raises(self):
        store = FakeStore(failed="shot-3")
        with self.assertRaisesRegex(m.AppStoreConnectError, "shot-3 failed"):
            m.upload_set(store, "set-1", self.images, 300, False, "en-US")

    def test_reorder_busy_is_retried(self):
        store = FakeStore()
        store.state = {"shot-1": "UPLOAD_COMPLETE"}
        store.order = ["shot-1"]
        calls = {"n": 0}
        original = store.request

        def flaky(method, path, **kwargs):
            if path.endswith("/relationships/appScreenshots") and calls["n"] < 2:
                calls["n"] += 1
                raise m.AppStoreConnectError(REORDER_BUSY)
            return original(method, path, **kwargs)

        store.request = flaky
        store.state["shot-1"] = "COMPLETE"
        m.order_screenshots(store, "set-1", ["shot-1"], False)
        self.assertEqual(calls["n"], 2)

    def test_order_that_never_sticks_is_an_error(self):
        store = FakeStore()
        store.order = ["b", "a"]
        store.request = lambda *a, **k: {}
        with self.assertRaisesRegex(m.AppStoreConnectError, "keeps a different screenshot order"):
            m.verify_screenshot_order(store, "set-1", ["a", "b"], False)

    def test_deferred_upload_then_finalize_sets_order(self):
        store = FakeStore()
        ids = m.upload_set(store, "set-1", self.images, 300, False, "en-US", finalize=False)
        self.assertEqual(store.polls, 0, "без ожидания при заливке")
        self.assertEqual(store.patches, 0)
        result = m.finalize_sets(store, [{"locale": "en-US", "set_id": "set-1", "ids": ids, "label": "en-US"}])
        self.assertEqual(result, {"done": ["en-US"], "failed": {}, "unfinished": []})
        self.assertEqual(store.order, ids)

    def test_finalize_never_reuploads_slow_sets(self):
        store = FakeStore(polls_to_finish=10**6)
        ids = m.upload_set(store, "set-1", self.images, 300, False, "en-US", finalize=False)
        before = store.next_id
        result = m.finalize_sets(store, [{"locale": "en-US", "set_id": "set-1", "ids": ids}], timeout_seconds=0)
        self.assertEqual(result["unfinished"], ["en-US"])
        self.assertEqual(result["done"], [])
        self.assertEqual(store.next_id, before, "ничего не перезаливаем")
        self.assertEqual(store.patches, 0, "порядок посреди обработки не ставим")

    def test_finalize_reports_rejected_screenshot(self):
        store = FakeStore(failed="shot-2")
        ids = m.upload_set(store, "set-1", self.images, 300, False, "de-DE", finalize=False)
        result = m.finalize_sets(store, [{"locale": "de-DE", "set_id": "set-1", "ids": ids}])
        self.assertIn("de-DE", result["failed"])
        self.assertEqual(result["done"], [])

    def test_manifest_roundtrip(self):
        path = Path(self.dir.name) / "manifest.jsonl"
        m.append_manifest(path, [{"locale": "en-US", "set_id": "s1", "ids": ["a"]}])
        m.append_manifest(path, [{"locale": "fr-FR", "set_id": "s2", "ids": ["b", "c"]}])
        self.assertEqual([e["locale"] for e in m.read_manifest(path)], ["en-US", "fr-FR"])
        self.assertEqual(m.read_manifest(Path(self.dir.name) / "missing.jsonl"), [])


if __name__ == "__main__":
    unittest.main()
