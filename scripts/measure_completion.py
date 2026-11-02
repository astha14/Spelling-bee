"""Local real-clock timer benchmark; no microphone, network, or TTS measurement.

Run from the project root: python -m scripts.measure_completion
"""
import asyncio
import json
import time
from backend.completion import SpellingCompletion
from backend.config import CompletionSettings


async def measure(label, settings, smart):
    done = asyncio.Event()
    timings = {}

    async def submit(token):
        if controller.claim(token):
            timings['speech_end_to_confirmation_prompt_ms'] = round(
                (time.monotonic() - controller.last_speech) * 1000, 1)
            done.set()

    controller = SpellingCompletion(submit, settings)
    controller.begin('APPLE')
    controller.listen()
    controller.speech_started()
    await asyncio.sleep(.05)
    controller.final('APPLE')
    await asyncio.sleep(settings.vad_stop)
    controller.speech_stopped()
    controller.smart_result(controller.token, smart)
    try:
        await asyncio.wait_for(done.wait(), 10)
    finally:
        await controller.close()
    return {'scenario': label, **timings}


async def main():
    old = CompletionSettings(completion_timeout=2.5, maximum_timeout=4.0)
    new = CompletionSettings()
    results = await asyncio.gather(
        measure('previous: Smart Turn complete', old, True),
        measure('current: Smart Turn complete', new, True),
        measure('previous: fallback', old, False),
        measure('current: fallback', new, False),
    )
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
