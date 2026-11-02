# Fully voice-controlled Spelling Bee

After microphone permission and **Start audio session**, all gameplay is spoken.
The only other button disconnects audio. The host asks your name and difficulty,
speaks a word, collects letters, detects completion after silence, grades it in Python, and
moves to the next word automatically. Say **play again** after the final score;
the microphone stays connected.

## Run locally on Linux

In the VS Code terminal:

```bash
cd /home/divyansh/Documents/spelling-bee
source .venv/bin/activate
python -m pip install -r requirements.txt -c requirements.lock.txt
# Only if you have not created .env yet:
cp -n .env.example .env
```

Keep your existing `.env`. Set `CARTESIA_API_KEY` and `CARTESIA_VOICE_ID` for an
English voice. Grading uses immediate scripted feedback. Optional
`OPENROUTER_API_KEY` and `OPENROUTER_MODEL` enable short conversational replies
and intent interpretation for questions; letters and grading never call the LLM.
Cartesia and optional OpenRouter usage may incur charges.

```bash
python -m pytest -q
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Open **http://localhost:8000**, click **Start audio session**, and allow microphone
access. Use headphones for reliable interruption handling. Restart Python after
changing `.env`. Stop the server with Ctrl+C. If port 8000 is occupied, use
`--port 8001` and open the matching URL.

In VS Code, select `.venv/bin/python` through **Python: Select Interpreter**.
The project uses Python 3.12 because the pinned audio stack supports it. For a
fresh checkout, first run `uv venv --python 3.12`, activate it, then run
`python -m ensurepip` before the install command above. If downloads stall on
this laptop's IPv6 route, `python scripts/install_ipv4.py` runs pip using IPv4
without changing system networking.

## Try this conversation

```text
Host: Welcome! What is your name? Or say start game.
You: My name is Alex.
Host: Hi, Alex! Choose easy mode, medium mode, or hard mode.
You: Easy mode.
Host: [speaks a word; spelling stays hidden]
You: [spell individual letters, with pauses if needed]
You: [stop speaking; no completion phrase needed]
Host: [after a base 2–2.5 seconds of silence, feedback and the next word automatically]
```

The ten predefined words in each difficulty are shuffled without repetition.
Each correct answer earns 10 points; incorrect answers earn zero. End Game
reports points against the full ten-word game, including how many were answered.

| Say | What happens |
| --- | --- |
| Start game | Skips the optional name and asks for difficulty |
| Easy mode / Medium mode / Hard mode | Selects difficulty before the first word |
| Repeat the word | Repeats the current word without clearing letters |
| Give me a hint / What does it mean? | Speaks the definition |
| Use it in a sentence | Speaks a prepared example sentence |
| Done / I'm done / Finished / That's my answer | Optional legacy shortcut: requests answer confirmation; not needed for automatic completion |
| Confirm / Yes | Grades a manually requested read-back answer; not needed in the automatic flow |
| Let me try again / Retry / No | Clears the answer without grading |
| Undo / Delete last letter | Removes one letter |
| Replace last letter with B | Changes the last letter and returns to spelling |
| What's my score? | Speaks the current score |
| Next word | Explains that the current answer must be graded first; progression is automatic |
| End game | Announces results and keeps audio open for replay |
| Play again | Resets a finished game and asks for difficulty |

Spell `A, B, C`, say letter names such as `bee, dee, em`, or use phonetics:
`A for Apple`, `B for Ball`, `D as in Dog`, or NATO words such as `bravo`,
`delta`, `papa`, `tango`, `mike`, and `november`.

Contradictory phrases like `B for dog` request clarification; the app never guesses
using the target word. Repeated letters remain repeated. Unknown sentences do
not become spelling attempts. Whole lowercase words are rejected because they
do not prove the player actually spelled the word. Clear uppercase compact STT
sequences are accepted. No target-based autocorrection is performed.

## How the code works

```text
Browser microphone with echo cancellation
  → SmallWebRTC transport
  → Silero VAD
  → Smart Turn audio adapter (background local inference)
  → Cartesia streaming STT
  → GameProcessor → spelling parser → Host → Game
  → Cartesia TTS
  → SmallWebRTC transport → browser speaker
