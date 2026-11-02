"""Optional OpenRouter personality. It never sees an answer or controls state."""
import logging
import httpx
from backend import config

async def encouragement():
    if not config.OPENROUTER_API_KEY:
        return ""
    try:
        async with httpx.AsyncClient(timeout=4) as client:
            response = await client.post("https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {config.OPENROUTER_API_KEY}"},
                json={"model": config.OPENROUTER_MODEL, "max_tokens": 40,
                      "messages": [{"role": "user", "content": "Give one short, friendly sentence encouraging a spelling bee player to keep practicing. No claims about correctness, no words to spell, no scores."}]})
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"][:200]
    except Exception:
        logging.getLogger(__name__).warning("Optional encouragement unavailable; using scripted host.")
        return ""
