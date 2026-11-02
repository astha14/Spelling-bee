"""Exercise real local WebRTC and Pipecat lifecycle with fake cloud services."""
import asyncio
import json
from dataclasses import replace
from unittest.mock import Mock, AsyncMock
from aiortc import RTCPeerConnection, RTCConfiguration, RTCSessionDescription, AudioStreamTrack
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.frames.frames import TTSSpeakFrame, TranscriptionFrame, BotStartedSpeakingFrame, BotStoppedSpeakingFrame, VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from backend import bot

class FakeSpeech(FrameProcessor):
    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)

class FakeTTS(FakeSpeech):
    async def process_frame(self, frame, direction):
        await FrameProcessor.process_frame(self, frame, direction)
        if isinstance(frame, TTSSpeakFrame):
            await self.push_frame(BotStartedSpeakingFrame(), FrameDirection.UPSTREAM)
            await self.push_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
        else:
            await self.push_frame(frame, direction)


def test_real_webrtc_commands_and_shutdown(monkeypatch):
    monkeypatch.setattr(bot.config, 'COMPLETION', replace(bot.config.COMPLETION,
        minimum_silence=.03, completion_timeout=.06, maximum_timeout=.1,
        vad_stop=.01, stt_final_wait=.03))
    stt_instances = []
    def create_stt(**kwargs):
        stt = FakeSpeech()
        stt_instances.append(stt)
        return stt
    monkeypatch.setattr(bot, 'CartesiaSTTService', create_stt)
    fake_tts = Mock(side_effect=lambda **kwargs: FakeTTS())
    monkeypatch.setattr(bot, 'CartesiaTTSService', fake_tts)
    async def scenario():
        client = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        connection = SmallWebRTCConnection(ice_servers=[])
        channel = client.createDataChannel('chat')
        client.addTrack(AudioStreamTrack())
        states = []
        named = asyncio.Event()
        @channel.on('message')
        def message(raw):
            data = json.loads(raw)
            states.append(data)
            if data.get('name') == 'Alex':
                named.set()
        task = None
        try:
            await client.setLocalDescription(await client.createOffer())
            await connection.initialize(sdp=client.localDescription.sdp, type='offer')
            task = asyncio.create_task(bot.run_bot(connection, 'easy'))
            answer = connection.get_answer()
            await client.setRemoteDescription(RTCSessionDescription(sdp=answer['sdp'], type=answer['type']))
            async with asyncio.timeout(10):
                while channel.readyState != 'open' or not states or states[-1].get('speaking') is not False:
                    await asyncio.sleep(.05)
            await stt_instances[0].push_frame(TranscriptionFrame('Alex', 'player', ''))
            await asyncio.wait_for(named.wait(), 5)
            async with asyncio.timeout(5):
                while states[-1].get('speaking') is not False:
                    await asyncio.sleep(.01)
            assert states[-1]['phase'] == 'DIFFICULTY_SELECTION'
            await stt_instances[0].push_frame(TranscriptionFrame('easy mode', 'player', ''))
            async with asyncio.timeout(5):
                while states[-1].get('phase') != 'SPELLING' or states[-1].get('speaking') is not False:
                    await asyncio.sleep(.01)
            await stt_instances[0].push_frame(VADUserStartedSpeakingFrame())
            await asyncio.sleep(.01)
            await stt_instances[0].push_frame(TranscriptionFrame('Z Z', 'player', ''))
            await asyncio.sleep(.01)
            await stt_instances[0].push_frame(VADUserStoppedSpeakingFrame())
            async with asyncio.timeout(5):
                while states[-1].get('question') != 2:
                    await asyncio.sleep(.01)
            assert states[-1]['score'] == 0
            assert 'word' not in states[-1]
            assert all(s.get('type') == 'state' for s in states)
        finally:
            await client.close()
            await connection.disconnect()
            if task:
                await asyncio.wait_for(task, 10)
    asyncio.run(scenario())
