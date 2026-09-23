const {test} = require('node:test');
const assert = require('node:assert/strict');
const {createRequest} = require('../static/http.js');

test('network failures become actionable Russian messages', async () => {
  for (const message of ['Failed to fetch', 'Load failed', 'NetworkError']) {
    const request = createRequest(async () => { throw new TypeError(message); });
    await assert.rejects(request('/api/graph'), /Нет связи с локальным сервером.*повторите запрос/);
  }
});

test('timeout aborts fetch and offers retry', async () => {
  const request = createRequest((path, {signal}) => new Promise((resolve, reject) => {
    signal.addEventListener('abort', () => reject(new Error('aborted')), {once:true});
  }), 5);
  await assert.rejects(request('/api/ask'), /Время ожидания истекло/);
});

test('HTTP errors and malformed JSON remain distinct from network failure', async () => {
  const stale = createRequest(async () => ({ok:false, json:async () => ({detail:'Данные изменились.'})}));
  await assert.rejects(stale('/api/ask'), /Данные изменились/);
  const invalid = createRequest(async () => ({ok:true, json:async () => {throw new SyntaxError();}}));
  await assert.rejects(invalid('/api/graph'), /Сервер вернул некорректный ответ/);
});

test('request preserves POST body and exact string IDs', async () => {
  const gid='100000004015047101';
  const request=createRequest(async (path, options) => {
    assert.equal(path,'/api/ask'); assert.equal(options.method,'POST');
    assert.equal(JSON.parse(options.body).gid,gid);
    return {ok:true,json:async()=>({cited_gids:[gid]})};
  });
  assert.deepEqual(await request('/api/ask',{method:'POST',body:JSON.stringify({gid})}),{cited_gids:[gid]});
});
