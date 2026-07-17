import asyncio
import io
import json
import os
import struct
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.error import HTTPError

import flet as ft
import flet_admob_pro as fad

from services.database_service import DatabaseService
from services.error_service import friendly_error
from services.firebase_auth_service import (
    FirebaseAuthService,
    FirebaseUser,
    MAINTENANCE_MESSAGE,
    OFFLINE_MESSAGE,
    SessionExpired,
)
from services.gemini_service import MAX_INLINE_BYTES, _extract_text, analyze_attachment
from services.image_queue_service import ImageGenerationQueue
from services.image_service import generate_flux_image_url
from services.session_service import SessionService
from services.usage_service import UsageService
from services.voice_service import VOICE_OPTIONS, audio_duration_seconds, estimate_seconds
from release_check import validate_release


class DatabaseHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.database = DatabaseService(str(Path(self.tempdir.name) / "test.db"))

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_memory_recall_is_cross_chat_and_account_scoped(self) -> None:
        first_chat = self.database.create_chat("user-a", "Introductions")
        self.database.save_message(first_chat, "user", "My name is Aisha.")
        self.database.learn_from_user_message("user-a", first_chat, "My name is Aisha.")
        second_chat = self.database.create_chat("user-a", "Second chat")

        context = self.database.memory_context("user-a", second_chat)
        self.assertIn("Preferred Name: Aisha", context)
        self.assertIn("My name is Aisha", context)
        self.assertEqual(self.database.memory_context("user-b", None), "")

    def test_attachment_names_are_sanitized_unique_and_confined(self) -> None:
        first = Path(
            self.database.import_attachment(None, "../../report.txt", data=b"first")
        )
        second = Path(
            self.database.import_attachment(None, "../../report.txt", data=b"second")
        )
        self.assertNotEqual(first, second)
        self.assertEqual(first.read_bytes(), b"first")
        self.assertEqual(second.read_bytes(), b"second")
        self.assertEqual(first.parent.resolve(), self.database.attachments_dir.resolve())
        self.assertNotIn("..", first.name)

    def test_invalid_and_oversized_chat_backups_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "valid chat backup"):
            self.database.import_chats("user", b"not-json")
        with self.assertRaisesRegex(ValueError, "smaller than 5 MB"):
            self.database.import_chats("user", b"x" * 5_000_001)
        wrong_format = json.dumps({"format": "other", "version": 1, "chats": []})
        with self.assertRaisesRegex(ValueError, "not exported"):
            self.database.import_chats("user", wrong_format.encode())

    def test_delete_user_data_does_not_delete_external_files(self) -> None:
        external = Path(self.tempdir.name) / "outside.txt"
        external.write_text("keep", encoding="utf-8")
        chat_id = self.database.create_chat("user", "Attachment")
        self.database.save_message(
            chat_id,
            "user",
            "file",
            attachment_name="outside.txt",
            attachment_path=str(external),
        )
        self.database.delete_user_data("user")
        self.assertTrue(external.exists())


class UsageHardeningTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.database = DatabaseService(str(Path(self.tempdir.name) / "test.db"))

    async def asyncTearDown(self) -> None:
        self.tempdir.cleanup()

    async def test_corrupt_numeric_state_recovers_without_crashing(self) -> None:
        self.database.save_user_state(
            "corrupt-user",
            {
                "daily_credits": "not-a-number",
                "request_used": None,
                "image_used": -99,
                "premium": "false",
            },
        )
        usage = UsageService(self.database)
        await usage.initialize("corrupt-user")
        self.assertEqual(usage.daily_credits, 0)
        self.assertEqual(usage.request_used, 0)
        self.assertEqual(usage.data["image_used"], 0)
        self.assertFalse(usage.premium)
        self.assertFalse(usage.gate("chat").allowed)

    async def test_unknown_feature_and_signed_out_access_fail_closed(self) -> None:
        usage = UsageService(self.database)
        self.assertEqual(usage.gate("chat").reason, "auth")
        await usage.initialize("user")
        self.assertEqual(usage.gate("unknown").reason, "config")