```

A Pipecat **frame** is an audio chunk, recognized text, speech activity event, or
instruction to speak. Silero detects speech start/stop and drives the visual
status. Only final Cartesia STT segments add letters; revised interim hypotheses
mark recognition as pending but never append to the answer.

The contest state machine is preserved. The new per-attempt completion controller
adds `WAITING_FOR_WORD → LISTENING → POSSIBLY_COMPLETE → VALIDATING → FEEDBACK`.
It waits for host playback to finish before listening. A fresh VAD speech start
is required before collecting letters, which also rejects late transcripts after
feedback when no new player speech has begun. Existing letters retained after a
hint or correction can still complete automatically: a fresh full silence window
starts after the host response, so playback never consumes the opportunity to
continue spelling.

Smart Turn V3 analyzes a bounded audio snapshot in the background. Its prediction
is only a hint: a positive result uses **2 seconds** of silence; an incomplete,
missing or failed prediction uses **2.5 seconds**. Observed pauses between
segments can extend either window: longest observed pause plus 0.6 seconds,
with that adaptive allowance capped at 4 seconds. Pace is retained across words
within one session. The first unexpectedly long pause can still end an attempt. The **1-second minimum** is a
lower bound, not a fast-submission path. Silence is measured from the end of
speech, accounting for the VAD stop delay. Neither answer correctness nor expected
word length affects this policy.

One cancellable asyncio timer owns completion. Resumed speech cancels it and
invalidates old turn predictions. The timer checks the attempt ID and generation
again under the same lock used by speech events before claiming an answer exactly
once. Each new word or retry gets a new attempt ID. VAD stops and Smart Turn
predictions cannot independently submit.

If recognition is still pending, the controller allows up to **2.5 additional
seconds** beyond the applicable silence threshold (4.5 seconds on the base positive
Smart Turn path, 5 seconds on the base fallback path; longer with adaptive pacing). A final result arriving in that
grace period can be graded immediately if silence is already sufficient. If a
final never arrives, the host requests a retry instead of grading an incomplete
prefix. Empty attempts never receive a grade.

Automatic completion calls the same Python validation/scoring function as the
existing manual confirmation path, then speaks feedback and the next word.
The optional “done” and confirmation commands remain available for compatibility,
but **normal gameplay needs neither “done” nor “confirm.”**

During host playback, only a recognized command such as repeat, hint, sentence,
score, retry, undo, or end can interrupt, and it requires VAD evidence of speech.
The processor broadcasts Pipecat's interruption frame to stop queued speech.
Ordinary spelling during host playback and late transcripts from overlapping
speech are ignored. Wait until the host stops before spelling.
Browser acoustic echo cancellation reduces echo; headphones remain recommended.
No software-only test can guarantee perfect acoustic separation on every laptop.

| File | Responsibility |
| --- | --- |
| `backend/main.py` | FastAPI, static page, WebRTC offers, session lifecycle |
| `backend/bot.py` | VAD, STT/TTS, frame processing, command interruptions, status |
| `backend/completion.py` | Per-attempt state, silence timer, pending-STT grace and exact-once claim |
| `backend/smart_turn.py` | Bounded audio snapshots and background Smart Turn signals |
| `backend/host.py` | Explicit conversation state machine and spoken commands |
| `backend/spelling_parser.py` | Letter aliases, phonetics, completion and corrections |
| `backend/game_logic.py` | Deterministic comparison, word selection, score |
| `backend/word_bank.py` | Words, definitions and example sentences |
| `backend/conversation.py`, `backend/host_prompt.py` | Bounded optional conversational routing and host personality |
| `backend/encouragement.py` | Unused optional OpenRouter helper; not called during gameplay |
| `backend/config.py` | Server-only environment variables |
| `frontend/app.js` | WebRTC audio, status, automatic reconnect attempts |
| `frontend/index.html`, `frontend/style.css` | Responsive listening/speaking display |
| `tests/` | Parsing, game rules, automatic completion, timing races, complete voice flows, interruptions, WebRTC |

## Privacy and failure behavior

Target words, host transcripts, definitions and sentences never enter frontend
JSON. Only audio carries the prompt. Recognized letters stay on the backend and are not displayed or sent in page state. Pipecat RTVI transcript emission is disabled. Pipecat library logs are
also disabled because even warning messages can include TTS text. Application
errors use generic messages without transcripts, answers or credentials.

Spelling and scoring make no LLM requests. Optional conversational requests send
the player's utterance and name to OpenRouter, without the backend word, buffer,
score or result. Python handles factual commands and validates all grades.
No audio recordings are saved by this application.

Microphone permission errors appear on the page. A dropped connection triggers
up to two automatic reconnect attempts into a **new game**; in-memory game state
is not resumed. If those fail, use Start audio session again. A 30-second silence
notice reminds a player who has not provided an answer. The separate completion timer grades nonempty attempts after sufficient silence. Idle sessions close after five minutes.
A finished game remains connected so you can say play again.

This is a single-player localhost MVP. It has no accounts or persistent scores.
Remote deployment needs HTTPS and appropriate WebRTC networking; no TURN server
is configured here. Word corrections support last-letter replacement, undo and
full retry; arbitrary edits such as “replace the third letter” are not supported.

## Testing

```bash
python -m pytest -q
python -m pip check
node --check frontend/app.js
node --test tests/frontend.test.cjs
```

The automated suite has **188 passing Python tests** and **4 passing browser-script tests**, including a ten-round automatically
graded game and replay, phonetic spelling, ambiguous input, corrections,
interruption guards, delayed/revised STT, timer races and stale callbacks, API
validation, bundled Smart Turn inference, and a real local WebRTC session with
simulated cloud STT/TTS that progresses without a completion phrase.
It does not contact paid services or require your keys.

For live acceptance:

1. Start audio, say your name and difficulty; use no gameplay clicks.
2. Spell with pauses of 0.5–2 seconds and repeated letters, then stay silent. Verify automatic feedback.
3. Try `B for Ball`, `D for Dog` and a deliberately conflicting phonetic phrase.
4. Request a repeat while the host is talking. Verify letters and score stay unchanged.
5. Retry, undo and replace the last letter; then stop speaking and verify automatic grading.
6. Request a hint, sentence and score using speech.
7. Finish ten rounds; say play again and select a different difficulty.
8. Test microphone denial and a dropped connection.

Live provider accuracy, speaker echo and physical microphone behavior require
this checklist on your laptop. Automated tests cannot establish recognition
accuracy for your accent. This update was tested without making live provider calls.

## Compatible APIs

Pipecat remains pinned to **1.14.0**. The installed sources/signatures were checked
for `LocalSmartTurnAnalyzerV3`, `SmartTurnParams`, `VADProcessor`,
`SileroVADAnalyzer`, `VADParams`, `broadcast_interruption`,
`PipelineWorker`, `WorkerRunner`, Cartesia services and SmallWebRTC. No dependency
upgrade was necessary; Silero's ONNX runtime is already installed.

- [Pipecat tagged source](https://github.com/pipecat-ai/pipecat/tree/v1.14.0)
- [Cartesia STT integration](https://docs.pipecat.ai/api-reference/server/services/stt/cartesia)
- [Cartesia TTS integration](https://docs.pipecat.ai/api-reference/server/services/tts/cartesia)
- [OpenRouter API](https://openrouter.ai/docs/api_reference/overview)


## Stage 1 completion configuration

These values have defaults in `backend/config.py`. Copy whichever settings you
want into your existing `.env`; do not overwrite your API keys. Restart the server
after changing settings. No new dependencies or provider services were added.

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `VAD_CONFIDENCE` | `0.7` | Silero confidence threshold; lower detects quieter/less certain speech but may detect more noise |
| `VAD_START_SECS` | `0.08` | Speech duration before VAD reports a start |
| `VAD_STOP_SECS` | `0.2` | Silence duration before VAD reports a stop |
| `SMART_TURN_ENABLED` | `true` | Enable the installed local V3 analyzer; false uses the silence fallback |
| `SMART_TURN_CPU_COUNT` | `1` | ONNX inference CPU threads |
| `SMART_TURN_AUDIO_SECS` | `8` | Maximum recent audio supplied to the analyzer |
| `SPELLING_MIN_SILENCE_SECS` | `1.0` | Lower bound on either completion timeout |
| `SPELLING_COMPLETION_SECS` | `2.0` | Silence required with a positive Smart Turn result |
| `SPELLING_MAX_COMPLETION_SECS` | `2.5` | Silence fallback if Smart Turn is incomplete, absent or unavailable |
| `SPELLING_PAUSE_MARGIN_SECS` | `0.6` | Extra silence beyond the longest observed pause |
| `SPELLING_ADAPTIVE_MAX_SECS` | `4.0` | Cap on the learned pause allowance; does not reduce configured base timeouts |
| `STT_FINAL_WAIT_SECS` | `2.5` | Extra bounded grace for a pending final transcript |
| `SPELLING_DEBUG` | `false` | Log VAD, prediction, timer, recognized-letter and validation events |

For players who pause longer, try `SPELLING_COMPLETION_SECS=3.5` and
`SPELLING_MAX_COMPLETION_SECS=5.0`. If finals arrive late, try
`STT_FINAL_WAIT_SECS=3.0`. Keep minimum <= default <= maximum. Do not lower the
minimum to compensate for slow transcription: that increases premature grading.
The fallback timeout is a base silence threshold; adaptive pacing can extend it.
Pending-STT grace and provider TTS latency are additional.

With `SPELLING_DEBUG=true`, terminal logs include player-recognized letters and
attempt IDs, not target words, host prompts, or credentials. There are no new LLM
requests for completion, no token tagging, and no Stage 2 implementation.
Result feedback goes directly to Cartesia TTS without an OpenRouter request.

### Stage 1 limitations

- A mid-word pause longer than the selected threshold can submit a partial answer.
  Smart Turn is trained for conversation and does not reliably know when spelling
  is complete. Increase the timeouts for slower spellers.
- VAD and STT can miss speech or mishear letters; automatic completion does not
  establish recognition accuracy. Use the live checklist to tune your microphone
  and accent. No live Cartesia microphone session was performed for this update.
- Cartesia finals do not carry this app's attempt ID. The app waits for pending
  finals and rejects transcripts during playback and before fresh speech, but an
  exceptionally delayed old final arriving after new speech has started cannot
  always be distinguished from the new attempt. Reconnect/retry if the provider
  is severely delayed.
- Repeated partial updates are ignored, not appended. Separate final segments are
  appended as delivered; identical final letters may be intentional repetitions
  and must not be deduplicated by text alone.
- Provider STT and TTS still contribute latency. The extra OpenRouter feedback
  request has been removed. Smart Turn inference runs off the audio event loop.


### Name and spelling recognition fixes

Introductions such as “Hi, my name is Alex,” “I'm Alex,” and “I am Alex” produce
“Hi, Alex!” The recognized-letter panel has been removed; score, round and audio
status remain visible. Letter buffers are no longer included in browser state.

A rejected STT segment no longer starts a spoken clarification while the player
is still spelling. The host continues listening, keeps subsequent recognized
letters, and requests a full retry after silence if any segment was unclear.
It never grades a buffer with a known missing segment. Saying “let me try again”
clears both the letters and the uncertainty flag.

The parser now accepts additional letter-name spellings such as “be,” “eff,”
“ell,” and “tea,” repeated-letter expressions such as “double P,” and punctuation
on uppercase sequences such as “CAT.” It never uses the expected word to repair
recognition. The shorter VAD start threshold helps detect brief letter sounds;
the longer final-result grace period allows delayed Cartesia finals to arrive.
If recognition still fails, `SPELLING_DEBUG=true` also records incoming final
transcripts during spelling and reasons for rejecting playback-overlapping or
pre-VAD transcripts. These diagnostics stay in the local terminal, not the page.


### Browser message and feedback fixes

The browser distinguishes game updates from transport messages and reports
rendering failures separately from malformed data. Frontend files are served
without caching, with versioned asset URLs to avoid mismatched scripts and HTML.
After updating, restart the server and refresh the tab with Ctrl+Shift+R.

Delayed final transcripts queued within the same attempt survive a new VAD speech
segment; bot playback and new attempts still invalidate queued transcripts.
This fixes a race that could discard letters across pauses, but does not recover
letters that Cartesia never transcribes. Base silence defaults are now 2 seconds
with Smart Turn completion and 2.5 seconds on fallback, extended for observed
slower pacing (your `.env` may override them). Feedback no longer waits for an extra LLM request, and the
practice message has been removed. Live microphone accuracy still needs testing.


### Paused spelling and measured latency (2026-10-31)

Inspection confirmed Pipecat 1.14.0, Cartesia `ink-whisper` STT and Cartesia TTS,
Silero VAD (0.08-second start, 0.2-second stop), and local Smart Turn V3.
No provider, model, dependency, scoring rule or LLM completion logic was changed.
The installed STT adapter sends `finalize` at each VAD stop. Short speech segments
therefore reach STT separately; the host must accumulate their final transcripts.
There is no supported spelling-mode setting in this installed adapter. Its
keyterm setting is for other Cartesia models, so no unsupported setting was added.
See [Cartesia manual streaming protocol](https://docs.cartesia.ai/api-reference/stt/websocket).

Confirmed application issues and fixes:

- The parser rejected mixed uppercase chunks such as `E LE P H ANT`; any rejected
  segment set a persistent ambiguity flag and forced a retry even if later
  letters were valid. These explicit letter chunks now retain their exact letters.
  Punctuation-only chunks no longer mark the spelling ambiguous. Unknown words
  still require clarification; they are never silently omitted or corrected.
- One host letter buffer persists across VAD and Smart Turn boundaries. Only
  final transcripts append; revised partials do not. The same Pipecat final frame
  delivered twice is ignored. Separate identical final frames are preserved so
  that two spoken P letters in APPLE remain two letters. Cartesia's request ID
  alone does not identify a unique chunk, so it is not used for deduplication.
  Provider retransmissions with new frame identities and no stable chunk ID
  cannot safely be distinguished from intentional repetitions.
- The old four-second fallback was still present after removing the LLM request.
  It is now 2.5 seconds, with a 2-second positive Smart Turn path. Deadlines remain
  anchored to speech end, not prediction arrival; delayed finals do not start a
  second full silence window. Pending recognition still gets bounded grace.

Run the reproducible local benchmark:

```bash
python -m scripts.measure_completion
```

Measured using real asyncio timers with synthetic speech events and a final
transcript already available; no audio, cloud STT, Smart Turn inference or TTS:

| Path | Before: speech end to submission | After |
| --- | ---: | ---: |
| Smart Turn complete | 2501.6 ms | 2002.7 ms |
| Fallback | 4002.3 ms | 2501.5 ms |

The application silence timer dominates this controlled benchmark. The dominant
stage in a live microphone session is **not yet measured**; these numbers are
not claims about audible feedback or acoustic recognition accuracy.

To measure a live session, restart with diagnostics enabled:

```bash
SPELLING_DEBUG=true python -m uvicorn backend.main:app --reload
```

Every diagnostic includes a monotonic `t=` timestamp and attempt ID. Events cover
VAD start/stop (including estimated last speech time), Smart Turn prediction,
provider partial/final arrivals (including empty responses), accumulator changes,
timer start/cancel/expiry, submission, validation, TTS request, synthesis start,
first generated TTS audio and transport audio start. Feedback milestones include
milliseconds since speech end and submission. Transport start is a server-side
proxy, **not proof of browser audibility**; browser buffering/device latency is
not measured. Diagnostics stay in the server terminal and can include recognized
player text; target words and synthesized prompts are not logged.

`backend/stt.py` observes raw responses, including empty transcripts the upstream
adapter does not forward. `backend/latency.py` observes TTS frames without buffering.
Both preserve the installed services' behavior. The new tests use response
fixtures for A, B, C, E, G, P, T and Z; they do not establish how accurately Cartesia
hears a real microphone. Live checks should spell APPLE continuously, as AP / PL /
E, and as A / P / P / L / E, then try an incorrect spelling and a delayed final.

Start with the supplied 2.0 / 2.5-second thresholds. For first pauses near two
seconds, use 2.5 / 3.0 seconds; learned pacing cannot protect a pause that already
exceeded the initial deadline. Longer pause tolerance necessarily delays final
feedback. If logs show missing letters at the provider, use `P for papa` to
clarify; do not shorten timers to compensate for missing STT results. A model
comparison would be a separate measured change, not an automatic provider switch.


### Conversational host and recognition diagnostics

The existing Pipecat 1.14.0 pipeline now includes a passive input-audio probe:
WebRTC → audio diagnostics → Silero VAD → Smart Turn → Cartesia STT →
deterministic game/conversation router → Cartesia TTS → output diagnostics → WebRTC.
`SPELLING_DEBUG=true` adds server audio sample counts/RMS, bytes reaching STT,
and bytes observed while the STT connection is disconnected. No audio is stored.

How to locate a live failure:

1. No `AUDIO received`: investigate browser permission, device or WebRTC delivery.
2. Audio arrives but RMS is near zero: check the selected microphone/input level.
3. Audible-level input but no VAD starts: investigate VAD sensitivity with actual
   recordings; energy alone cannot distinguish speech from background noise.
4. STT input arrives, but disconnected bytes or empty/missing provider finals appear:
   investigate connection/provider transcription. A final transcript log is needed
   to distinguish omitted letters from parser rejection.
5. Correct final text but wrong accumulated text: parser/aggregation problem.
6. Correct buffer but early submission: completion threshold issue; compare timestamps.
7. Correct submitted text but wrong score: deterministic validation issue.

A confirmed application routing issue was that ordinary conversation was treated
as an unknown spelling segment and permanently marked the attempt unclear. Known
conversations now preserve the buffer without setting that flag. This does not
establish that every missed live letter had this cause. No live acoustic accuracy
measurements were possible during these changes.

Try these voice requests without restarting the game:

- “Can you repeat the word?” / “Can you use it in a sentence?”
- “What is the definition?” / “What's my score?” / “What are the rules?”
- “I'm nervous” / “This sounds difficult” / “Tell me a joke”
- “Pause the contest” / “Resume the contest”
- “Can we talk about bees?” (optional OpenRouter conversation)

The host introduces the rules, remembers the contestant's name, varies feedback,
and celebrates correct streaks. Score and correctness always come from Python.
Interaction labels distinguish waiting, spelling, conversation and pause without
replacing the contest state machine. Pausing keeps letters and stops completion;
resuming waits for fresh speech. Unknown short fragments still require clarification.
Single letters, phonetic spelling and known commands never call OpenRouter.

Conversational model calls run in a cancellable task outside the audio lock, with
an overall three-second timeout. New speech cancels a pending reply. Commands such
as end/pause also cancel it; late replies cannot affect a newer attempt. Responses
are short JSON objects: Python handles factual intents, and only bounded casual
text is spoken directly. The dedicated personality prompt prohibits grading or
answer disclosure; code rejects unsupported intents, target-word text and obvious
scoring/spelling claims. Arbitrary conversational quality still depends on the
configured model. No model result can change letters, scores or grading.
LLM JSON is validated before speech rather than streamed unvalidated into TTS;
Cartesia TTS continues to stream audio. With no key or a failed/invalid response,
the host asks a short clarification and preserves the game.

**Pause tests:** synthetic final transcripts, worst-case positive Smart Turn at
every pause, including 0.08 seconds of VAD-start delay:

| Between-letter pause | Defaults 2.0 / 2.5 seconds | Slow profile 3.5 / 4.0 seconds |
| --- | --- | --- |
| 0.5 seconds | Complete FROG retained | Complete FROG retained |
| 1 second | Complete FROG retained | Complete FROG retained |
| 2 seconds | First pause can submit early | Complete FROG retained |
| 3 seconds | First pause can submit early | Complete FROG retained |

For slow spelling set `SPELLING_COMPLETION_SECS=3.5` and
`SPELLING_MAX_COMPLETION_SECS=4.0` in `.env`, then restart. This necessarily makes
final feedback slower. Alternatively say “pause” for thinking time. No acoustic
turn detector can guarantee distinguishing an unannounced thinking pause from
finishing. Adaptive pacing helps only after observing pauses within the initial
window. This update does not silently increase your existing thresholds.

The repeat local real-clock benchmark measured 2501.1 → 2002.2 ms on the positive
Smart Turn path, and 4001.8 → 2501.0 ms on fallback. These compare historical versus
current timer settings; the conversational feature itself does not reduce those
timers or add an LLM call to grading. Live STT/LLM/TTS and browser audibility remain
unmeasured. Use the timestamped diagnostic events to measure your session.

**STT limits:** the response fixtures cover A/B/C/D/E/F/G/P/T/V/Z and M/N/J/S;
they verify parser and adapter behavior, not microphone recognition. Cartesia's
installed default remains `ink-whisper`. The smallest provider-compatible
comparison is an opt-in `CARTESIA_STT_MODEL=ink-2` test with the same recordings.
This option was not activated or acoustically benchmarked here. Cartesia documents
[keyterm prompting](https://docs.cartesia.ai/use-the-api/stt/keyterms) for important
terms; it is not a proven isolated-letter spelling mode. Do not bias STT with the
current target word. Phonetic forms such as “B for bravo” remain available for
confusable letters. No provider was replaced and no new dependency was added.

Changed files for this update: `backend/bot.py`, `host.py`, `spelling_parser.py`,
`conversation.py`, `host_prompt.py`, `latency.py`, `stt.py`, `config.py`,
`frontend/app.js`, `.env.example`, this README, and the conversation, completion
and diagnostics tests. Tests cover pauses, corrections, partial revisions,
repetitions, late events, conversation preservation, cancellation, paused input,
model boundaries/fallbacks, feedback and complete gameplay.
