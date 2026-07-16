from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from config import (
    ADS_FOR_REQUEST_REFILL,
    AD_REQUEST_REFILL,
    AD_REWARD_CREDITS,
    CREDIT_COSTS,
    DEV_PREMIUM_MODE,
    FREE_DAILY_CREDITS,
    FREE_DAILY_VOICE_SECONDS,
    FREE_IMAGES_PER_WINDOW,
    FREE_REQUESTS_PER_WINDOW,
    FREE_VOICE_MAX_SECONDS_PER_CLIP,
    PREMIUM_MONTHLY_CHAT,
    PREMIUM_MONTHLY_ENHANCEMENTS,
    PREMIUM_MONTHLY_IMAGES,
    PREMIUM_MONTHLY_VOICE_CHARS,
    ROLLING_WINDOW_HOURS,
)
from services.database_service import DatabaseService


@dataclass(frozen=True)
class GateResult:
    allowed: bool
    source: str = ""
    cost: int = 0
    message: str = ""
    reason: str = ""


class UsageService:
    """Per-account credits and quotas stored in SQLite.

    Free limits reset exactly 24 hours after the current window began. They do
    not reset at calendar midnight. Credits are granted only when a complete
    pack of five provider-verified rewarded ads has finished. That pack adds
    fifty credits and twenty request slots to the current rolling window.
    """

    REQUEST_FEATURES = {"chat", "analysis", "enhance"}

    def __init__(self, database: DatabaseService) -> None:
        self.database = database
        self.user_id: str | None = None
        self.data: dict = {}

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @classmethod
    def _defaults(cls) -> dict:
        now = cls._now()
        return {
            "window_started_at": now.isoformat(),
            "month": now.strftime("%Y-%m"),
            "premium": DEV_PREMIUM_MODE,
            "daily_credits": FREE_DAILY_CREDITS,
            "request_used": 0,
            "bonus_request_limit": 0,
            "image_used": 0,
            "voice_seconds_used": 0,
            "ads_in_pack": 0,
            "chat_month": 0,
            "image_month": 0,
            "enhance_month": 0,
            "voice_chars_month": 0,
        }

    async def initialize(self, user_id: str) -> None:
        self.user_id = user_id
        stored = self.database.get_user_state(user_id) or {}
        self.data = {**self._defaults(), **stored}
        self._migrate_legacy_state(stored)
        self._normalize_state()
        self._reset_periods()
        if DEV_PREMIUM_MODE:
            self.data["premium"] = True
        await self.save()

    def _migrate_legacy_state(self, stored: dict) -> None:
        if "request_used" not in stored:
            self.data["request_used"] = self._safe_int(
                stored.get("chat_day", 0)
            ) + self._safe_int(stored.get("enhance_day", 0))
        if "image_used" not in stored:
            self.data["image_used"] = self._safe_int(stored.get("image_day", 0))
        if "voice_seconds_used" not in stored:
            self.data["voice_seconds_used"] = self._safe_int(
                stored.get("voice_seconds_day", 0)
            )

    @staticmethod
    def _safe_int(value: object, default: int = 0) -> int:
        try:
            return max(0, int(value))
        except (TypeError, ValueError, OverflowError):
            return default

    def _normalize_state(self) -> None:
        numeric_fields = (
            "daily_credits",
            "request_used",
            "bonus_request_limit",
            "image_used",
            "voice_seconds_used",
            "ads_in_pack",
            "chat_month",
            "image_month",
            "enhance_month",
            "voice_chars_month",
        )
        for field in numeric_fields:
            self.data[field] = self._safe_int(self.data.get(field, 0))
        premium = self.data.get("premium", False)
        if isinstance(premium, str):
            premium = premium.strip().lower() == "true"
        self.data["premium"] = bool(premium)

    def _window_start(self) -> datetime:
        try:
            value = datetime.fromisoformat(str(self.data["window_started_at"]))
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        except (KeyError, TypeError, ValueError):
            value = self._now()
            self.data["window_started_at"] = value.isoformat()
            return value

    def _reset_periods(self) -> bool:
        now = self._now()
        changed = False
        if now - self._window_start() >= timedelta(hours=ROLLING_WINDOW_HOURS):
            self.data.update(
                {
                    "window_started_at": now.isoformat(),
                    "daily_credits": FREE_DAILY_CREDITS,
                    "request_used": 0,
                    "bonus_request_limit": 0,
                    "image_used": 0,
                    "voice_seconds_used": 0,
                    "ads_in_pack": 0,
                }
            )
            changed = True

        month_key = now.strftime("%Y-%m")
        if self.data.get("month") != month_key:
            self.data.update(
                {
                    "month": month_key,
                    "chat_month": 0,
                    "image_month": 0,
                    "enhance_month": 0,
                    "voice_chars_month": 0,
                }
            )
            changed = True
        return changed

    async def save(self) -> None:
        if self.user_id is not None:
            self.database.save_user_state(self.user_id, self.data)

    @property
    def premium(self) -> bool:
        return bool(self.data.get("premium", False))

    @property
    def daily_credits(self) -> int:
        return self._safe_int(self.data.get("daily_credits", 0))

    @property
    def request_limit(self) -> int:
        return FREE_REQUESTS_PER_WINDOW + max(
            0, self._safe_int(self.data.get("bonus_request_limit", 0))
        )

    @property
    def request_used(self) -> int:
        return self._safe_int(self.data.get("request_used", 0))

    def gate(self, feature: str, units: int = 1) -> GateResult:
        if self.user_id is None:
            return GateResult(False, message="Please sign in first.", reason="auth")
        if feature not in CREDIT_COSTS:
            return GateResult(False, message="This feature is not configured.", reason="config")
        self._reset_periods()
        units = max(1, self._safe_int(units, 1))
        if self.premium:
            return self._premium_gate(feature, units)
        return self._free_gate(feature, units)

    def _premium_gate(self, feature: str, units: int) -> GateResult:
        if feature in {"chat", "analysis"} and self.data["chat_month"] >= PREMIUM_MONTHLY_CHAT:
            return GateResult(False, message="Your monthly request limit has been reached.", reason="limit")
        if feature == "image" and self.data["image_month"] >= PREMIUM_MONTHLY_IMAGES:
            return GateResult(False, message="Your monthly image limit has been reached.", reason="limit")
        if feature == "enhance" and self.data["enhance_month"] >= PREMIUM_MONTHLY_ENHANCEMENTS:
            return GateResult(False, message="Your monthly enhancer limit has been reached.", reason="limit")
        if feature == "voice" and self.data["voice_chars_month"] + units > PREMIUM_MONTHLY_VOICE_CHARS:
            return GateResult(False, message="Your monthly voice limit has been reached.", reason="limit")
        return GateResult(True, source="premium")

    def _free_gate(self, feature: str, units: int) -> GateResult:
        if feature in self.REQUEST_FEATURES and self.request_used >= self.request_limit:
            return GateResult(
                False,
                message=(
                    f"Your {self.request_limit}-request allowance is used. "
                    f"Complete {ADS_FOR_REQUEST_REFILL} rewarded ads to receive "
                    f"{AD_REWARD_CREDITS} credits and {AD_REQUEST_REFILL} more "
                    "requests in this 24-hour window."
                ),
                reason="request_limit",
            )

        if feature == "image" and self._safe_int(
            self.data.get("image_used", 0)
        ) >= FREE_IMAGES_PER_WINDOW:
            return GateResult(
                False,
                message=f"You can generate up to {FREE_IMAGES_PER_WINDOW} images per 24-hour window.",
                reason="limit",
            )

        if feature == "voice":
            if units > FREE_VOICE_MAX_SECONDS_PER_CLIP:
                return GateResult(
                    False,
                    message=f"A single free voiceover can be up to {FREE_VOICE_MAX_SECONDS_PER_CLIP} seconds.",
                    reason="limit",
                )
            if self._safe_int(
                self.data.get("voice_seconds_used", 0)
            ) + units > FREE_DAILY_VOICE_SECONDS:
                return GateResult(
                    False,
                    message=f"Your {FREE_DAILY_VOICE_SECONDS}-second voice limit for this 24-hour window has been reached.",
                    reason="limit",
                )

        cost = units if feature == "voice" else int(CREDIT_COSTS[feature])
        if self.daily_credits >= cost:
            return GateResult(True, source="daily", cost=cost)
        return GateResult(
            False,
            cost=cost,
            message=f"This action needs {cost} credits. Watch an ad to get free credits.",
            reason="credits",
        )

    async def record(self, feature: str, gate: GateResult, units: int = 1) -> None:
        if not gate.allowed:
            return
        if gate.source == "daily":
            self.data["daily_credits"] = max(0, self.daily_credits - gate.cost)
        if feature in self.REQUEST_FEATURES:
            self.data["request_used"] = self.request_used + 1
        if feature in {"chat", "analysis"}:
            self.data["chat_month"] += 1
        elif feature == "image":
            self.data["image_used"] = self._safe_int(
                self.data.get("image_used", 0)
            ) + 1
            self.data["image_month"] += 1
        elif feature == "enhance":
            self.data["enhance_month"] += 1
        elif feature == "voice":
            if self.premium:
                self.data["voice_chars_month"] += max(1, int(units))
            else:
                self.data["voice_seconds_used"] = self._safe_int(
                    self.data.get("voice_seconds_used", 0)
                ) + max(1, self._safe_int(units, 1))
        await self.save()

    async def record_rewarded_ad(self) -> dict:
        """Record one verified completion; grant value only after all five."""
        self._reset_periods()
        progress = self._safe_int(self.data.get("ads_in_pack", 0)) + 1
        unlocked = False
        if progress >= ADS_FOR_REQUEST_REFILL:
            self.data["daily_credits"] = self.daily_credits + AD_REWARD_CREDITS
            self.data["bonus_request_limit"] = self._safe_int(
                self.data.get("bonus_request_limit", 0)
            ) + AD_REQUEST_REFILL
            progress = 0
            unlocked = True
        self.data["ads_in_pack"] = progress
        await self.save()
        return {
            "credits_added": AD_REWARD_CREDITS if unlocked else 0,
            "ads_in_pack": progress,
            "ads_needed": ADS_FOR_REQUEST_REFILL - progress,
            "requests_unlocked": AD_REQUEST_REFILL if unlocked else 0,
            "pack_completed": unlocked,
        }

    def snapshot(self) -> dict:
        if not self.data:
            return {
                "plan": "Free",
                "credits": 0,
                "requests": "Sign in required",
                "images": "Sign in required",
                "voice": "Sign in required",
                "ads": "Sign in required",
                "reset_at": "",
            }
        self._reset_periods()
        reset_at = self._window_start() + timedelta(hours=ROLLING_WINDOW_HOURS)
        if self.premium:
            return {
                "plan": "Premium",
                "credits": self.daily_credits,
                "requests": f"{self.data['chat_month']}/{PREMIUM_MONTHLY_CHAT} this month",
                "images": f"{self.data['image_month']}/{PREMIUM_MONTHLY_IMAGES} this month",
                "voice": f"{self.data['voice_chars_month']}/{PREMIUM_MONTHLY_VOICE_CHARS} characters",
                "ads": "Not required",
                "reset_at": reset_at.isoformat(),
            }
        return {
            "plan": "Free",
            "credits": self.daily_credits,
            "requests": f"{self.request_used}/{self.request_limit} requests in this window",
            "images": f"{self.data.get('image_used', 0)}/{FREE_IMAGES_PER_WINDOW} images",
            "voice": f"{self.data.get('voice_seconds_used', 0)}/{FREE_DAILY_VOICE_SECONDS} seconds",
            "ads": (
                f"{self.data.get('ads_in_pack', 0)}/{ADS_FOR_REQUEST_REFILL} ads "
                f"toward +{AD_REWARD_CREDITS} credits"
            ),
            "reset_at": reset_at.isoformat(),
        }
