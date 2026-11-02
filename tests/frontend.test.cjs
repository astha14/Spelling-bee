const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
function page() {
  const html = fs.readFileSync('frontend/index.html', 'utf8');
  const elements = Object.fromEntries([...html.matchAll(/id="([^"]+)"/g)].map(m => [m[1], {textContent: ''}]));
  const context = vm.createContext({document: {getElementById: id => elements[id]}, window: {addEventListener() {}}, console: {warn() {}, error() {}}});
  vm.runInContext(fs.readFileSync('frontend/app.js', 'utf8'), context);
  return {elements, receive: data => context.receiveServerMessage(data)};
}
const update = {type: 'state', question: 1, score: 10, total: 10, percentage: 10, answered: 1, phase: 'SPELLING', finished: false};
test('valid game updates render without a recognized-letters panel', () => {
  const {elements, receive} = page();
  assert.equal(elements.letters, undefined);
  receive(JSON.stringify(update));
  assert.equal(elements.score.textContent, '10 points');
  assert.equal(elements.error.textContent, '');
  receive(JSON.stringify({...update, phase: 'GAME_OVER', finished: true, name: 'Alex'}));
  assert.equal(elements.results.hidden, false);
  assert.match(elements['result-text'].textContent, /Alex, you earned/);
});
test('non-game transport messages do not produce misleading errors', () => {
  const {elements, receive} = page();
  for (const raw of ['ping', 'null', '[]', '{}', '{"type":"signalling"}', new Uint8Array()]) receive(raw);
  assert.equal(elements.error.textContent, '');
});
test('service errors and incomplete game updates remain visible', () => {
  const {elements, receive} = page();
  receive(JSON.stringify({type: 'error', error: 'Voice service unavailable'}));
  assert.equal(elements.error.textContent, 'Voice service unavailable');
  receive(JSON.stringify({type: 'state'}));
  assert.match(elements.error.textContent, /incomplete/);
});
test('rendering failures are distinguished from message parsing', () => {
  const {elements, receive} = page();
  delete elements.score;
  receive(JSON.stringify(update));
  assert.match(elements.error.textContent, /Refresh this tab/);
});
