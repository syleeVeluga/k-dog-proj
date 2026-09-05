export async function api<T>(path: string, method = 'GET', data?: unknown): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method, credentials: 'same-origin',
    headers: { 'X-KDOG-Request': '1', ...(data instanceof Blob ? {} : { 'Content-Type': 'application/json' }) },
    body: data === undefined ? undefined : data instanceof Blob ? data : JSON.stringify(data),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: '서버에 연결할 수 없습니다.' }));
    if (response.status === 401 && path !== '/auth/login') window.dispatchEvent(new Event('kdog-session-expired'));
    throw new Error(typeof error.detail === 'string' ? error.detail : '입력 형식을 확인하세요.');
  }
  return response.json();
}
