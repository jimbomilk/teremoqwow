import { setToken, token } from './store.js';

export function logout() {
  setToken('');
  document.getElementById('login-screen').style.display = 'flex';
  document.getElementById('login-error').textContent = '';
}

export async function login() {
  const email = document.getElementById('login-email').value;
  const pass  = document.getElementById('login-password').value;
  const authUrl = window.AUTH_URL || '';
  try {
    const r = await fetch(`${authUrl}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password: pass }),
    });
    if (!r.ok) {
      document.getElementById('login-error').textContent = 'Credenciales inválidas';
      return;
    }
    const data = await r.json();
    const payload = JSON.parse(atob(data.access_token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));
    if (!['admin', 'superadmin', 'operator', 'analyst'].includes(payload.role)) {
      document.getElementById('login-error').textContent = 'Acceso denegado: rol insuficiente';
      return;
    }
    setToken(data.access_token);
    document.getElementById('login-screen').style.display = 'none';
    document.getElementById('user-email').textContent = payload.email;
    document.getElementById('sidebar-user').textContent = `${payload.role} · ${payload.email}`;
    document.dispatchEvent(new CustomEvent('auth:login', { detail: payload }));
  } catch (e) {
    document.getElementById('login-error').textContent = 'Error de conexión con Auth API';
  }
}

document.addEventListener('auth:unauthorized', logout);

window.login = login;
window.logout = logout;
