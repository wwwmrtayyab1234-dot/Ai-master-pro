"""AdMob adapters with verified rewards and desktop-safe development behavior."""

import asyncio
from typing import Optional

import flet as ft

from config import (
    ADMOB_NATIVE_UNIT_ID,
    ADMOB_REWARDED_UNIT_ID,
    ADMOB_TEST_MODE,
    ADMOB_TEST_NATIVE_UNIT_ID,
    ADMOB_TEST_REWARDED_UNIT_ID,
    APP_ENV,
)

try:
    import flet_admob_pro as fad
except ImportError:
    fad = None


def _is_mobile(page: ft.Page) -> bool:
    try:
        return not page.web and page.platform.is_mobile()
    except (AttributeError, TypeError):
        return False


def _unit_id(live_id: str, test_id: str) -> str:
    return test_id if ADMOB_TEST_MODE else live_id


async def watch_rewarded_ad(page: ft.Page, timeout_seconds: int = 150) -> bool:
    """Show one ad and return True only after the SDK reward callback.

    Windows/macOS/Linux cannot render Google Mobile Ads. They use a short
    simulator only in development, so the desktop preview remains testable.
    Production always fails closed when a verified mobile callback is absent.
    """
    if not _is_mobile(page):
        if APP_ENV != "development":
            return False
        await asyncio.sleep(1.25)
        return True

    if fad is None:
        raise RuntimeError("The Android rewarded-ad extension is not installed.")

    loop = asyncio.get_running_loop()
    finished: asyncio.Future[bool] = loop.create_future()
    reward_earned = False

    def settle(value: bool) -> None:
        if not finished.done():
            finished.set_result(value)

    async def on_load(event) -> None:
        try:
            await event.control.show()
        except Exception:
            settle(False)

    def on_reward(_event) -> None:
        nonlocal reward_earned
        reward_earned = True

    def on_close(_event) -> None:
        settle(reward_earned)

    def on_error(_event) -> None:
        settle(False)

    rewarded = fad.RewardedAd(
        unit_id=_unit_id(ADMOB_REWARDED_UNIT_ID, ADMOB_TEST_REWARDED_UNIT_ID),
        request=fad.AdRequest(non_personalized_ads=True),
        on_load=on_load,
        on_reward=on_reward,
        on_close=on_close,
        on_error=on_error,
    )
    page.services.append(rewarded)
    page.update()
    try:
        return await asyncio.wait_for(finished, timeout=timeout_seconds)
    except asyncio.TimeoutError:
        return False
    finally:
        if rewarded in page.services:
            page.services.remove(rewarded)
            page.update()


def create_native_ad(page: ft.Page) -> Optional[ft.Control]:
    """Create a compact native ad for Android/iOS or return None on desktop."""
    if fad is None or not _is_mobile(page):
        return None
    return fad.NativeAd(
        unit_id=_unit_id(ADMOB_NATIVE_UNIT_ID, ADMOB_TEST_NATIVE_UNIT_ID),
        request=fad.AdRequest(non_personalized_ads=True),
        template_style=fad.NativeAdTemplateStyle(
            template_type=fad.NativeAdTemplateType.SMALL,
            main_bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
            corner_radius=16,
        ),
        height=100,
        expand=True,
    )
