import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("sync_releases", Path(__file__).parents[1] / "scripts/sync_releases.py")
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


class MirrorTests(unittest.TestCase):
    def setUp(self):
        self.asset = {"name": "app.apk", "size": 3, "digest": "sha256:" + hashlib.sha256(b"apk").hexdigest(),
                      "browser_download_url": "https://github.com/example/app.apk"}
        self.source = {"id": 10, "tag_name": "v1.0", "name": "Mobile v1.0", "prerelease": False,
                       "published_at": "2026-11-18T11:50:29Z", "assets": [self.asset],
                       "html_url": "https://github.com/Alumos/etkn-mobile/releases/tag/v1.0", "body": "Changes"}

    def test_initial_history_and_saved_delivery_state(self):
        state = sync.state_for(self.source, {}, "2026-11-18T12:00:00Z")
        self.assertEqual("historical", state["telegram"])
        state = sync.state_for(self.source, {}, self.source["published_at"])
        self.assertEqual("pending", state["telegram"])
        state.update(telegram="sent", message_id=99)
        mirror = {"body": sync.release_body(self.source, state)}
        self.assertEqual(state, sync.state_for(self.source, mirror, "2020-01-01T00:00:00Z"))
        self.assertIn("/archive/refs/tags/v1.0.tar.gz", mirror["body"])

    def test_download_checks_actual_bytes_and_hash(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(sync.urllib.request, "urlopen", return_value=io.BytesIO(b"apk")):
                self.assertEqual(b"apk", sync.download(self.asset, folder).read_bytes())
            with patch.object(sync.urllib.request, "urlopen", return_value=io.BytesIO(b"bad")):
                with self.assertRaisesRegex(RuntimeError, "integrity"):
                    sync.download(self.asset, folder)

    def test_telegram_unicode_limit_keeps_links(self):
        self.source["body"] = "😀" * 5000
        text = sync.message_text(self.source, {"html_url": "https://github.com/hbq0405/etkn-mobile/releases/tag/v1.0"})
        self.assertLessEqual(len(text.encode("utf-16-le")) // 2, 4000)
        self.assertIn("https://github.com/hbq0405/etkn-mobile/releases/tag/v1.0", text)
        self.assertTrue(text.endswith(self.source["html_url"]))

    def test_resume_draft_then_notify_only_once(self):
        state = sync.state_for(self.source, {}, self.source["published_at"])
        mirror = {"id": 20, "tag_name": "v1.0", "name": "Mobile v1.0", "draft": True,
                  "prerelease": False, "assets": [copy.deepcopy(self.asset)],
                  "body": sync.release_body(self.source, state), "html_url": "https://example.test/release"}
        def fake_api(path, method="GET", payload=None, missing_ok=False):
            if method == "PATCH":
                mirror.update(payload)
            return copy.deepcopy(mirror)
        with patch.object(sync, "api", side_effect=fake_api), patch.object(sync, "notify", return_value=99) as notify:
            with patch.object(sync, "download") as download:
                sync.sync_one("hbq0405/etkn-mobile", self.source, "v1.0", self.source["published_at"])
                sync.sync_one("hbq0405/etkn-mobile", self.source, "v1.0", self.source["published_at"])
                download.assert_not_called()
            notify.assert_called_once()
        self.assertFalse(mirror["draft"])
        self.assertEqual("sent", sync.state_for(self.source, mirror, "")["telegram"])

    def test_telegram_failure_remains_pending_for_retry(self):
        mirror = {"id": 20, "name": "Mobile v1.0", "draft": False, "prerelease": False,
                  "assets": [copy.deepcopy(self.asset)], "body": "", "html_url": "https://example.test/release"}
        def fake_api(path, method="GET", payload=None, missing_ok=False):
            if method == "PATCH":
                mirror.update(payload)
            return copy.deepcopy(mirror)
        with patch.object(sync, "api", side_effect=fake_api), patch.object(sync, "notify", side_effect=RuntimeError("failed")):
            with self.assertRaisesRegex(RuntimeError, "failed"):
                sync.sync_one("hbq0405/etkn-mobile", self.source, "v1.0", self.source["published_at"])
        self.assertEqual("pending", sync.state_for(self.source, mirror, "")["telegram"])

    def test_unready_or_unsafe_assets_stop_publication(self):
        self.source["assets"] = []
        with self.assertRaisesRegex(RuntimeError, "No published APK"):
            sync.selected_assets(self.source)
        self.asset["name"] = "../app.apk"
        self.source["assets"] = [self.asset]
        with self.assertRaisesRegex(RuntimeError, "Unsafe"):
            sync.selected_assets(self.source)


if __name__ == "__main__":
    unittest.main()