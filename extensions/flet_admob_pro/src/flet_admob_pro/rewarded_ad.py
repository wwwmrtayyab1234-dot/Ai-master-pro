from dataclasses import field
from typing import Optional

import flet as ft

from flet_admob_pro.types import AdRequest


@ft.control("RewardedAd")
class RewardedAd(ft.Service):
    """A non-visual Flet service that owns one rewarded-ad lifecycle."""

    unit_id: str
    request: AdRequest = field(default_factory=AdRequest)
    on_load: Optional[ft.ControlEventHandler["RewardedAd"]] = None
    on_error: Optional[ft.ControlEventHandler["RewardedAd"]] = None
    on_open: Optional[ft.ControlEventHandler["RewardedAd"]] = None
    on_close: Optional[ft.ControlEventHandler["RewardedAd"]] = None
    on_impression: Optional[ft.ControlEventHandler["RewardedAd"]] = None
    on_click: Optional[ft.ControlEventHandler["RewardedAd"]] = None
    on_reward: Optional[ft.ControlEventHandler["RewardedAd"]] = None

    def before_update(self):
        assert not self.page.web and self.page.platform.is_mobile(), (
            "RewardedAd is only supported on Android and iOS"
        )

    async def show(self) -> None:
        await self._invoke_method("show")
