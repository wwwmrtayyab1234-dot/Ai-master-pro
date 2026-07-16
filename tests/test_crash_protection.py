import asyncio
import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.crash_service import CrashProtector
from services.database_service import open_database_resilient


class CrashProtectorTests(unittest.TestCase):
    def test_logs_are_written_and_credentials_are_redacted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            protector = CrashProtector(Path(directory) / "logs")
            protector.install()
            try:
                protector.capture_exception(
                    RuntimeError(
                        "api_key=gsk_abcdefghijklmnopqrstuvwxyz123456 "
                        "refresh_token=secret-refresh-value"
                    ),
                    "Provider failed",
                )
                log_text = protector.log_path.read_text(encoding="utf-8")
                self.assertIn("Provider failed", log_text)
                self.assertIn("[REDACTED]", log_text)
                self.assertNotIn("gsk_abcdefghijklmnopqrstuvwxyz123456", log_text)
                self.assertNotIn("secret-refresh-value", log_text)
            finally:
                protector.restore()


class AsyncCrashProtectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_asyncio_unhandled_error_is_captured(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            loop = asyncio.get_running_loop()
            protector = CrashProtector(Path(directory) / "logs")
            protector.install(loop)
            try:
                loop.call_exception_handler(
                    {
                        "message": "Background worker failed",
                        "exception": RuntimeError("temporary failure"),
                    }
                )
                await asyncio.sleep(0)
                log_text = protector.log_path.read_text(encoding="utf-8")
                self.assertIn("Background worker failed", log_text)
                self.assertIn("temporary failure", log_text)
            finally:
                protector.restore()


class DatabaseRecoveryTests(unittest.TestCase):
    def test_context_manager_releases_sqlite_file_handle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database, _backup = open_database_resilient(
                Path(directory) / "ai_master_pro.db"
            )
            connection = database._connect()
            with connection:
                self.assertEqual(connection.execute("SELECT 1").fetchone()[0], 1)
            with self.assertRaisesRegex(sqlite3.ProgrammingError, "closed database"):
                connection.execute("SELECT 1")

    def test_corrupt_database_is_preserved_and_recreated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "ai_master_pro.db"
            corrupt_bytes = b"this is not a sqlite database"
            database_path.write_bytes(corrupt_bytes)

            database, backup = open_database_resilient(database_path)

            self.assertIsNotNone(backup)
            self.assertEqual(backup.read_bytes(), corrupt_bytes)
            self.assertTrue(database_path.is_file())
            chat_id = database.create_chat("recovered-user", "Recovered")
            self.assertGreater(chat_id, 0)

    def test_healthy_database_does_not_create_a_recovery_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "ai_master_pro.db"
            first, first_backup = open_database_resilient(database_path)
            first.create_chat("user", "Healthy")
            second, second_backup = open_database_resilient(database_path)

            self.assertIsNone(first_backup)
            self.assertIsNone(second_backup)
            self.assertEqual(len(second.list_chats("user")), 1)


if __name__ == "__main__":
    unittest.main()
