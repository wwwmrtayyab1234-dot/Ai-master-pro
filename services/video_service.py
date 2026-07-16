"""Reserved interface for the intentionally locked video-generation feature.

Video *analysis* is implemented by ``gemini_service``. Generative video remains
disabled until a production API provider, billing policy, and moderation flow
are configured; keeping this small import-safe interface prevents optional
desktop video packages from breaking the mobile app.
"""

from pathlib import Path


VIDEO_COMING_SOON_MESSAGE = (
    "Video generation is coming soon. Video upload and analysis are available "
    "in the Analyze section."
)


def create_video(script: str, duration: int, premium: bool) -> Path:
    del script, duration, premium
    raise NotImplementedError(VIDEO_COMING_SOON_MESSAGE)
