/**
 * Página Pipeline (#214): estado de transporte (automático) y verificación humana, por fase.
 * La lógica (acciones, refresh, polling) vive en pipeline-actions.js con dependencias inyectables.
 */
import { api } from '../api.js';
import { currentPage } from '../store.js';
import { setContent, setMonitorInterval } from '../router.js';
import { attachClicks, refresh, runAction, startPolling, POLL_MS } from './pipeline-actions.js';

// Cada loadPipeline() abre una "generación". Un refresh/tick/acción solo pinta si su generación
// sigue siendo la vigente Y la página activa es Pipeline: así una carga antigua (A) nunca pisa a la nueva (B).
let generation = 0;
let pollId = null;

const stopPolling = () => {
  if (pollId !== null) { window.clearInterval(pollId); pollId = null; }
};
const isActiveFor = (gen) => () => currentPage === 'pipeline' && gen === generation;
const reloadFor = (gen) => () => refresh({ api, setContent, isActive: isActiveFor(gen) });

function onAction(phase, action) {
  const gen = generation; // la instancia vigente en el momento del clic
  return runAction({
    api, phase, action, reload: reloadFor(gen),
    askNote: (a) => window.prompt(a === 'verify'
      ? 'Nota de verificación (opcional). Confirmas que has visto y oído la fase correctamente:'
      : 'Motivo de la revocación (opcional):'),
    notify: (msg) => window.alert(msg),
  });
}

export async function loadPipeline() {
  const gen = ++generation;
  stopPolling(); // nunca dos intervals: se limpia el anterior antes de registrar otro
  const content = document.getElementById('content');
  attachClicks(content, onAction);
  const reload = reloadFor(gen);
  await reload();
  if (!isActiveFor(gen)()) return; // caducada: ni pinta ni registra polling
  stopPolling();
  pollId = startPolling({
    refresh: reload, isActive: isActiveFor(gen), setInterval: window.setInterval.bind(window),
    clearInterval: (id) => { window.clearInterval(id); if (pollId === id) pollId = null; },
    setMonitorInterval, ms: POLL_MS,
  });
}
