export async function request(path, { method = 'GET', body, signal } = {}) {
  let response;
  try {
    response = await fetch(path, {
      method, signal,
      ...(body instanceof FormData ? { body } : body === undefined ? {} : {
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      }),
    });
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    throw new Error('Cannot reach Stackplan. Check your connection and that the helper API is running.');
  }
  let data;
  try { data = await response.json(); } catch { throw new Error('The helper returned an unreadable response. Please retry.'); }
  if (!response.ok) throw new Error(data.errors?.join(' ') || `Request failed (${response.status}).`);
  return data;
}
