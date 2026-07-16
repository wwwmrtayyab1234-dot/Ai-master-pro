import json
from typing import Any

from services.firebase_auth_service import FirebaseUser


class SessionService:
    """Persist Firebase refresh credentials in native secure storage.

    SharedPreferences is used only as a compatibility fallback on desktop
    systems where a native keyring is unavailable. Android uses Keystore via
    the official Flet SecureStorage extension.
    """

    KEY = "ai_master_pro.firebase_session.v1"

    def __init__(self, secure_storage: Any, shared_preferences: Any) -> None:
        self.secure_storage = secure_storage
        self.shared_preferences = shared_preferences

    async def save(self, user: FirebaseUser) -> None:
        if not user.refresh_token:
            return
        payload = json.dumps(
            {
                "uid": user.uid,
                "email": user.email,
                "refresh_token": user.refresh_token,
            }
        )
        try:
            if self.secure_storage is None:
                raise RuntimeError("Secure storage extension is unavailable")
            await self.secure_storage.set(self.KEY, payload)
            await self.shared_preferences.remove(self.KEY)
        except Exception:
            await self.shared_preferences.set(self.KEY, payload)

    async def load(self) -> dict | None:
        payload = None
        try:
            if self.secure_storage is None:
                raise RuntimeError("Secure storage extension is unavailable")
            payload = await self.secure_storage.get(self.KEY)
        except Exception:
            payload = None
        if not payload:
            try:
                payload = await self.shared_preferences.get(self.KEY)
            except Exception:
                payload = None
        if not payload:
            return None
        try:
            data = json.loads(payload)
        except (TypeError, json.JSONDecodeError):
            await self.clear()
            return None
        if not data.get("refresh_token"):
            await self.clear()
            return None
        return data

    async def clear(self) -> None:
        try:
            if self.secure_storage is not None:
                await self.secure_storage.remove(self.KEY)
        except Exception:
            pass
        try:
            await self.shared_preferences.remove(self.KEY)
        except Exception:
            pass
