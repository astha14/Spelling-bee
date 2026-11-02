/* Native browser WebRTC; no frontend build tools or API keys. */
const $ = id => document.getElementById(id);
let peer, channel, stream, active = false, heartbeat, retryTimer, retries = 0, manuallyClosed = false;
let hostSpeaking = false, userSpeaking = false;
function cleanup() {
  active = false;
  clearInterval(heartbeat);
  stream?.getTracks().forEach(track => track.stop());
  if (peer) { peer.onconnectionstatechange = null; peer.close(); }
  peer = channel = stream = null;
  $('audio').srcObject = null;
  $('start').disabled = false;
  $('mic').textContent = 'Off';
  $('connection').textContent = 'Offline';
}
// Transport messages are not all game updates. Validate before touching the DOM.
function receiveServerMessage(raw) {
  if (typeof raw !== 'string') return;
  let data;
  try {
    data = JSON.parse(raw);
  } catch {
    console.warn('Ignored a non-JSON data-channel message.');
    return;
  }
  if (!data || typeof data !== 'object' || Array.isArray(data)) return;
  if (data.type !== 'state' && data.type !== 'error') return;
  if (data.type === 'state') {
    const numbers = ['question', 'score', 'total', 'percentage', 'answered'];
    if (!numbers.every(key => typeof data[key] === 'number' && Number.isFinite(data[key])) ||
        typeof data.phase !== 'string' || typeof data.finished !== 'boolean' ||
        (data.name !== undefined && typeof data.name !== 'string')) {
      $('error').textContent = 'Game update was incomplete. Reconnect the audio session.';
      return;
    }
  }
  try {
    state(data);
  } catch (error) {
    console.error('Unable to render the game update:', error);
    $('error').textContent = 'Page update failed. Refresh this tab to load the latest version.';
  }
}
function state(data) {
  if (typeof data.error === 'string') $('error').textContent = data.error;
  if (data.type !== 'state') return;
  $('round').textContent = `${data.question} / ${data.total}`;
  $('score').textContent = `${data.score} points`;
  if (typeof data.speaking === 'boolean') hostSpeaking = data.speaking;
  if (typeof data.user_speaking === 'boolean') userSpeaking = data.user_speaking;
  $('mic').textContent = userSpeaking ? 'Hearing you' : hostSpeaking ? 'Host speaking' : 'Listening';
  // Keep capture enabled for command interruptions; browser AEC removes playback echo.
  const prompts = {
    WELCOME: 'Say your name, or say start game.',
    DIFFICULTY_SELECTION: 'Say easy mode, medium mode, or hard mode.',
    SPELLING: 'Spell aloud. After a few seconds of silence, your answer is checked automatically.',
    CONFIRMING_ANSWER: 'Say confirm to grade, or let me try again.',
    GAME_OVER: 'Say play again to start another game.'
  };
  $('status').textContent = data.paused ? 'Contest paused. Say resume when ready.' :
    data.notice || prompts[data.phase] || 'Listen to the host.';
  $('results').hidden = !data.finished;
  if (data.finished) {
    $('result-text').textContent = `${data.name || 'Player'}, you earned ${data.score} / ${data.total * 10} points (${data.percentage}%). ${data.answered} of ${data.total} words answered.`;
  }
}
async function iceComplete(pc) {
  if (pc.iceGatheringState === 'complete') return;
  await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error('Audio negotiation timed out. Please retry.')), 12000);
    pc.addEventListener('icegatheringstatechange', () => {
      if (pc.iceGatheringState === 'complete') { clearTimeout(timeout); resolve(); }
    });
  });
}
async function connect() {
  cleanup();
  hostSpeaking = userSpeaking = false;
  $('start').disabled = true;
  $('error').textContent = ''; $('results').hidden = true;
  $('status').textContent = 'Connecting your microphone…';
  try {
    const health = await fetch('/api/health').then(r => r.json());
    if (!health.voice_configured) throw new Error('Add your Cartesia API key and voice ID to .env, then restart the Python server.');
    stream = await navigator.mediaDevices.getUserMedia({audio: {echoCancellation:true, noiseSuppression:true, autoGainControl:true}});
    peer = new RTCPeerConnection({iceServers:[]});
    const pc = peer;
    pc.ontrack = event => {
      $('audio').srcObject = new MediaStream([event.track]);
      $('audio').play().catch(() => { $('error').textContent = 'Audio playback blocked. Click the page and try Start again.'; });
    };
    stream.getTracks().forEach(track => pc.addTrack(track, stream));
    channel = pc.createDataChannel('chat');
    channel.onmessage = event => { if (peer === pc) receiveServerMessage(event.data); };
    channel.onopen = () => {
      heartbeat = setInterval(() => { if (channel?.readyState === 'open') channel.send('ping'); }, 1000);
      active = true; $('connection').textContent = 'Connected'; $('mic').textContent = 'Listening';

    };
    pc.onconnectionstatechange = () => {
      if (['failed','disconnected','closed'].includes(pc.connectionState)) {
        cleanup();
        if (!manuallyClosed && retries < 2) {
          retries++;
          $('error').textContent = 'Audio lost. Reconnecting into a new game…';
          retryTimer = setTimeout(connect, 1500);
        } else {
          $('error').textContent = 'Audio disconnected. Start a new audio session to reconnect.';
        }
      }
    };
    await pc.setLocalDescription(await pc.createOffer());
    await iceComplete(pc);
    const response = await fetch('/api/offer', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({sdp:pc.localDescription.sdp,type:'offer'})});
    const answer = await response.json();
    if (!response.ok) throw new Error(answer.detail || 'Unable to connect.');
    await pc.setRemoteDescription({sdp:answer.sdp,type:answer.type});
    setTimeout(() => {
      if (peer === pc && !active) { $('error').textContent = 'Connection timed out. Check server logs and try again.'; cleanup(); }
    }, 15000);
  } catch (error) {
    $('error').textContent = error.name === 'NotAllowedError' ? 'Microphone permission was denied. Allow microphone access for localhost in your browser, then try again.' : error.message;
    cleanup();
  }
};
$('start').onclick = () => { manuallyClosed = false; retries = 0; clearTimeout(retryTimer); connect(); };
$('disconnect').onclick = () => { manuallyClosed = true; clearTimeout(retryTimer); cleanup(); };
window.addEventListener('beforeunload', () => { manuallyClosed = true; clearTimeout(retryTimer); cleanup(); });
