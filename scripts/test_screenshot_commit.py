"""Коммит скриншота: 409 «уже принят» после 500 — это успех, а не ошибка.

Запуск: python3 scripts/test_screenshot_commit.py
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import upload_screenshots_api as m  # noqa: E402

ALREADY = (
    'PATCH https://api.appstoreconnect.apple.com/v1/appScreenshots/x failed with 409: '
    '{"errors": [{"code": "STATE_ERROR", "detail": "Asset in Completed! can\'t be re-committed!"}, '
    '{"code": "STATE_ERROR", "detail": "Asset is already Approved! can\'t commit Asset!"}]}'
)


class FakeClient:
    def __init__(self, patch_error):
        self.patch_error = patch_error

    def request(self, method, path, **kwargs):
        if method == "POST":
            return {"data": {"id": "shot-1", "attributes": {"uploadOperations": [{"op": 1}]}}}
        raise m.AppStoreConnectError(self.patch_error)

    def upload_operation(self, operation, image_path):
        pass


class CommitTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".png")
        self.tmp.write(b"png")
        self.tmp.flush()

    def tearDown(self):
        self.tmp.close()

    def test_already_committed_is_success(self):
        got = m.upload_screenshot(FakeClient(ALREADY), "set-1", Path(self.tmp.name), dry_run=False)
        self.assertEqual(got, "shot-1")

    def test_other_409_still_fails(self):
        err = 'PATCH x failed with 409: {"errors": [{"code": "STATE_ERROR", "detail": "Set is locked"}]}'
        with self.assertRaises(m.AppStoreConnectError):
            m.upload_screenshot(FakeClient(err), "set-1", Path(self.tmp.name), dry_run=False)

    def test_500_still_fails(self):
        with self.assertRaises(m.AppStoreConnectError):
            m.upload_screenshot(FakeClient("PATCH x failed after 5 attempts"), "set-1", Path(self.tmp.name), dry_run=False)


if __name__ == "__main__":
    unittest.main()
