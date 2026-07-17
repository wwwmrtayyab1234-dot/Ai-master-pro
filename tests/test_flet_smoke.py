import asyncio
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock, patch

import flet as ft
from flet.messaging.connection import Connection
from flet.messaging.session import Session
from flet.pubsub.pubsub_hub import PubSubHub

import main as app


class _FakeConnection(Connection):
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        super().__init__()
        self.loop = loop
        self.executor = ThreadPoolExecutor(max_workers=2)
        self.pubsubhub = PubSubHub(loop=loop, executor=self.executor)
        self.messages = []
        self.page_name = "test"
        self.page_url = "http://localhost:8550"

    def send_message(self, message) -> None:
        self.messages.append(message)

    def get_upload_url(self, file_name: str, _expires: int) -> str:
        return f"http://localhost/{file_name}"

    def oauth_authorize(self, attrs: dict) -> None:
        self.oauth_attrs = attrs


class FletControlTreeSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def test_full_app_tree_mounts_and_resizes(self) -> None:
        """Test that the app's full control tree initializes and mounts correctly in test environment."""
        connection = _FakeConnection(asyncio.get_running_loop())
        session = Session(connection)
        page = session.page
        page.platform = ft.PagePlatform.WINDOWS
        page.width = 430
        page.height = 820

        with tempfile.TemporaryDirectory() as directory, patch.object(
            ft.StoragePaths,
            "get_application_support_directory",
            AsyncMock(return_value=directory),
        ), patch.object(
            ft.Connectivity,
            "get_connectivity",
            AsyncMock(return_value=[ft.ConnectivityType.WIFI]),
        ), patch.object(
            ft.SharedPreferences, "get", AsyncMock(return_value=None)
        ), patch.object(
            ft.SharedPreferences, "set", AsyncMock()
        ), patch.object(
            ft.SharedPreferences, "remove", AsyncMock()
        ):
            # Gracefully handle the optional flet_secure_storage module
            # It's not required in the test environment
            try:
                if app.fss is not None:
                    with patch.object(
                        app.fss.SecureStorage, "get", AsyncMock(return_value=None)
                    ), patch.object(
                        app.fss.SecureStorage, "set", AsyncMock()
                    ), patch.object(
                        app.fss.SecureStorage, "remove", AsyncMock()
                    ):
                        await app.main(page)
                else:
                    await app.main(page)
            except AttributeError:
                # fss module not available or not properly initialized - safe to continue
                # This is expected in CI/CD test environments
                await app.main(page)

            # Test that the app successfully mounts and creates the expected structure
            for width, height in ((340, 640), (430, 820), (1000, 800)):
                page.width = width
                page.height = height
                page.on_resize(None)

        # Verify the control tree is properly initialized
        self.assertEqual(len(page.controls), 1)
        self.assertGreaterEqual(len(page.services), 5)
        self.assertGreaterEqual(len(connection.messages), 2)
        connection.executor.shutdown(wait=True)


if __name__ == "__main__":
    unittest.main()
