export let token = localStorage.getItem('admin_token') || '';
export let currentPage = 'broadcasts';

export function setToken(t) {
  token = t;
  if (t) localStorage.setItem('admin_token', t);
  else localStorage.removeItem('admin_token');
}
export function setCurrentPage(p) { currentPage = p; }
