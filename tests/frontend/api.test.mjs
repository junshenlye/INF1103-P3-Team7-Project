import test from 'node:test';
import assert from 'node:assert/strict';
import { request } from '../../frontend/static/api.js';

test('transport preserves partial-success payloads and errors', async () => {
  const original = global.fetch;
  try {
    global.fetch = async () => Response.json({ payload: { modules: [{ module_title: 'A' }] }, errors: ['B failed'] });
    const result = await request('/api/projects/1/process');
    assert.equal(result.payload.modules.length, 1);
    assert.deepEqual(result.errors, ['B failed']);
  } finally { global.fetch = original; }
});
test('HTTP errors expose helper error messages', async () => {
  const original = global.fetch;
  try {
    global.fetch = async () => Response.json({ payload: null, errors: ['Project not found.'] }, { status: 404 });
    await assert.rejects(request('/api/projects/1'), /Project not found/);
  } finally { global.fetch = original; }
});
test('uploads preserve multipart boundaries', async () => {
  const original = global.fetch;
  try {
    let sent;
    global.fetch = async (_, options) => { sent = options; return Response.json({ payload: {}, errors: [] }); };
    const upload = new FormData(); upload.append('modules', '[]');
    await request('/api/projects/1/process', { method: 'POST', body: upload });
    assert.equal(sent.body, upload); assert.equal(sent.headers, undefined);
  } finally { global.fetch = original; }
});
