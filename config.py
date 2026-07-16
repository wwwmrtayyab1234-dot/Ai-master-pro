import os

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv() -> None:
        return None


load_dotenv()

APP_NAME = "AI Master Pro"
APP_ENV = os.getenv("APP_ENV", "development").lower()
DEV_PREMIUM_MODE = os.getenv("DEV_PREMIUM_MODE", "false").lower() == "true"

PRIVACY_POLICY_URL = os.getenv("PRIVACY_POLICY_URL", "").strip()
APP_SHARE_URL = os.getenv("APP_SHARE_URL", "").strip()
SUPPORT_EMAIL = os.getenv("SUPPORT_EMAIL", "").strip()
WHATSAPP_NUMBER = os.getenv("WHATSAPP_NUMBER", "").strip()
GOOGLE_OAUTH_CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
GOOGLE_OAUTH_CLIENT_SECRET = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
GOOGLE_OAUTH_REDIRECT_URL = os.getenv(
    "GOOGLE_OAUTH_REDIRECT_URL", "http://localhost:8550/oauth_callback"
).strip()

FREE_DAILY_CREDITS = 50
FREE_REQUESTS_PER_WINDOW = 20
FREE_IMAGES_PER_WINDOW = 5
FREE_VOICE_MAX_SECONDS_PER_CLIP = 60
FREE_DAILY_VOICE_SECONDS = 60
AD_REWARD_CREDITS = 50
ADS_FOR_REQUEST_REFILL = 5
AD_REQUEST_REFILL = 20
ROLLING_WINDOW_HOURS = 24
IMAGE_REQUESTS_PER_MINUTE = 3
IMAGE_MAX_RETRIES = 3

# AdMob production IDs. Test IDs are selected automatically while
# ADMOB_TEST_MODE is enabled, so live ads are never clicked during development.
ADMOB_APP_ID = os.getenv(
    "ADMOB_APP_ID", "ca-app-pub-3725379940334991~3875540091"
).strip()
ADMOB_REWARDED_UNIT_ID = os.getenv(
    "ADMOB_REWARDED_UNIT_ID", "ca-app-pub-3725379940334991/1504372099"
).strip()
ADMOB_NATIVE_UNIT_ID = os.getenv(
    "ADMOB_NATIVE_UNIT_ID", "ca-app-pub-3725379940334991/5200642743"
).strip()
ADMOB_TEST_MODE = os.getenv("ADMOB_TEST_MODE", "true").lower() == "true"
ADMOB_TEST_REWARDED_UNIT_ID = "ca-app-pub-3940256099942544/5224354917"
ADMOB_TEST_NATIVE_UNIT_ID = "ca-app-pub-3940256099942544/2247696110"

PREMIUM_MONTHLY_CHAT = 1_000
PREMIUM_MONTHLY_IMAGES = 100
PREMIUM_MONTHLY_ENHANCEMENTS = 300
PREMIUM_MONTHLY_VOICE_CHARS = 30_000
PREMIUM_VIDEO_MAX_SECONDS = 180

CREDIT_COSTS = {
    "chat": 1,
    "analysis": 1,
    "image": 10,
    "enhance": 1,
    "voice": 1,
}