class _MemoryStore:
    def __init__(self, fail: bool = False) -> None:
        self.values: dict[str, str] = {}
        self.fail = fail

    async def set(self, key: str, value: str) -> None:
        if self.fail:
            raise RuntimeError("store unavailable")
        self.values[key] = value

    async def get(self, key: str):
        if self.fail:
            raise RuntimeError("store unavailable")
        return self.values.get(key)

    async def remove(self, key: str) -> None:
        if self.fail:
            raise RuntimeError("store unavailable")
        self.values.pop(key, None)


class SessionServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_secure_storage_round_trip_and_clear(self) -> None:
        secure = _MemoryStore()
        fallback = _MemoryStore()
        session = SessionService(secure, fallback)
        user = FirebaseUser("uid", "person@example.com", "id", "refresh", True)
        await session.save(user)
        self.assertEqual((await session.load())["uid"], "uid")
        self.assertFalse(fallback.values)
        await session.clear()
        self.assertIsNone(await session.load())

    async def test_shared_preferences_fallback_and_invalid_data_cleanup(self) -> None:
        fallback = _MemoryStore()
        session = SessionService(_MemoryStore(fail=True), fallback)
        user = FirebaseUser("uid", "person@example.com", "id", "refresh", True)
        await session.save(user)
        self.assertEqual((await session.load())["refresh_token"], "refresh")
        fallback.values[SessionService.KEY] = "broken-json"
        self.assertIsNone(await session.load())


class ProviderBoundaryTests(unittest.IsolatedAsyncioTestCase):
    def test_error_messages_hide_unknown_provider_details(self) -> None:
        self.assertEqual(friendly_error(RuntimeError("HTTP 503 upstream")), MAINTENANCE_MESSAGE)
        self.assertEqual(friendly_error(OSError("network is unreachable")), OFFLINE_MESSAGE)
        self.assertEqual(friendly_error(RuntimeError("secret internal trace")), MAINTENANCE_MESSAGE)
        self.assertEqual(friendly_error(ValueError("Choose a valid file.")), "Choose a valid file.")

    def test_firebase_error_mapping(self) -> None:
        body = io.BytesIO(json.dumps({"error": {"message": "INVALID_REFRESH_TOKEN"}}).encode())
        error = HTTPError("https://example.invalid", 400, "bad", {}, body)
        self.assertIsInstance(FirebaseAuthService._friendly_http_error(error), SessionExpired)

    def test_google_oauth_token_is_exchanged_for_firebase_session(self) -> None:
        service = FirebaseAuthService()
        firebase_response = {
            "localId": "firebase-uid",
            "email": "person@example.com",
            "idToken": "firebase-id-token",
            "refreshToken": "firebase-refresh-token",
        }
        expected_user = FirebaseUser(
            "firebase-uid",
            "person@example.com",
            "firebase-id-token",
            "firebase-refresh-token",
            True,
        )
        with patch.object(service, "_post", return_value=firebase_response) as post, patch.object(
            service, "_user", return_value=expected_user
        ):
            result = service.sign_in_with_google_access_token(
                "google-access-token",
                "http://localhost:8550/oauth_callback",
            )
        self.assertEqual(result, expected_user)
        endpoint, payload = post.call_args.args
        self.assertEqual(endpoint, "signInWithIdp")
        self.assertIn("providerId=google.com", payload["postBody"])
        self.assertTrue(payload["returnSecureToken"])

    def test_gemini_response_and_preflight_validation(self) -> None:
        response = {"candidates": [{"content": {"parts": [{"text": "Result"}]}}]}
        self.assertEqual(_extract_text(response), "Result")
        with self.assertRaises(RuntimeError):
            _extract_text({"candidates": []})
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"GEMINI_API_KEY": "test-key"}
        ):
            unsupported = Path(directory) / "file.exe"
            unsupported.write_bytes(b"x")
            with self.assertRaisesRegex(ValueError, "Supported files"):
                analyze_attachment(str(unsupported), "Analyze")
            oversized = Path(directory) / "large.pdf"
            with oversized.open("wb") as stream:
                stream.truncate(MAX_INLINE_BYTES + 1)
            with self.assertRaisesRegex(ValueError, "smaller than 18 MB"):
                analyze_attachment(str(oversized), "Analyze")

    def test_image_urls_are_encoded_and_randomized(self) -> None:
        first = generate_flux_image_url("a boy & rain")
        second = generate_flux_image_url("a boy & rain")
        self.assertIn("a%20boy%20%26%20rain", first)
        self.assertNotEqual(first, second)
        with self.assertRaises(ValueError):
            generate_flux_image_url("   ")

    async def test_image_queue_serializes_concurrent_jobs(self) -> None:
        queue = ImageGenerationQueue()
        queue.minimum_interval = 0
        active = 0
        maximum_active = 0

        def fake_download(prompt: str, _premium: bool) -> str:
            nonlocal active, maximum_active
            active += 1
            maximum_active = max(maximum_active, active)
            try:
                return f"data:image/png;base64,{prompt}"
            finally:
                active -= 1

        queue._download_image = fake_download
        results = await asyncio.gather(
            queue.generate("one"), queue.generate("two"), queue.generate("three")
        )
        self.assertEqual(maximum_active, 1)
        self.assertEqual(len(results), 3)
        queue.worker_task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await queue.worker_task

    async def test_image_queue_retries_temporary_provider_failures(self) -> None:
        queue = ImageGenerationQueue()
        attempts = 0

        def flaky_download(_prompt: str, _premium: bool) -> str:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise RuntimeError("temporary provider failure")
            return "data:image/png;base64,success"

        queue._download_image = flaky_download
        with patch("services.image_queue_service.IMAGE_MAX_RETRIES", 3), patch(
            "services.image_queue_service.asyncio.sleep", new=AsyncMock()
        ):
            result = await queue._run_with_retries("retry me", False)
        self.assertEqual(result, "data:image/png;base64,success")
        self.assertEqual(attempts, 3)

    def test_voice_catalog_and_estimates(self) -> None:
        self.assertIn("edge_hindi_female", VOICE_OPTIONS)
        self.assertIn("edge_urdu_male", VOICE_OPTIONS)
        self.assertIn("edge_spanish_female", VOICE_OPTIONS)
        self.assertEqual(estimate_seconds(""), 1)
        self.assertGreaterEqual(estimate_seconds("one two three four five"), 2)

    def test_voice_duration_is_measured_from_mp3_frames(self) -> None:
        # MPEG-1 Layer III, 128 kbps, 44.1 kHz: each frame is 417 bytes.
        frame = bytes.fromhex("FFFB9000") + bytes(413)
        self.assertEqual(audio_duration_seconds(frame * 38), 1)
        self.assertEqual(audio_duration_seconds(frame * 39), 2)
        with self.assertRaisesRegex(RuntimeError, "could not be verified"):
            audio_duration_seconds(b"not-an-mp3")


