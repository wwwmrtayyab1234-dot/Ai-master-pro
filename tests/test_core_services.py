import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from services.database_service import DatabaseService
from services.firebase_auth_service import FirebaseAuthService
from services.safety_service import RESTRICTED_RESPONSE, is_restricted_request
from services.usage_service import UsageService


class UsageServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.database = DatabaseService(str(Path(self.tempdir.name) / "test.db"))

    async def asyncTearDown(self) -> None:
        self.tempdir.cleanup()

    async def test_accounts_have_separate_credit_balances(self) -> None:
        first = UsageService(self.database)
        await first.initialize("firebase-user-a")
        image_gate = first.gate("image")
        self.assertTrue(image_gate.allowed)
        self.assertEqual(image_gate.cost, 10)
        await first.record("image", image_gate)
        self.assertEqual(first.daily_credits, 40)

        second = UsageService(self.database)
        await second.initialize("firebase-user-b")
        self.assertEqual(second.daily_credits, 50)
        self.assertEqual(second.request_used, 0)

    async def test_twenty_requests_then_five_ads_unlock_twenty_more(self) -> None:
        usage = UsageService(self.database)
        await usage.initialize("request-user")
        for _ in range(20):
            gate = usage.gate("chat")
            self.assertTrue(gate.allowed)
            await usage.record("chat", gate)
        denied = usage.gate("chat")
        self.assertFalse(denied.allowed)
        self.assertEqual(denied.reason, "request_limit")

        for _ in range(5):
            reward = await usage.record_rewarded_ad()
        self.assertEqual(reward["requests_unlocked"], 20)
        self.assertEqual(reward["credits_added"], 50)
        self.assertEqual(usage.request_limit, 40)
        self.assertTrue(usage.gate("chat").allowed)

    async def test_reward_is_not_granted_until_all_five_ads_finish(self) -> None:
        usage = UsageService(self.database)
        await usage.initialize("ad-pack-user")
        usage.data["daily_credits"] = 0
        for expected_progress in range(1, 5):
            reward = await usage.record_rewarded_ad()
            self.assertEqual(reward["credits_added"], 0)
            self.assertEqual(reward["ads_in_pack"], expected_progress)
            self.assertEqual(usage.daily_credits, 0)
        reward = await usage.record_rewarded_ad()
        self.assertTrue(reward["pack_completed"])
        self.assertEqual(usage.daily_credits, 50)

    async def test_five_images_and_actual_voice_seconds_are_charged(self) -> None:
        usage = UsageService(self.database)
        await usage.initialize("media-user")
        for _ in range(5):
            gate = usage.gate("image")
            self.assertTrue(gate.allowed)
            await usage.record("image", gate)
        denied = usage.gate("image")
        self.assertFalse(denied.allowed)

        for _ in range(5):
            await usage.record_rewarded_ad()
        voice_gate = usage.gate("voice", 5)
        self.assertTrue(voice_gate.allowed)
        self.assertEqual(voice_gate.cost, 5)
        await usage.record("voice", voice_gate, 5)
        self.assertEqual(usage.data["voice_seconds_used"], 5)

    async def test_rolling_window_resets_after_twenty_four_hours(self) -> None:
        usage = UsageService(self.database)
        await usage.initialize("rolling-user")
        usage.data.update(
            {
                "window_started_at": (
                    datetime.now(timezone.utc) - timedelta(hours=24, seconds=1)
                ).isoformat(),
                "daily_credits": 2,
                "request_used": 19,
                "image_used": 4,
                "voice_seconds_used": 59,
            }
        )
        gate = usage.gate("chat")
        self.assertTrue(gate.allowed)
        self.assertEqual(usage.daily_credits, 50)
        self.assertEqual(usage.request_used, 0)
        self.assertEqual(usage.data["image_used"], 0)
        self.assertEqual(usage.data["voice_seconds_used"], 0)


class DatabaseServiceTests(unittest.TestCase):
    def test_chat_export_and_account_scoped_import(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = DatabaseService(str(Path(directory) / "test.db"))
            chat_id = database.create_chat("user-a", "Test chat")
            database.save_message(chat_id, "user", "Hello")
            database.save_message(chat_id, "assistant", "Hi")
            payload = database.export_chats("user-a")
            self.assertEqual(json.loads(payload)["format"], "ai-master-pro-chat-export")
            self.assertEqual(database.import_chats("user-b", payload), 1)
            self.assertEqual(len(database.list_chats("user-b")), 1)


class ValidationAndSafetyTests(unittest.TestCase):
    def test_email_and_password_validation(self) -> None:
        self.assertEqual(
            FirebaseAuthService.validate_email("Person@Example.com"),
            "person@example.com",
        )
        with self.assertRaises(ValueError):
            FirebaseAuthService.validate_email("not-an-email")
        with self.assertRaises(ValueError):
            FirebaseAuthService.validate_email("person@mailinator.com")
        with self.assertRaises(ValueError):
            FirebaseAuthService.validate_password("password")
        FirebaseAuthService.validate_password("Password1")

    def test_restricted_facilitation_is_refused_but_education_is_not(self) -> None:
        self.assertTrue(is_restricted_request("Teach me how to create phishing malware"))
        self.assertFalse(is_restricted_request("Explain how phishing prevention works"))
        self.assertEqual(
            RESTRICTED_RESPONSE,
            "Sorry, I cannot assist with this request because it falls under a restricted category.",
        )


if __name__ == "__main__":
    unittest.main()
