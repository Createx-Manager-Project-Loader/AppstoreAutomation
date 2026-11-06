"""Выпуск по кнопке: что уходит в Apple и где мы останавливаемся. Apple не трогаем.

Запуск: python3 scripts/release/test_release.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import release as r  # noqa: E402

r.time.sleep = lambda _s: None


def version(number, state, phased=None, vid=None):
    v = {"id": vid or f"v-{number}", "type": "appStoreVersions",
         "attributes": {"versionString": number, "appStoreState": state, "createdDate": f"2026-11-0{len(number)}"},
         "relationships": {"appStoreVersionPhasedRelease": {"data": {"id": f"p-{number}"} if phased else None}}}
    return v, ({"id": f"p-{number}", "type": "appStoreVersionPhasedReleases",
                "attributes": {"phasedReleaseState": phased}} if phased else None)


class Fake:
    def __init__(self, *pairs):
        self.versions = [p[0] for p in pairs]
        self.included = [p[1] for p in pairs if p[1]]
        self.calls = []

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs.get("json")))
        if method == "GET" and "/appStoreVersions?" in path:
            assert "appStoreVersionPhasedRelease&include" in path, "связь должна быть в fields"
            return {"data": self.versions, "included": self.included}
        return {}

    def writes(self):
        return [(m, p, j) for m, p, j in self.calls if m != "GET"]


class ReleaseTest(unittest.TestCase):
    def test_release_pending_version(self):
        c = Fake(version("1.6.1", "PENDING_DEVELOPER_RELEASE", "INACTIVE"), version("1.6", "READY_FOR_SALE"))
        r.release(c, r.by_version(r.versions_of(c, "app"), "1.6.1"))
        method, path, body = c.writes()[0]
        self.assertEqual((method, path), ("POST", "/appStoreVersionReleaseRequests"))
        self.assertEqual(body["data"]["relationships"]["appStoreVersion"]["data"]["id"], "v-1.6.1")

    def test_release_refuses_not_pending(self):
        c = Fake(version("1.6.1", "IN_REVIEW"))
        with self.assertRaisesRegex(r.Stop, "не ждёт выпуска"):
            r.release(c, r.by_version(r.versions_of(c, "app"), "1.6.1"))
        self.assertEqual(c.writes(), [])

    def test_unknown_version_stops(self):
        c = Fake(version("1.6", "READY_FOR_SALE"))
        with self.assertRaisesRegex(r.Stop, "Версии 1.6.1 в App Store Connect нет"):
            r.by_version(r.versions_of(c, "app"), "1.6.1")

    def test_pause_active(self):
        c = Fake(version("1.6", "READY_FOR_SALE", "ACTIVE"))
        r.phase(c, r.by_version(r.versions_of(c, "app"), "1.6"), "pause")
        method, path, body = c.writes()[0]
        self.assertEqual((method, path), ("PATCH", "/appStoreVersionPhasedReleases/p-1.6"))
        self.assertEqual(body["data"]["attributes"]["phasedReleaseState"], "PAUSED")

    def test_resume_needs_paused(self):
        c = Fake(version("1.6", "READY_FOR_SALE", "ACTIVE"))
        with self.assertRaisesRegex(r.Stop, "из этого состояния"):
            r.phase(c, r.by_version(r.versions_of(c, "app"), "1.6"), "resume")

    def test_complete_from_paused(self):
        c = Fake(version("1.6", "READY_FOR_SALE", "PAUSED"))
        r.phase(c, r.by_version(r.versions_of(c, "app"), "1.6"), "complete")
        self.assertEqual(c.writes()[0][2]["data"]["attributes"]["phasedReleaseState"], "COMPLETE")

    def test_no_phased_release_stops(self):
        c = Fake(version("1.6", "READY_FOR_SALE"))
        with self.assertRaisesRegex(r.Stop, "нет поэтапной раскатки"):
            r.phase(c, r.by_version(r.versions_of(c, "app"), "1.6"), "pause")

    def test_settings_scheduled_and_phased_on(self):
        c = Fake(version("1.6.1", "PREPARE_FOR_SUBMISSION"), version("1.6", "READY_FOR_SALE"))
        v = r.editable_version(c, "app", 0)
        r.apply_settings(c, v, "SCHEDULED", "2026-11-12T08:00:00Z", True)
        patch, post = c.writes()
        self.assertEqual(patch[2]["data"]["attributes"], {"releaseType": "SCHEDULED", "earliestReleaseDate": "2026-11-12T08:00:00Z"})
        self.assertEqual((post[0], post[1]), ("POST", "/appStoreVersionPhasedReleases"))
        self.assertEqual(post[2]["data"]["attributes"]["phasedReleaseState"], "INACTIVE")

    def test_settings_manual_clears_date_and_drops_phased(self):
        c = Fake(version("1.6.1", "PREPARE_FOR_SUBMISSION", "INACTIVE"))
        r.apply_settings(c, r.editable_version(c, "app", 0), "MANUAL", None, False)
        patch, delete = c.writes()
        self.assertIsNone(patch[2]["data"]["attributes"]["earliestReleaseDate"])
        self.assertEqual((delete[0], delete[1]), ("DELETE", "/appStoreVersionPhasedReleases/p-1.6.1"))

    def test_settings_phased_untouched_when_not_asked(self):
        c = Fake(version("1.6.1", "PREPARE_FOR_SUBMISSION", "INACTIVE"))
        r.apply_settings(c, r.editable_version(c, "app", 0), "AFTER_APPROVAL", None, None)
        self.assertEqual(len(c.writes()), 1)

    def test_settings_without_editable_version_stops(self):
        c = Fake(version("1.6", "READY_FOR_SALE"))
        with self.assertRaisesRegex(r.Stop, "так и не появилось"):
            r.editable_version(c, "app", 0)


if __name__ == "__main__":
    unittest.main()
