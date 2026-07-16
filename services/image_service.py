import secrets
from urllib.parse import quote, urlencode


def generate_flux_image_url(prompt: str, premium: bool = False) -> str:
    clean_prompt = prompt.strip()
    if not clean_prompt:
        raise ValueError("The image prompt cannot be empty.")

    size = 1280 if premium else 1024
    params = urlencode(
        {
            "model": "flux",
            "width": size,
            "height": size,
            "enhance": "true",
            "seed": secrets.randbelow(2_147_483_647),
        }
    )
    return f"https://image.pollinations.ai/prompt/{quote(clean_prompt, safe='')}?{params}"


def generate_flux_video_frame_url(prompt: str, premium: bool = False) -> str:
    """Build a vertical Flux frame URL for short-form video rendering."""
    clean_prompt = prompt.strip()
    if not clean_prompt:
        raise ValueError("The video prompt cannot be empty.")

    width, height = (1080, 1920) if premium else (720, 1280)
    visual_prompt = (
        f"{clean_prompt}, vertical cinematic scene, natural composition, "
        "realistic lighting, highly detailed, no text, no watermark"
    )
    params = urlencode(
        {
            "model": "flux",
            "width": width,
            "height": height,
            "enhance": "true",
            "seed": secrets.randbelow(2_147_483_647),
        }
    )
    return f"https://image.pollinations.ai/prompt/{quote(visual_prompt, safe='')}?{params}"
