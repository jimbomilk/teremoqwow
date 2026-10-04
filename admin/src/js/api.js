import { token } from './store.js';

const API = window.ADMIN_API_URL || '/admin-api';
export { API };

export async function api(path, opts = {}) {
  const r = await fetch(`${API}${path}`, {
    ...opts,
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json',
      ...(opts.headers || {}),
    },
  });
  if (r.status === 401) {
    document.dispatchEvent(new CustomEvent('auth:unauthorized'));
    throw new Error('401');
  }
  return r;
}
