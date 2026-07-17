import os
from collections.abc import Sequence

FREE_CHAT_MODEL = "llama-3.1-8b-instant"
PREMIUM_CHAT_MODEL = "llama-3.3-70b-versatile"


def _client():
    # Groq imports pydantic/httpx and is relatively expensive on Android.
    # Defer it until the user actually sends a chat or enhances a prompt.
    from groq import AsyncGroq

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is missing from the .env file.")
    return AsyncGroq(api_key=api_key)


async def get_ai_reply(
    messages: Sequence[dict[str, str]],
    premium: bool = False,
    memory_context: str = "",
) -> str:
    model = PREMIUM_CHAT_MODEL if premium else FREE_CHAT_MODEL
    completion = await _client().chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are AI Master Pro, a clear, friendly and practical AI "
                    "assistant for content creators. Help with hooks, scripts, "
                    "captions, content strategy and coding. Detect the language "
                    "and writing style of the user's latest message, then reply "
                    "in that same language and script. English gets English; "
                    "Urdu script gets Urdu script; Roman Urdu gets Roman Urdu; "
                    "Hindi Devanagari gets Hindi; Roman Hindi or Hinglish gets "
                    "the same Roman Hindi or Hinglish style. Apply the same rule "
                    "to Arabic, Spanish, French, German, Portuguese, Bengali, "
                    "Indonesian, Turkish, Japanese, Korean and Chinese. Do not "
                    "translate or switch languages unless the user asks. "
                    "Use the supplied cross-chat memory when it is relevant. "
                    "If the memory contains the user's preferred name, address "
                    "the user naturally by that name without overusing it. "
                    "Never provide instructions that facilitate harmful, illegal, "
                    "exploitative, privacy-invasive, or otherwise restricted activity. "
                    "For a restricted request, reply exactly: Sorry, I cannot assist "
                    "with this request because it falls under a restricted category.\n\n"
                    f"Cross-chat memory:\n{memory_context or 'No saved memory yet.'}"
                ),
            },
            *messages,
        ],
        temperature=0.7,
        max_completion_tokens=1200 if premium else 800,
    )
    reply = completion.choices[0].message.content
    return reply.strip() if reply else "The response could not be generated."


async def enhance_prompt(prompt: str, premium: bool = False) -> str:
    clean_prompt = prompt.strip()
    if not clean_prompt:
        raise ValueError("The prompt cannot be empty.")

    if premium:
        instruction = (
            "Transform the user's short idea into one polished, ultra-detailed "
            "cinematic image-generation prompt. Specify subject, environment, "
            "composition, lighting, mood, color palette, camera/lens, depth, "
            "texture and quality. Preserve the original idea. Return only the "
            "enhanced prompt, without labels or explanation."
        )
    else:
        instruction = (
            "Improve the user's image prompt while keeping it concise. Add a "
            "clear subject, setting, lighting, composition and visual style. "
            "Return only the improved prompt, without labels or explanation."
        )

    completion = await _client().chat.completions.create(
        model=FREE_CHAT_MODEL,
        messages=[
            {"role": "system", "content": instruction},
            {"role": "user", "content": clean_prompt},
        ],
        temperature=0.8,
        max_completion_tokens=350 if premium else 180,
    )
    result = completion.choices[0].message.content
    return result.strip() if result else clean_prompt