class AdServiceBoundaryTests(unittest.IsolatedAsyncioTestCase):
    def test_custom_rewarded_ad_is_a_registered_flet_service(self) -> None:
        ad = fad.RewardedAd(unit_id="test-unit")
        self.assertIsInstance(ad, ft.Service)
        self.assertEqual(ad._c, "RewardedAd")

    async def test_rewarded_ad_fails_closed_on_non_mobile_production(self) -> None:
        from services.ad_service import watch_rewarded_ad

        with patch("services.ad_service._is_mobile", return_value=False), patch(
            "services.ad_service.APP_ENV", "production"
        ):
            self.assertFalse(await watch_rewarded_ad(object()))


class PackagingConfigurationTests(unittest.TestCase):
    def test_brand_assets_are_valid_square_pngs_and_used_at_startup(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for asset_name, minimum_size in (("icon.png", 1024), ("splash.png", 512)):
            data = (root / "assets" / asset_name).read_bytes()
            self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
            width, height = struct.unpack(">II", data[16:24])
            self.assertEqual(width, height)
            self.assertGreaterEqual(width, minimum_size)

        main_source = (root / "main.py").read_text(encoding="utf-8")
        self.assertGreaterEqual(main_source.count('src="icon.png"'), 4)
        first_frame = main_source.split(
            "# Optional and provider-specific packages", maxsplit=1
        )[0]
        startup = main_source.split("startup_screen =", maxsplit=1)[1].split(
            "offline_screen =", maxsplit=1
        )[0]
        self.assertNotIn("ProgressRing", first_frame)
        self.assertNotIn("ProgressRing", startup)

    def test_android_manifest_and_dependencies(self) -> None:
        root = Path(__file__).resolve().parents[1]
        config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        permissions = config["tool"]["flet"]["android"]["permission"]
        self.assertTrue(permissions["android.permission.INTERNET"])
        self.assertTrue(permissions["android.permission.RECORD_AUDIO"])
        self.assertFalse(permissions["android.permission.CAMERA"])
        self.assertFalse(permissions["android.permission.ACCESS_FINE_LOCATION"])
        app_id = config["tool"]["flet"]["android"]["meta_data"][
            "com.google.android.gms.ads.APPLICATION_ID"
        ]
        self.assertTrue(app_id.startswith("ca-app-pub-"))
        dependencies = config["project"]["dependencies"]
        self.assertIn("flet-admob-pro", dependencies)

        requirements = (root / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn('flet-desktop==0.85.3; platform_system == "Windows"', requirements)

        extension = tomllib.loads(
            (root / "extensions/flet_admob_pro/pyproject.toml").read_text(encoding="utf-8")
        )
        data_files = extension["tool"]["setuptools"]["data-files"]
        self.assertIn("flutter/flet_admob_pro", data_files)
        self.assertIn("flutter/flet_admob_pro/lib", data_files)

    def test_github_apk_workflow_has_required_build_and_security_steps(self) -> None:
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/build.yml").read_text(encoding="utf-8")
        self.assertIn("actions/setup-python@v5", workflow)
        self.assertIn("python -m pip install -r requirements.txt", workflow)
        self.assertIn("python -m unittest discover -s tests -v", workflow)
        self.assertIn("flet build apk --clear-cache --yes --no-rich-output", workflow)
        self.assertIn("actions/upload-artifact@v4", workflow)
        self.assertIn("secrets.FIREBASE_API_KEY", workflow)
        self.assertIn("secrets.GROQ_API_KEY", workflow)
        self.assertIn("Verify private configuration loads", workflow)
        self.assertIn('Path(".env").unlink(missing_ok=True)', workflow)
        self.assertIn("secrets.GOOGLE_OAUTH_CLIENT_SECRET", workflow)
        self.assertNotIn('"GOOGLE_OAUTH_CLIENT_SECRET",', workflow)
        self.assertLess(
            workflow.index("- name: Build Android APK"),
            workflow.index("- name: Clean up private configuration"),
        )

    def test_release_check_accepts_complete_production_configuration(self) -> None:
        environment = {
            "APP_ENV": "production",
            "ADMOB_TEST_MODE": "false",
            "DEV_PREMIUM_MODE": "false",
            "GROQ_API_KEY": "configured-groq-key",
            "GEMINI_API_KEY": "configured-gemini-key",
            "ELEVENLABS_API_KEY": "configured-elevenlabs-key",
            "FIREBASE_API_KEY": "configured-firebase-key",
            "FIREBASE_AUTH_DOMAIN": "project.firebaseapp.com",
            "FIREBASE_PROJECT_ID": "project-id",
            "FIREBASE_APP_ID": "configured-firebase-app-id",
            "GOOGLE_OAUTH_CLIENT_ID": "configured-google-client-id",
            "GOOGLE_OAUTH_REDIRECT_URL": "http://localhost:8550/oauth_callback",
            "SUPPORT_EMAIL": "support@aimasterpro.test",
            "PRIVACY_POLICY_URL": "https://aimasterpro.test/privacy",
            "APP_SHARE_URL": "https://play.google.com/store/apps/details?id=com.aimasterpro.app",
            "ADMOB_APP_ID": "ca-app-pub-3725379940334991~3875540091",
            "ADMOB_REWARDED_UNIT_ID": "ca-app-pub-3725379940334991/1504372099",
            "ADMOB_NATIVE_UNIT_ID": "ca-app-pub-3725379940334991/5200642743",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "privacy_policy.html").write_text("Production privacy", encoding="utf-8")
            (root / "delete_account.html").write_text("Production deletion", encoding="utf-8")
            with patch.dict(os.environ, environment, clear=True):
                self.assertEqual(validate_release(root), [])


if __name__ == "__main__":
    unittest.main()
