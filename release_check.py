"""Fail closed when a Play Store build still contains development settings."""

import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv


PLACEHOLDER_MARKERS = ("replace_with", "your_", ".example", "changeme")


def _real_value(value: str) -> bool:
    clean = value.strip().lower()
    return bool(clean) and not any(marker in clean for marker in PLACEHOLDER_MARKERS)


def _https_url(value: str) -> bool:
    parsed = urlparse(value.strip())
    return parsed.scheme == "https" and bool(parsed.netloc) and _real_value(value)


def validate_release(root: Path | None = None) -> list[str]:
    project_root = root or Path(__file__).resolve().parent
    load_dotenv(project_root / ".env", override=False)
    errors: list[str] = []

    if os.getenv("APP_ENV", "").strip().lower() != "production":
        errors.append("Set APP_ENV=production in .env.")
    if os.getenv("ADMOB_TEST_MODE", "true").strip().lower() != "false":
        errors.append("Set ADMOB_TEST_MODE=false only for the final signed store build.")
    if os.getenv("DEV_PREMIUM_MODE", "false").strip().lower() == "true":
        errors.append("Set DEV_PREMIUM_MODE=false for release.")

    required_values = {
        "GROQ_API_KEY": os.getenv("GROQ_API_KEY", ""),
        "GEMINI_API_KEY": os.getenv("GEMINI_API_KEY", ""),
        "ELEVENLABS_API_KEY": os.getenv("ELEVENLABS_API_KEY", ""),
        "FIREBASE_API_KEY": os.getenv("FIREBASE_API_KEY", ""),
        "FIREBASE_AUTH_DOMAIN": os.getenv("FIREBASE_AUTH_DOMAIN", ""),
        "FIREBASE_PROJECT_ID": os.getenv("FIREBASE_PROJECT_ID", ""),
        "FIREBASE_APP_ID": os.getenv("FIREBASE_APP_ID", ""),
        "GOOGLE_OAUTH_CLIENT_ID": os.getenv("GOOGLE_OAUTH_CLIENT_ID", ""),
        "GOOGLE_OAUTH_CLIENT_SECRET": os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", ""),
        "SUPPORT_EMAIL": os.getenv("SUPPORT_EMAIL", ""),
    }
    for name, value in required_values.items():
        if not _real_value(value):
            errors.append(f"Add a real {name} value to .env.")

    if not _https_url(os.getenv("PRIVACY_POLICY_URL", "")):
        errors.append("PRIVACY_POLICY_URL must be a real public HTTPS URL.")
    if not _https_url(os.getenv("APP_SHARE_URL", "")):
        errors.append("APP_SHARE_URL must be the real public HTTPS store/listing URL.")

    redirect = os.getenv("GOOGLE_OAUTH_REDIRECT_URL", "").strip()
    if redirect != "http://localhost:8550/oauth_callback":
        errors.append(
            "GOOGLE_OAUTH_REDIRECT_URL must match the registered "
            "http://localhost:8550/oauth_callback URI."
        )

    app_id = os.getenv("ADMOB_APP_ID", "")
    rewarded = os.getenv("ADMOB_REWARDED_UNIT_ID", "")
    native = os.getenv("ADMOB_NATIVE_UNIT_ID", "")
    if not re.fullmatch(r"ca-app-pub-\d{16}~\d{10}", app_id):
        errors.append("ADMOB_APP_ID is invalid.")
    for name, value in (
        ("ADMOB_REWARDED_UNIT_ID", rewarded),
        ("ADMOB_NATIVE_UNIT_ID", native),
    ):
        if not re.fullmatch(r"ca-app-pub-\d{16}/\d{10}", value):
            errors.append(f"{name} is invalid.")

    for file_name in ("privacy_policy.html", "delete_account.html"):
        policy = project_root / file_name
        if not policy.is_file():
            errors.append(f"{file_name} is missing.")
            continue
        content = policy.read_text(encoding="utf-8", errors="replace").lower()
        if "your-domain.example" in content or "your-public-domain.example" in content:
            errors.append(f"Replace placeholder contact/URL text in {file_name}.")

    return errors


def main() -> int:
    errors = validate_release()
    if errors:
        print("PLAY STORE RELEASE CHECK FAILED")
        for error in errors:
            print(f"- {error}")
        return 1
    print("PLAY STORE RELEASE CHECK PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
