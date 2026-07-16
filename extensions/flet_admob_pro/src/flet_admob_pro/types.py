from dataclasses import dataclass
from enum import Enum
from typing import Optional

import flet as ft


@dataclass
class AdRequest:
    keywords: Optional[list[str]] = None
    content_url: Optional[str] = None
    neighboring_content_urls: Optional[list[str]] = None
    non_personalized_ads: Optional[bool] = None
    http_timeout: Optional[int] = None
    extras: Optional[dict[str, str]] = None


class NativeAdTemplateType(Enum):
    SMALL = "small"
    MEDIUM = "medium"


@dataclass
class NativeAdTemplateTextStyle:
    size: Optional[ft.Number] = None
    text_color: Optional[ft.ColorValue] = None
    bgcolor: Optional[ft.ColorValue] = None


@dataclass
class NativeAdTemplateStyle:
    template_type: NativeAdTemplateType = NativeAdTemplateType.SMALL
    main_bgcolor: Optional[ft.ColorValue] = None
    corner_radius: Optional[ft.Number] = None
    call_to_action_text_style: Optional[NativeAdTemplateTextStyle] = None
    primary_text_style: Optional[NativeAdTemplateTextStyle] = None
    secondary_text_style: Optional[NativeAdTemplateTextStyle] = None
    tertiary_text_style: Optional[NativeAdTemplateTextStyle] = None
