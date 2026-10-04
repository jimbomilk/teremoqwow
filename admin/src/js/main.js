import { token } from './store.js';
import { login, logout } from './auth.js';
import { navigate, loadPage, pages } from './router.js';
import { startGlobalStatusPoll } from './poll.js';
import { API } from './api.js';
// Register monitor window functions (loadMonitor is not yet in the nav, but code is preserved)
import './pages/monitor.js';

const _host = window.location.hostname || 'localhost';
window.MOQ_RELAY_URL = `https://${_host}:4443/anon`;
// En prod el player está en /player/ (nginx); en dev en :5173
window.PLAYER_URL    = window.location.port ? `https://${_host}:5443` : `${window.location.origin}/player`;
window.AUTH_URL      = window.AUTH_URL || '';

(async () => {
  try {
    const r = await fetch(`${API}/admin/relay/cert-hash`);
    if (r.ok) {
      const d = await r.json();
      if (d.cert_hash) window.MOQ_CERT_HASH = d.cert_hash;
    }
  } catch (_) {}
})();

if (token) {
  try {
    const payload = JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));
    if (payload.exp > Date.now() / 1000) {
      document.getElementById('login-screen').style.display = 'none';
      document.getElementById('user-email').textContent = payload.email;
      document.getElementById('sidebar-user').textContent = `${payload.role} · ${payload.email}`;
      loadPage('broadcasts');
      startGlobalStatusPoll();
    } else {
      logout();
    }
  } catch (e) {
    logout();
  }
}

document.addEventListener('auth:login', () => {
  loadPage('broadcasts');
  startGlobalStatusPoll();
});
