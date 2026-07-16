from typing import Optional

import flet as ft

from flet_admob_pro.base_ad import BaseAd
from flet_admob_pro.types import NativeAdTemplateStyle


@ft.control("NativeAd")
class NativeAd(BaseAd):
    template_style: Optional[NativeAdTemplateStyle] = None
    on_will_dismiss: Optional[ft.ControlEventHandler["NativeAd"]] = None

    def before_update(self):
        super().before_update()
        assert self.template_style is not None, "template_style must be provided"
