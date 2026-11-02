"""FastAPI serves static files and negotiates local WebRTC sessions."""
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from loguru import logger as voice_logger
# Library diagnostics can include TTS text. Keep player-visible terminal logs private.
voice_logger.disable("pipecat")
from pipecat.transports.smallwebrtc.request_handler import SmallWebRTCRequestHandler, SmallWebRTCRequest
from backend import config
from backend.bot import run_bot

if config.COMPLETION.debug:
    logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
handler = SmallWebRTCRequestHandler()
tasks = set()

@asynccontextmanager
async def lifespan(app):
    yield
    await handler.close()
    for task in list(tasks):
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

app = FastAPI(lifespan=lifespan)

@app.middleware("http")
async def fresh_frontend(request, call_next):
    response = await call_next(request)
    if request.url.path in {"/", "/index.html", "/app.js", "/style.css"}:
        response.headers["Cache-Control"] = "no-store"
    return response


class Offer(BaseModel):
    sdp: str = Field(max_length=100000)
    type: str
    difficulty: str = "easy"

@app.get("/api/health")
async def health():
    return {"ok": True, "voice_configured": bool(config.CARTESIA_API_KEY and config.CARTESIA_VOICE_ID)}

@app.post("/api/offer")
async def offer(body: Offer):
    if body.difficulty not in {"easy", "medium", "hard"} or body.type != "offer":
        raise HTTPException(400, "Invalid difficulty or WebRTC offer.")
    if not config.CARTESIA_API_KEY or not config.CARTESIA_VOICE_ID:
        raise HTTPException(503, "Set CARTESIA_API_KEY and CARTESIA_VOICE_ID in .env, then restart the server.")
    if len(tasks) >= 3:
        raise HTTPException(429, "Too many active games. Close another game first.")

    async def start(connection):
        async def guarded():
            try:
                await run_bot(connection, body.difficulty)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.error("Voice pipeline failed; verify provider configuration and connectivity.")
                connection.send_app_message({"type": "error", "error": "Voice connection failed. Check server logs and reconnect."})
            finally:
                await connection.disconnect()
        task = asyncio.create_task(guarded())
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    return await handler.handle_web_request(SmallWebRTCRequest(sdp=body.sdp, type=body.type), start)

app.mount("/", StaticFiles(directory=Path(__file__).resolve().parent.parent / "frontend", html=True), name="frontend")
