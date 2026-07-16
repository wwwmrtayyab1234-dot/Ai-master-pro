import base64
import json
import mimetypes
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
MAX_INLINE_BYTES = 18 * 1024 * 1024
SUPPORTED_BINARY_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
    "video/mp4",
    "video/mpeg",
    "video/quicktime",
    "video/webm",
    "audio/mpeg",
    "audio/mp4",
    "audio/x-m4a",
    "audio/wav",
    "audio/x-wav",
    "audio/webm",
    "audio/ogg",
}
TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".py",
    ".json",
    ".csv",
    ".html",
    ".css",
    ".js",
    ".ts",
    ".xml",
    ".yaml",
    ".yml",
}


def _extract_text(response: dict) -> str:
    candidates = response.get("candidates") or []
    if not candidates:
        raise RuntimeError("Gemini did not return a response.")
    parts = candidates[0].get("content", {}).get("parts", [])
    text = "\n".join(part.get("text", "") for part in parts if part.get("text"))
    if not text.strip():
        raise RuntimeError("Gemini returned an empty response.")
    return text.strip()


def analyze_attachment(file_path: str, prompt: str, memory_context: str = "") -> str:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is missing from the .env file.")

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError("The attached file could not be found on this device.")
    if path.stat().st_size > MAX_INLINE_BYTES:
        raise ValueError("The attachment must be smaller than 18 MB.")

    user_prompt = prompt.strip() or "Analyze this file and explain the important information."
    instruction = (
        "You are AI Master Pro's multimodal analyst. Analyze the attached file carefully. "
        "Answer in the user's language and writing style. Use the supplied cross-chat memory "
        "when it is relevant. Mention uncertainty instead of inventing facts."
    )
    memory_block = f"\n\nCross-chat memory:\n{memory_context}" if memory_context else ""
    parts: list[dict] = [
        {"text": f"{instruction}{memory_block}\n\nUser request: {user_prompt}"}
    ]

    if path.suffix.lower() in TEXT_EXTENSIONS:
        content = path.read_text(encoding="utf-8", errors="replace")
        parts.append({"text": f"\nAttached file ({path.name}):\n{content}"})
    else:
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if mime_type not in SUPPORTED_BINARY_TYPES:
            raise ValueError(
                "Supported files: PDF, common images, MP4/MOV/WEBM video, WAV/MP3/M4A audio, and text/code files."
            )
        parts.append(
            {
                "inline_data": {
                    "mime_type": mime_type,
                    "data": base64.b64encode(path.read_bytes()).decode("ascii"),
                }
            }
        )

    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 2048},
    }
    request = Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        method="POST",
    )
    try:
        with urlopen(request, timeout=90) as response:
            return _extract_text(json.loads(response.read().decode("utf-8")))
    except HTTPError as error:
        details = json.loads(error.read().decode("utf-8"))
        message = details.get("error", {}).get("message", "Gemini request failed")
        raise RuntimeError(message) from error
    except URLError as error:
        raise RuntimeError("Check your internet connection and Gemini API configuration.") from error
