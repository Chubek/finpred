const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../yieldcraft_mcp/ui/editor.html'), 'utf8');
const script = html.match(/<script>([\s\S]+)<\/script>/)[1];
const rpc = message => ({jsonrpc: '2.0', ...message});
const handshake = rpc({
  id: 1,
  result: {protocolVersion: '2026-01-26', hostCapabilities: {serverTools: {}}},
});

function editor({framed = true} = {}) {
  const sent = [], elements = new Map(), timers = new Set();
  const element = () => ({append() {}, replaceChildren() {}, addEventListener() {}});
  const document = {
    documentElement: {scrollHeight: 100},
    createElement: element,
    createTextNode() {},
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, {...element(), value: '', disabled: id === 'validate'});
      return elements.get(id);
    },
  };
  const window = {addEventListener(event, handler) { this[event] = handler; }};
  window.parent = framed ? {postMessage(message, origin) { sent.push({message, origin}); }} : window;
  vm.runInNewContext(script, {
    document, window,
    setTimeout(callback) { timers.add(callback); return callback; },
    clearTimeout(callback) { timers.delete(callback); },
  });
  const deliver = (origin, data, source = window.parent) => window.message({origin, data, source});
  return {sent, timers, deliver, input: elements.get('source'), validate: elements.get('validate')};
}

test('standalone editor does not initiate a host handshake', () => {
  const app = editor({framed: false});
  assert.deepEqual(app.sent, []);
  assert.equal(app.validate.disabled, true);
});

test('opaque parent cannot receive strategy source and falls back on timeout', async () => {
  const app = editor();
  app.input.value = 'private draft';
  app.deliver('null', handshake);
  await Promise.resolve();
  assert.equal(app.validate.disabled, true);
  const [expire] = app.timers;
  expire();
  await app.validate.onclick();
  assert.deepEqual(app.sent.map(({message, origin}) => [message.method, origin]), [['ui/initialize', '*']]);
  assert.doesNotMatch(JSON.stringify(app.sent), /private draft/);
});

test('only the pinned parent origin receives strategy validation requests', async () => {
  const app = editor();
  const host = 'https://host.example';
  app.deliver('https://other.example', handshake, {});
  app.deliver(host, handshake);
  await Promise.resolve();
  assert.equal(app.validate.disabled, false);
  app.input.value = 'private draft';
  app.deliver('https://other.example', rpc({
    method: 'ui/notifications/tool-input',
    params: {arguments: {source: 'wrong origin'}},
  }));
  const validation = app.validate.onclick();
  assert.equal(app.sent.at(-1).origin, host);
  assert.equal(app.sent.at(-1).message.params.arguments.source, 'private draft');
  assert.equal(app.sent.filter(({origin}) => origin === '*').length, 1);
  app.deliver(host, rpc({id: app.sent.at(-1).message.id, result: {structuredContent: {admitted: false}}}));
  await validation;
});
