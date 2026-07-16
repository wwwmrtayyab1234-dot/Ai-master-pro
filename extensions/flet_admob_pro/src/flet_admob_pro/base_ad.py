from dataclasses import field
from typing import Optional

import flet as ft

from flet_admob_pro.types import AdRequest


@ft.control
class BaseAd(ft.Control):
    unit_id: str
    request: AdRequest = field(default_factory=AdRequest)
    on_load: Optional[ft.ControlEventHandler["BaseAd"]] = None
    on_error: Optional[ft.ControlEventHandler["BaseAd"]] = None
    on_open: Optional[ft.ControlEventHandler["BaseAd"]] = None
    on_close: Optional[ft.ControlEventHandler["BaseAd"]] = None
    on_impression: Optional[ft.ControlEventHandler["BaseAd"]] = None
    on_click: Optional[ft.ControlEventHandler["BaseAd"]] = None

    def before_update(self):
        assert not self.page.web and self.page.platform.is_mobile(), (
            f"{self.__class__.__name__} is only supported on Android and iOS"
        )
