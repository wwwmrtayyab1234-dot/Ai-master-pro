import asyncio
import json
import math
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import edge_tts


VOICE_OPTIONS = {
    "edge_male": {
        "name": "English Male — Free",
        "engine": "edge",
        "voice_id": "en-US-AndrewNeural",
        "premium": False,
    },
    "edge_female": {
        "name": "English Female — Free",
        "engine": "edge",
        "voice_id": "en-US-AriaNeural",
        "premium": False,
    },
    "edge_urdu_male": {
        "name": "Urdu Male — Free",
        "engine": "edge",
        "voice_id": "ur-PK-AsadNeural",
        "premium": False,
    },
    "edge_urdu_female": {
        "name": "Urdu Female — Free",
        "engine": "edge",
        "voice_id": "ur-PK-UzmaNeural",
        "premium": False,
    },
    "edge_hindi_male": {
        "name": "Hindi Male - Free",
        "engine": "edge",
        "voice_id": "hi-IN-MadhurNeural",
        "premium": False,
    },
    "edge_hindi_female": {
        "name": "Hindi Female - Free",
        "engine": "edge",
        "voice_id": "hi-IN-SwaraNeural",
        "premium": False,
    },
    "edge_arabic_female": {
        "name": "Arabic Female - Free",
        "engine": "edge",
        "voice_id": "ar-SA-ZariyahNeural",
        "premium": False,
    },
    "edge_spanish_female": {
        "name": "Spanish Female - Free",
        "engine": "edge",
        "voice_id": "es-ES-ElviraNeural",
        "premium": False,
    },
    "edge_french_female": {
        "name": "French Female - Free",
        "engine": "edge",
        "voice_id": "fr-FR-DeniseNeural",
        "premium": False,
    },
    "edge_german_female": {
        "name": "German Female - Free",
        "engine": "edge",
        "voice_id": "de-DE-KatjaNeural",
        "premium": False,
    },
    "edge_portuguese_female": {
        "name": "Portuguese Female - Free",
        "engine": "edge",
        "voice_id": "pt-BR-FranciscaNeural",
        "premium": False,
    },
    "edge_bengali_female": {
        "name": "Bengali Female - Free",
        "engine": "edge",
        "voice_id": "bn-IN-TanishaaNeural",
        "premium": False,
    },
    "edge_indonesian_female": {
        "name": "Indonesian Female - Free",
        "engine": "edge",
        "voice_id": "id-ID-GadisNeural",
        "premium": False,
    },
    "edge_turkish_female": {
        "name": "Turkish Female - Free",
        "engine": "edge",
        "voice_id": "tr-TR-EmelNeural",
        "premium": False,
    },
    "edge_japanese_female": {
        "name": "Japanese Female - Free",
        "engine": "edge",
        "voice_id": "ja-JP-NanamiNeural",
        "premium": False,
    },
    "edge_korean_female": {
        "name": "Korean Female - Free",
        "engine": "edge",
        "voice_id": "ko-KR-SunHiNeural",
        "premium": False,
    },
    "edge_chinese_female": {
        "name": "Chinese Mandarin Female - Free",
        "engine": "edge",
        "voice_id": "zh-CN-XiaoxiaoNeural",
        "premium": False,
    },
    "eleven_adam": {
        "name": "Adam — Premium ElevenLabs",
        "engine": "elevenlabs",
        "voice_id": "pNInz6obpgDQGcFmaJgB",
        "premium": True,
    },
    "eleven_rachel": {
        "name": "Rachel — Premium ElevenLabs",
        "engine": "elevenlabs",
        "voice_id": "21m00Tcm4TlvDq8ikWAM",
        "premium": True,
    },
}


def estimate_seconds(text: str) -> int:
    words = len(text.split())
    return max(1, round(words / 2.3))


def audio_duration_seconds(audio: bytes) -> int:
    """Return billable whole seconds by reading MPEG audio frame headers."""
    version_names = {0: "2.5", 2: "2", 3: "1"}
    layer_names = {1: 3, 2: 2, 3: 1}
    sample_rates = {
        "1": (44100, 48000, 32000),
        "2": (22050, 24000, 16000),
        "2.5": (11025, 12000, 8000),
    }
    mpeg1_bitrates = {
        1: (0, 32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448),
        2: (0, 32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384),
        3: (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320),
    }
    mpeg2_bitrates = {
        1: (0, 32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256),
        2: (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160),
        3: (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160),
    }
    index = 0
    duration = 0.0
    audio_length = len(audio)
    while index + 4 <= audio_length:
        if audio[index] != 0xFF or audio[index + 1] & 0xE0 != 0xE0:
            index += 1
            continue
        header = int.from_bytes(audio[index : index + 4], "big")
        version = version_names.get((header >> 19) & 0x3)
        layer = layer_names.get((header >> 17) & 0x3)
        bitrate_index = (header >> 12) & 0xF
        rate_index = (header >> 10) & 0x3
        padding = (header >> 9) & 0x1
        if not version or not layer or bitrate_index in {0, 15} or rate_index == 3:
            index += 1
            continue
        rate = sample_rates[version][rate_index]
        rates = mpeg1_bitrates if version == "1" else mpeg2_bitrates
        bitrate = rates[layer][bitrate_index] * 1000
        if layer == 1:
            frame_length = int((12 * bitrate / rate + padding) * 4)
            samples = 384
        elif layer == 3 and version != "1":
            frame_length = int(72 * bitrate / rate + padding)
            samples = 576
        else:
            frame_length = int(144 * bitrate / rate + padding)
            samples = 1152
        if frame_length < 4 or index + frame_length > audio_length:
            index += 1
            continue
        duration += samples / rate
        index += frame_length
    if duration <= 0:
        raise RuntimeError("The generated audio duration could not be verified.")
    return max(1, math.ceil(duration))


async def _edge_audio(text: str, voice_id: str) -> bytes:
    output = bytearray()
    communicate = edge_tts.Communicate(text=text, voice=voice_id)
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            output.extend(chunk["data"])
    if not output:
        raise RuntimeError("Edge TTS did not return audio.")
    return bytes(output)


def _eleven_audio(text: str, voice_id: str) -> bytes:
    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        raise RuntimeError("ELEVENLABS_API_KEY is missing from the .env file.")

    request = Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=mp3_44100_128",
        data=json.dumps(
            {"text": text, "model_id": "eleven_multilingual_v2"}
        ).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
            "xi-api-key": api_key,
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=90) as response:
            audio = response.read()
    except HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"ElevenLabs request failed: {details[:240]}") from error
    except URLError as error:
        raise RuntimeError("Check your internet connection and ElevenLabs API key.") from error
    if not audio:
        raise RuntimeError("ElevenLabs did not return audio.")
    return audio


async def generate_voiceover(
    text: str,
    voice_key: str,
    premium_user: bool,
) -> tuple[bytes, str, int]:
    clean_text = text.strip()
    if not clean_text:
        raise ValueError("The voiceover script cannot be empty.")
    if voice_key not in VOICE_OPTIONS:
        raise ValueError("The selected voice is invalid.")

    config = VOICE_OPTIONS[voice_key]
    if config["premium"] and not premium_user:
        raise PermissionError("ElevenLabs voices are available on the premium plan.")

    if config["engine"] == "edge":
        audio = await _edge_audio(clean_text, config["voice_id"])
    else:
        audio = await asyncio.to_thread(_eleven_audio, clean_text, config["voice_id"])

    return audio, config["name"], audio_duration_seconds(audio)
