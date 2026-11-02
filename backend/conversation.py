"""Conversation routing cannot grade, alter letters, or choose contest words."""
import asyncio
import json
import re
import httpx
from backend import config
from backend.host_prompt import HOST_SYSTEM_PROMPT
from backend.spelling_parser import parse_spelling

INTENTS = {'repeat', 'hint', 'sentence', 'score', 'rules', 'pause', 'resume',
           'nervous', 'joke', 'encouragement', 'conversation', 'clarify'}


def local_intent(text):
    clean = text.lower().replace('’', "'").strip(' .!?')
    if re.search(r'\b(?:for|as in|last letter)\b', clean):
        return None
    if (re.search(r'\b(nervous|anxious|scared|difficult|struggling|frustrated)\b', clean)
            or re.search(r'\bthis (?:is|sounds|seems) (?:hard|tough)\b', clean)):
        return 'nervous'
    if clean in {"okay let me try", "okay, let me try", "okay let's try", "okay, let's try", "let's try", "i'm ready to spell"}:
        return 'resume'
    if re.search(r'\b(joke|funny|make me laugh)\b', clean):
        return 'joke'
    if clean in {'thank you', 'thanks', 'this is fun', 'i love this game', 'you are funny'}:
        return 'encouragement'
    return None


def conversational_candidate(text):
    # Short unknown fragments may be STT-damaged letters: do not guess their intent.
    return bool(re.match(r"^(?:can |could |would |why |how |what |do you |are you |i feel |i think |tell me |let's |please )", text.lower().strip()))


async def interpret(text, name, target, report):
    fallback = ('clarify', '')
    if not config.OPENROUTER_API_KEY:
        return fallback
    started = asyncio.get_running_loop().time()
    report('LLM conversation started')
    try:
        async with asyncio.timeout(3):
            async with httpx.AsyncClient(timeout=3) as client:
                response = await client.post('https://openrouter.ai/api/v1/chat/completions',
                    headers={'Authorization': f'Bearer {config.OPENROUTER_API_KEY}'},
                    json={'model': config.OPENROUTER_MODEL, 'max_tokens': 120,
                          'response_format': {'type': 'json_object'},
                          'messages': [{'role': 'system', 'content': HOST_SYSTEM_PROMPT},
                                       {'role': 'user', 'content': json.dumps({'name': name, 'request': text[:600]})}]})
                response.raise_for_status()
                data = json.loads(response.json()['choices'][0]['message']['content'])
        intent = data.get('intent')
        if intent not in INTENTS:
            return fallback
        reply = data.get('reply', '')
        if intent != 'conversation':
            return intent, ''
        if not isinstance(reply, str) or not 1 <= len(reply) <= 280:
            return fallback
        # Never play a generated answer disclosure or claim of grading/scoring.
        compact = re.sub('[^a-z]', '', reply.lower())
        if ((target and target.lower() in compact) or parse_spelling(reply).letters or re.search(
                r'\d|\b(correct|incorrect|right|wrong|score|points|earned|spelling|spelled|answer|won|win|perfect|grade|result|round|letters)\b', reply, re.I)):
            return fallback
        return intent, reply
    except Exception:
        return fallback
    finally:
        report('LLM conversation finished', elapsed_ms=round(
            (asyncio.get_running_loop().time() - started) * 1000, 1))
