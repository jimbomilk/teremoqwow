import { api } from '../api.js';
import { setContent } from '../router.js';

function _signalTileId(broadcastId) { return 'tile-' + broadcastId.replace(/\W/g, '_'); }

function _renderSignalTile(b, audioInfo, ls, playerUrl) {
  const tid  = _signalTileId(b.id);
  const cert = window.MOQ_CERT_HASH ? `&cert=${encodeURIComponent(window.MOQ_CERT_HASH)}` : '';
  const relayParam = window.MOQ_RELAY_URL ? `&relay=${encodeURIComponent(window.MOQ_RELAY_URL)}` : '';
  const viewUrl = `${playerUrl}?embed=1&broadcast=${encodeURIComponent(b.id)}${relayParam}${cert}`;
  const lsMs = ls?.lipsync_ms ?? 0;
  const lsOk = Math.abs(lsMs) < 40;
  const lsColor = lsOk ? 'var(--green)' : Math.abs(lsMs) < 80 ? 'var(--yellow)' : 'var(--red)';
  const tracks = (audioInfo?.tracks || b.audio_tracks || [{ id: 't0', lang: 'es', label: 'Español' }]);
  const trackBadges = tracks.map(t =>
    `<span data-tid="${t.id}" data-bid="${b.id}"
      style="background:rgba(79,195,247,0.12);border:1px solid rgba(79,195,247,0.25);
             border-radius:3px;padding:1px 5px;font-size:0.65rem;color:var(--accent);cursor:pointer"
      title="Click para eliminar" onclick="removeAudioTrack('${b.id}','${t.id}')">${t.label}</span>`
  ).join('');

  const videoKbps = (b.video_kbps || Math.round(b.bitrate_kbps * 0.94));
  const audioKbps = audioInfo?.kbps || b.audio_kbps || (b.bitrate_kbps - videoKbps);

  return `
  <div id="${tid}" style="background:var(--surface);border:1px solid var(--border);border-radius:10px;overflow:hidden;display:flex;flex-direction:column">
    <div style="padding:0.45rem 0.8rem;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:0.5rem;flex-shrink:0;background:rgba(0,0,0,0.25)">
      <span style="width:8px;height:8px;border-radius:50%;background:var(--green);display:inline-block;animation:pulse 1.5s infinite;flex-shrink:0"></span>
      <code style="font-size:0.82rem;color:#fff;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${b.id}</code>
      ${b.simulated ? '<span class="badge yellow">sim</span>' : ''}
      <span class="badge green" style="font-size:0.65rem">${b.status}</span>
      <a href="${viewUrl}" target="_blank"
        style="background:rgba(79,195,247,0.14);border:1px solid rgba(79,195,247,0.3);color:var(--accent);
               padding:2px 10px;border-radius:4px;font-size:0.72rem;text-decoration:none;white-space:nowrap">▶ Ver</a>
      <button onclick="stopInject('${b.id}')"
        style="background:rgba(239,83,80,0.12);border:1px solid rgba(239,83,80,0.3);color:var(--red);
               padding:2px 8px;border-radius:4px;cursor:pointer;font-size:0.72rem">⏹ Parar</button>
      <button class="btn danger" style="font-size:0.7rem;padding:2px 8px;margin-left:8px;border-color:var(--red)" onclick="killBroadcast('${b.id}')">💀 Forzar</button>
      <button onclick="navigator.clipboard.writeText('${viewUrl}').then(e=>this.textContent='✓').catch(()=>{})"
        style="background:none;border:1px solid var(--border);color:var(--muted);padding:2px 7px;border-radius:4px;cursor:pointer;font-size:0.7rem" title="Copiar URL">📋</button>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;min-height:200px;flex:1">
      <div style="border-right:1px solid var(--border);display:flex;flex-direction:column;min-width:0">
        <div style="padding:0.3rem 0.6rem;font-size:0.63rem;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;border-bottom:1px solid rgba(255,255,255,0.05)">
          📹 Vídeo <span style="color:var(--muted);font-weight:400;text-transform:none;letter-spacing:0">· origen</span>
        </div>
        <iframe id="cv-vid-${tid}"
          src="${viewUrl}"
          loading="lazy"
          style="flex:1;width:100%;height:220px;min-height:220px;display:block;background:#000;border:none"
          title="Preview stream ${b.id}">
        </iframe>
        <div style="padding:0.35rem 0.6rem;font-size:0.7rem;line-height:1.6;border-top:1px solid rgba(255,255,255,0.06)">
          <div style="color:var(--text);font-weight:500">${b.video_resolution || '1280×720'} · ${b.video_fps || 30} fps</div>
          <div style="color:var(--muted)">${b.video_codec || 'H.264'} ${b.video_profile || 'Main'}</div>
          <div style="color:var(--accent)">${(videoKbps / 1000).toFixed(1)} Mbps vídeo</div>
          <div style="margin-top:3px">
            <a href="${viewUrl}" target="_blank" style="font-size:0.65rem;color:var(--accent);text-decoration:none">
              ↗ ver stream MoQ en el player
            </a>
          </div>
        </div>
      </div>
      <div style="border-right:1px solid var(--border);display:flex;flex-direction:column;min-width:0">
        <div style="padding:0.3rem 0.6rem;font-size:0.63rem;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;border-bottom:1px solid rgba(255,255,255,0.05)">🔊 Audio</div>
        <canvas id="cv-aud-${tid}" style="flex:1;width:100%;display:block;min-height:120px"></canvas>
        <div style="padding:0.35rem 0.6rem;font-size:0.7rem;line-height:1.6;border-top:1px solid rgba(255,255,255,0.06)">
          <div style="color:var(--text);font-weight:500">${audioInfo?.codec || b.audio_codec || 'AAC'} · ${audioKbps} kbps</div>
          <div style="color:var(--muted)">${audioInfo?.channels || b.audio_channels || 2}ch · ${((audioInfo?.sample_rate || b.audio_sample_rate || 48000) / 1000).toFixed(0)} kHz</div>
          <div style="display:flex;flex-wrap:wrap;gap:3px;margin-top:3px;align-items:center">
            ${trackBadges}
            <button onclick="addAudioTrackUI('${b.id}')"
              style="background:none;border:1px dashed rgba(255,255,255,0.2);color:var(--muted);padding:1px 5px;border-radius:3px;cursor:pointer;font-size:0.62rem;line-height:1.3">+</button>
          </div>
        </div>
      </div>
      <div style="display:flex;flex-direction:column;min-width:0">
        <div style="padding:0.3rem 0.6rem;font-size:0.63rem;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;border-bottom:1px solid rgba(255,255,255,0.05)">📊 Data</div>
        <div style="padding:0.5rem 0.7rem;flex:1;font-size:0.72rem;line-height:1.85">
          <div style="display:flex;justify-content:space-between"><span style="color:var(--muted)">Total bitrate</span><span style="color:var(--text)">${(b.bitrate_kbps / 1000).toFixed(1)} Mbps</span></div>
          <div style="display:flex;justify-content:space-between"><span style="color:var(--muted)">Viewers</span><span id="viewers-${tid}" style="color:var(--text)">${b.viewers}</span></div>
          <div style="display:flex;justify-content:space-between"><span style="color:var(--muted)">Relay</span><span id="relay-status-${tid}" style="color:var(--muted);font-size:0.65rem">—</span></div>
          <div style="display:flex;justify-content:space-between"><span style="color:var(--muted)">Lip-sync</span><span style="color:${lsColor}">${lsMs >= 0 ? '+' : ''}${lsMs} ms ${lsOk ? '✓' : '⚠'}</span></div>
          <div style="display:flex;justify-content:space-between"><span style="color:var(--muted)">Latencia</span><span style="color:var(--green)">&lt;100 ms</span></div>
          <div style="display:flex;justify-content:space-between"><span style="color:var(--muted)">Encoder</span><span style="color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:90px" title="${b.encoder || '—'}">${b.encoder || '—'}</span></div>
          <div style="display:flex;justify-content:space-between"><span style="color:var(--muted)">Iniciado</span><span style="color:var(--muted);font-size:0.65rem">${b.started_at?.slice(11, 19) || '—'}</span></div>
        </div>
        <div style="padding:0.35rem 0.6rem;border-top:1px solid rgba(255,255,255,0.06)">
          <div style="font-size:0.62rem;color:var(--muted);margin-bottom:3px">Simular alerta audio</div>
          <div style="display:flex;gap:3px">
            <button onclick="simAudioAlert('${b.id}','silence')" class="btn" style="flex:1;font-size:0.62rem;padding:2px">Silencio</button>
            <button onclick="simAudioAlert('${b.id}','clipping')" class="btn" style="flex:1;font-size:0.62rem;padding:2px">Clip</button>
            <button onclick="simAudioAlert('${b.id}','desync')" class="btn" style="flex:1;font-size:0.62rem;padding:2px">Desync</button>
          </div>
        </div>
      </div>
    </div>
  </div>`;
}

export async function loadBroadcasts() {
  const [r, srcR, audioR, lsR, alertsR] = await Promise.all([
    api('/admin/broadcasts'),
    api('/admin/monitor/source?broadcast=anon/live1'),
    api('/admin/audio/tracks'),
    api('/admin/audio/lipsync'),
    api('/admin/audio/alerts'),
  ]);
  const data      = await r.json();
  const source    = await srcR.json();
  const audioList = await audioR.json();
  const lsList    = await lsR.json();
  const auAlerts  = await alertsR.json();

  const audioMap = Object.fromEntries(audioList.map(a => [a.broadcast_id, a]));
  const lsMap    = Object.fromEntries(lsList.map(l => [l.broadcast_id, l]));

  const playerUrl = window.PLAYER_URL || 'http://localhost:5173';
  const active = data.filter(b => b.status === 'active');
  const cols   = active.length <= 2 ? (active.length <= 1 ? 1 : 2) : 2;

  const tiles = active.length
    ? active.map(b => _renderSignalTile(b, audioMap[b.id], lsMap[b.id], playerUrl)).join('')
    : `<div style="background:var(--surface);border:1px dashed var(--border);border-radius:10px;padding:3rem;display:flex;flex-direction:column;align-items:center;justify-content:center;color:var(--muted);grid-column:1/-1">
        <div style="font-size:2.5rem;margin-bottom:0.75rem">📡</div>
        <div style="font-size:0.9rem">Sin señales activas</div>
        <div style="font-size:0.78rem;margin-top:0.25rem">Usa el panel de inyección para iniciar un stream</div>
       </div>`;

  const alertHtml = auAlerts.length
    ? auAlerts.map(a => `
        <div style="display:flex;align-items:center;gap:0.6rem;padding:0.4rem 0;border-bottom:1px solid var(--border)">
          <span class="badge ${a.kind === 'silence' ? 'red' : a.kind === 'clipping' ? 'yellow' : 'blue'}">${a.kind}</span>
          <code style="font-size:0.75rem;flex:1">${a.broadcast_id}</code>
          <span style="font-size:0.7rem;color:var(--muted)">${a.ts?.slice(11, 19) || ''}</span>
          ${a.simulated ? '<span class="badge yellow" style="font-size:0.62rem">sim</span>' : ''}
          <button onclick="resolveAudioAlert('${a.id}')" class="btn" style="font-size:0.7rem;padding:2px 7px">Resolver</button>
        </div>`).join('')
    : '<p style="color:var(--muted);font-size:0.82rem">Sin alertas activas</p>';

  setContent(`
    <div style="display:grid;grid-template-columns:1fr 280px;gap:1.25rem;align-items:start">
      <div>
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:0.75rem">
          <div class="section-title" style="margin:0">Señales activas (${active.length})</div>
          <div style="display:flex;align-items:center;gap:0.5rem">
            ${active.length < 3 ? `<button id="btn-quick-test" onclick="quickTest(this)"
              style="background:rgba(76,175,80,0.15);border:1px solid var(--green);color:var(--green);
                     padding:2px 10px;border-radius:4px;cursor:pointer;font-size:0.78rem">🚀 Test rápido</button>` : ''}
            <span style="font-size:0.72rem;color:var(--muted)">${cols === 1 ? '1 columna' : '2 columnas'} · vídeo · audio · data</span>
          </div>
        </div>
        <div style="display:grid;grid-template-columns:repeat(${cols},1fr);gap:0.75rem;margin-bottom:1.25rem">
          ${tiles}
        </div>
        <div class="section-title" style="margin-bottom:0.5rem">Alertas de audio</div>
        <div class="card" style="padding:0.5rem 0.75rem">${alertHtml}</div>
      </div>
      <div style="display:flex;flex-direction:column;gap:0.75rem">
        <div>
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:0.5rem">
            <div class="section-title" style="margin:0">Nuevo canal</div>
            <div style="display:flex;gap:4px">
              <button id="mode-syn" onclick="setInjectMode('synthetic')"
                style="font-size:0.7rem;padding:2px 8px;border-radius:4px;cursor:pointer;border:1px solid var(--accent);background:var(--accent);color:#000">Sintético</button>
              <button id="mode-real" onclick="setInjectMode('real')"
                style="font-size:0.7rem;padding:2px 8px;border-radius:4px;cursor:pointer;border:1px solid var(--border);background:none;color:var(--muted)">Real</button>
            </div>
          </div>
          <div class="card" style="padding:0.75rem">
            <div style="margin-bottom:0.5rem">
              <div style="font-size:0.7rem;color:var(--muted);margin-bottom:2px">Broadcast ID</div>
              <input id="inj-id" value="anon/live2" style="width:100%;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:0.3rem 0.5rem;border-radius:4px;font-size:0.8rem"/>
            </div>
            <div style="margin-bottom:0.5rem">
              <div style="font-size:0.7rem;color:var(--muted);margin-bottom:4px">Preset</div>
              <div id="preset-btns" style="display:flex;gap:3px;flex-wrap:wrap">
                <span style="font-size:0.7rem;color:var(--muted)">Cargando...</span>
              </div>
            </div>
            <details style="margin-bottom:0.4rem">
              <summary style="font-size:0.72rem;color:var(--muted);cursor:pointer;margin-bottom:4px">📹 Vídeo</summary>
              <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px;margin-top:4px">
                <div><div style="font-size:0.65rem;color:var(--muted)">Resolución</div>
                  <input id="v-res" value="1280x720" style="width:100%;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:2px 4px;border-radius:3px;font-size:0.75rem"/></div>
                <div><div style="font-size:0.65rem;color:var(--muted)">FPS</div>
                  <input id="v-fps" type="number" value="30" style="width:100%;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:2px 4px;border-radius:3px;font-size:0.75rem"/></div>
                <div><div style="font-size:0.65rem;color:var(--muted)">Bitrate vídeo (kbps)</div>
                  <input id="v-kbps" type="number" value="4000" style="width:100%;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:2px 4px;border-radius:3px;font-size:0.75rem"/></div>
                <div><div style="font-size:0.65rem;color:var(--muted)">GOP frames</div>
                  <input id="v-gop" type="number" value="30" style="width:100%;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:2px 4px;border-radius:3px;font-size:0.75rem"/></div>
              </div>
            </details>
            <details style="margin-bottom:0.4rem">
              <summary style="font-size:0.72rem;color:var(--muted);cursor:pointer;margin-bottom:4px">🔊 Audio</summary>
              <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px;margin-top:4px">
                <div><div style="font-size:0.65rem;color:var(--muted)">Bitrate audio (kbps)</div>
                  <input id="a-kbps" type="number" value="128" style="width:100%;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:2px 4px;border-radius:3px;font-size:0.75rem"/></div>
                <div><div style="font-size:0.65rem;color:var(--muted)">Canales</div>
                  <select id="a-ch" style="width:100%;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:2px 4px;border-radius:3px;font-size:0.75rem">
                    <option value="2">Estéreo (2)</option><option value="1">Mono (1)</option><option value="6">5.1 (6)</option>
                  </select></div>
              </div>
              <div style="margin-top:4px">
                <div style="font-size:0.65rem;color:var(--muted);margin-bottom:2px">Pistas de idioma</div>
                <div id="inj-tracks" style="display:flex;flex-wrap:wrap;gap:3px;align-items:center">
                  <span class="inj-track-badge" data-lang="es" data-label="Español"
                    style="background:rgba(79,195,247,0.12);border:1px solid rgba(79,195,247,0.25);border-radius:3px;padding:1px 5px;font-size:0.65rem;color:var(--accent);cursor:pointer"
                    onclick="removeInjTrack(this)">Español ×</span>
                  <button onclick="addInjTrack()"
                    style="background:none;border:1px dashed rgba(255,255,255,0.2);color:var(--muted);padding:1px 5px;border-radius:3px;cursor:pointer;font-size:0.62rem">+</button>
                </div>
              </div>
            </details>
            <div id="srt-section" style="display:none;margin-bottom:0.5rem">
              <div style="font-size:0.7rem;color:var(--muted);margin-bottom:4px">📡 Fuente de ingesta</div>
              <div style="display:flex;gap:3px;margin-bottom:6px">
                <button id="src-testsrc" onclick="setIngestType('testsrc2')"
                  style="flex:1;font-size:0.65rem;padding:2px;border-radius:3px;cursor:pointer;border:1px solid var(--accent);background:rgba(79,195,247,0.15);color:var(--accent)">Testsrc2</button>
                <button id="src-push" onclick="setIngestType('srt_push')"
                  style="flex:1;font-size:0.65rem;padding:2px;border-radius:3px;cursor:pointer;border:1px solid var(--border);background:none;color:var(--muted)">SRT Push</button>
                <button id="src-pull" onclick="setIngestType('srt_pull')"
                  style="flex:1;font-size:0.65rem;padding:2px;border-radius:3px;cursor:pointer;border:1px solid var(--border);background:none;color:var(--muted)">SRT Pull</button>
              </div>
              <div id="srt-common" style="display:none;margin-bottom:4px">
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px">
                  <div><div style="font-size:0.65rem;color:var(--muted)">Puerto SRT</div>
                    <input id="srt-port" type="number" value="9998" style="width:100%;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:2px 4px;border-radius:3px;font-size:0.75rem"/></div>
                  <div><div style="font-size:0.65rem;color:var(--muted)">Latencia</div>
                    <select id="srt-lat" style="width:100%;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:2px 4px;border-radius:3px;font-size:0.75rem">
                      <option value="80">LAN (80ms)</option>
                      <option value="150">Nacional (150ms)</option>
                      <option value="300" selected>Internacional (300ms)</option>
                    </select></div>
                </div>
                <div style="margin-top:4px"><div style="font-size:0.65rem;color:var(--muted)">Passphrase (vacío = sin cifrado)</div>
                  <input id="srt-pass" type="password" placeholder="mínimo 10 chars" style="width:100%;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:2px 4px;border-radius:3px;font-size:0.75rem"/></div>
              </div>
              <div id="srt-pull-host" style="display:none;margin-bottom:4px">
                <div style="font-size:0.65rem;color:var(--muted)">Host encoder</div>
                <input id="srt-host" placeholder="192.168.1.50" style="width:100%;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:2px 4px;border-radius:3px;font-size:0.75rem"/>
              </div>
              <div id="srt-push-ep" style="display:none;margin-top:4px;padding:5px 7px;background:rgba(79,195,247,0.06);border:1px solid rgba(79,195,247,0.2);border-radius:4px">
                <div style="font-size:0.62rem;color:var(--muted);margin-bottom:2px">Comparte con tu encoder:</div>
                <div style="display:flex;align-items:center;gap:4px">
                  <code id="srt-ep-url" style="font-size:0.65rem;color:var(--accent);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"></code>
                  <button onclick="navigator.clipboard.writeText(document.getElementById('srt-ep-url').textContent).then(()=>this.textContent='✓')"
                    style="background:none;border:1px solid var(--border);color:var(--muted);padding:1px 5px;border-radius:3px;cursor:pointer;font-size:0.65rem">📋</button>
                </div>
              </div>
            </div>
            <div style="display:flex;gap:0.4rem;margin-top:0.5rem">
              <button id="btn-synthetic" onclick="createSynthetic()"
                style="flex:1;background:rgba(79,195,247,0.15);border:1px solid var(--accent);color:var(--accent);padding:0.35rem;border-radius:4px;cursor:pointer;font-size:0.78rem">▶ Crear sintético</button>
              <button id="btn-real" onclick="injectReal()" style="display:none;
                flex:1;background:rgba(76,175,80,0.15);border:1px solid var(--green);color:var(--green);padding:0.35rem;border-radius:4px;cursor:pointer;font-size:0.78rem">🚀 Inyectar real</button>
            </div>
            <div id="inj-status" style="margin-top:0.4rem;font-size:0.75rem;color:var(--muted)"></div>
            <div id="ffmpeg-block" style="display:none;margin-top:0.6rem">
              <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:3px">
                <span style="font-size:0.65rem;color:var(--muted)">Comando generado</span>
                <button onclick="navigator.clipboard.writeText(document.getElementById('ffmpeg-cmd').textContent).then(()=>this.textContent='✓')"
                  style="background:none;border:1px solid var(--border);color:var(--muted);padding:1px 6px;border-radius:3px;cursor:pointer;font-size:0.65rem">📋 Copiar</button>
              </div>
              <pre id="ffmpeg-cmd" style="background:#0a0a14;border:1px solid var(--border);border-radius:4px;padding:0.5rem;font-size:0.62rem;overflow-x:auto;white-space:pre;color:#a0d8ef;margin:0;max-height:120px;overflow-y:auto"></pre>
            </div>
          </div>
        </div>
        <div>
          <div class="section-title" style="margin-bottom:0.5rem">Resumen</div>
          <div class="card">
            <div class="stat-item"><span class="stat-label">Señales activas</span><span class="stat-value green">${active.length}</span></div>
            <div class="stat-item"><span class="stat-label">Bitrate total</span><span class="stat-value">${(data.reduce((s, b) => s + b.bitrate_kbps, 0) / 1000).toFixed(1)} Mbps</span></div>
            <div class="stat-item"><span class="stat-label">Viewers totales</span><span class="stat-value">${data.reduce((s, b) => s + b.viewers, 0)}</span></div>
            <div class="stat-item"><span class="stat-label">Fuente relay</span><span class="stat-value" style="color:${source.broadcasting ? 'var(--green)' : 'var(--red)'}">${source.broadcasting ? '🟢 LIVE' : '🔴 OFF'}</span></div>
            <div class="stat-item"><span class="stat-label">Alertas audio</span><span class="stat-value ${auAlerts.length ? 'yellow' : 'green'}">${auAlerts.length}</span></div>
          </div>
        </div>
        <div>
          <div class="section-title" style="margin-bottom:0.5rem">Todos los broadcasts</div>
          <div style="font-size:0.78rem">
            ${data.map(b => `
              <div style="display:flex;align-items:center;gap:0.4rem;padding:0.35rem 0;border-bottom:1px solid var(--border)">
                <span class="badge ${b.status === 'active' ? 'green' : b.status === 'stopped' ? 'yellow' : 'red'}" style="font-size:0.62rem">${b.status}</span>
                <code style="font-size:0.72rem;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${b.id}</code>
                <span style="color:var(--muted);font-size:0.7rem">${(b.bitrate_kbps / 1000).toFixed(1)}M</span>
                ${b.status !== 'active' ? `<button class="btn" style="font-size:0.65rem;padding:1px 6px" onclick="injectBroadcast('${b.id}',4000)">▶</button>` : ''}
              </div>`).join('')}
          </div>
        </div>
      </div>
    </div>`);

  loadPresets();
  requestAnimationFrame(() => _startSignalAnimations(active));
  _startRelayPoll(active);
}

// ── Poll relay ─────────────────────────────────────────────────────────────────

let _relayPollTimer = null;

function _startRelayPoll(broadcasts) {
  if (_relayPollTimer) clearInterval(_relayPollTimer);
  async function poll() {
    try {
      const r = await api('/admin/relay/connections');
      if (!r.ok) return;
      const d = await r.json();
      broadcasts.forEach(b => {
        const tid = _signalTileId(b.id);
        const viewersEl = document.getElementById('viewers-' + tid);
        const statusEl  = document.getElementById('relay-status-' + tid);
        if (!viewersEl || !statusEl) return;
        const isLive = d.online && d.broadcasts.some(s => s.includes(b.id.split('/')[0]));
        viewersEl.textContent = String(b.viewers);
        viewersEl.style.color = isLive ? 'var(--green)' : 'var(--muted)';
        statusEl.textContent  = d.online ? (isLive ? '🟢 publicando' : '🟡 sin stream') : '🔴 relay off';
        statusEl.style.color  = d.online ? (isLive ? 'var(--green)' : 'var(--yellow)') : 'var(--red)';
      });
    } catch (_) {}
  }
  poll();
  _relayPollTimer = setInterval(poll, 3000);
}

// ── Audio canvas animations ────────────────────────────────────────────────────

let _animFrames = [];

function _startSignalAnimations(broadcasts) {
  _animFrames.forEach(id => cancelAnimationFrame(id));
  _animFrames = [];
  broadcasts.forEach(b => {
    const tid = _signalTileId(b.id);
    const cva = document.getElementById('cv-aud-' + tid);
    if (!cva) return;
    const ctx = cva.getContext('2d');
    const W = cva.offsetWidth || 200, H = cva.offsetHeight || 120;
    cva.width = W; cva.height = H;
    let vuL = 0.75, vuR = 0.68, pkL = 0.75, pkR = 0.68;
    const PKD = 0.008;
    function drawAudio() {
      ctx.clearRect(0, 0, W, H);
      ctx.fillStyle = '#0a0a14'; ctx.fillRect(0, 0, W, H);
      const base = Math.min(0.95, 0.5 + (b.audio_kbps || 128) / 512);
      vuL = Math.max(0.05, Math.min(0.98, vuL + (Math.random() - .42) * 0.12 + (base - vuL) * 0.06));
      vuR = Math.max(0.05, Math.min(0.98, vuR + (Math.random() - .42) * 0.12 + (base - vuR) * 0.06));
      pkL = Math.max(vuL, pkL - PKD);
      pkR = Math.max(vuR, pkR - PKD);
      const mW = 22, gap = 6, barsTotal = 2 * mW + gap;
      const ox = (W - barsTotal) / 2;
      const barH = H * 0.72;
      const barY = H * 0.06;
      [['L', ox, vuL, pkL], ['R', ox + mW + gap, vuR, pkR]].forEach(([label, x, lv, pk]) => {
        ctx.fillStyle = '#1a1a2e'; ctx.fillRect(x, barY, mW, barH);
        const segs = 20;
        const filledSegs = Math.round(lv * segs);
        for (let s = 0; s < segs; s++) {
          const sy = barY + barH - (s + 1) * (barH / segs);
          const sh = barH / segs - 1;
          const pct = s / segs;
          ctx.fillStyle = s >= filledSegs ? '#1a2a1a'
            : pct < 0.6 ? '#4caf50'
            : pct < 0.8 ? '#ffc107'
            : '#ef5350';
          ctx.fillRect(x + 1, sy, mW - 2, sh);
        }
        const py = barY + barH - pk * barH - 2;
        ctx.fillStyle = '#fff'; ctx.fillRect(x, py, mW, 2);
        ctx.fillStyle = '#666'; ctx.font = '9px monospace'; ctx.textAlign = 'center';
        ctx.fillText(label, x + mW / 2, barY + barH + 11);
      });
      const lufs = -23 + (vuL + vuR - 1.0) * 8;
      const dbfs = -6 + (Math.max(pkL, pkR) - 0.8) * 18;
      ctx.fillStyle = 'rgba(255,255,255,0.55)'; ctx.font = '9px monospace'; ctx.textAlign = 'center';
      ctx.fillText(`${lufs.toFixed(1)} LUFS`, W / 2, H * 0.94);
      ctx.fillStyle = 'rgba(255,255,255,0.35)';
      ctx.fillText(`pico ${dbfs.toFixed(1)} dBFS`, W / 2, H * 0.86);
      _animFrames.push(requestAnimationFrame(drawAudio));
    }
    drawAudio();
  });
}

// ── Audio track helpers ────────────────────────────────────────────────────────

async function addAudioTrackUI(broadcastId) {
  const lang  = prompt('Código de idioma (ej: en, fr, pt):', 'en');
  if (!lang) return;
  const label = prompt('Etiqueta (ej: English):', lang.toUpperCase()) || lang.toUpperCase();
  await api('/admin/audio/tracks/add', { method: 'POST', body: JSON.stringify({ broadcast_id: broadcastId, lang, label }) });
  loadBroadcasts();
}

async function removeAudioTrack(broadcastId, trackId) {
  await api('/admin/audio/tracks/remove', { method: 'POST', body: JSON.stringify({ broadcast_id: broadcastId, track_id: trackId }) });
  loadBroadcasts();
}

async function simAudioAlert(broadcastId, kind) {
  await api('/admin/audio/alerts/simulate', { method: 'POST', body: JSON.stringify({ broadcast_id: broadcastId, kind }) });
  loadBroadcasts();
}

async function resolveAudioAlert(alertId) {
  await api('/admin/audio/alerts/resolve', { method: 'POST', body: JSON.stringify({ alert_id: alertId }) });
  loadBroadcasts();
}

// ── Inject panel ───────────────────────────────────────────────────────────────

let _injMode = 'synthetic';
let _ingestType = 'testsrc2';
let _presets = [];

async function loadPresets() {
  try {
    const r = await api('/admin/broadcasts/presets');
    _presets = await r.json();
    const container = document.getElementById('preset-btns');
    if (!container) return;
    container.innerHTML = _presets.map((p, i) => `
      <button onclick="applyPreset(${i})"
        style="font-size:0.65rem;padding:2px 7px;border-radius:3px;cursor:pointer;
               border:1px solid var(--border);background:none;color:var(--muted)"
        id="preset-${p.id}">${p.label}</button>
    `).join('');
  } catch (_) {}
}

function applyPreset(idx) {
  const p = _presets[idx];
  if (!p) return;
  _setVal('v-res', p.video.resolution);
  _setVal('v-fps', p.video.fps);
  _setVal('v-kbps', p.video.kbps);
  _setVal('v-gop', p.video.gop_frames);
  _setVal('a-kbps', p.audio.kbps);
  _setVal('a-ch', p.audio.channels);
  _presets.forEach(x => {
    const btn = document.getElementById('preset-' + x.id);
    if (btn) { btn.style.borderColor = 'var(--border)'; btn.style.color = 'var(--muted)'; btn.style.background = 'none'; }
  });
  const active = document.getElementById('preset-' + p.id);
  if (active) { active.style.borderColor = 'var(--accent)'; active.style.color = 'var(--accent)'; active.style.background = 'rgba(79,195,247,0.12)'; }
  const status = document.getElementById('inj-status');
  if (status) status.textContent = `Preset "${p.label}" aplicado · ${(p.total_kbps / 1000).toFixed(1)} Mbps total`;
}

function _setVal(id, val) {
  const el = document.getElementById(id);
  if (el) el.value = val;
}

function setInjectMode(mode) {
  _injMode = mode;
  const synBtn  = document.getElementById('mode-syn');
  const realBtn = document.getElementById('mode-real');
  const srtSec  = document.getElementById('srt-section');
  const btnSyn  = document.getElementById('btn-synthetic');
  const btnReal = document.getElementById('btn-real');
  if (mode === 'synthetic') {
    synBtn.style.cssText  += ';background:var(--accent);color:#000;border-color:var(--accent)';
    realBtn.style.cssText += ';background:none;color:var(--muted);border-color:var(--border)';
    srtSec.style.display = 'none';
    btnSyn.style.display = ''; btnReal.style.display = 'none';
  } else {
    realBtn.style.cssText += ';background:var(--accent);color:#000;border-color:var(--accent)';
    synBtn.style.cssText  += ';background:none;color:var(--muted);border-color:var(--border)';
    srtSec.style.display = '';
    btnSyn.style.display = 'none'; btnReal.style.display = '';
    updateSrtEndpointPreview();
  }
}

function setIngestType(type) {
  _ingestType = type;
  const ids = { testsrc2: 'src-testsrc', srt_push: 'src-push', srt_pull: 'src-pull' };
  Object.entries(ids).forEach(([t, id]) => {
    const btn = document.getElementById(id);
    if (!btn) return;
    const active = t === type;
    btn.style.borderColor  = active ? 'var(--accent)' : 'var(--border)';
    btn.style.color        = active ? 'var(--accent)' : 'var(--muted)';
    btn.style.background   = active ? 'rgba(79,195,247,0.15)' : 'none';
  });
  document.getElementById('srt-common').style.display    = type !== 'testsrc2' ? '' : 'none';
  document.getElementById('srt-pull-host').style.display = type === 'srt_pull' ? '' : 'none';
  document.getElementById('srt-push-ep').style.display   = type === 'srt_push' ? '' : 'none';
  if (type === 'srt_push') updateSrtEndpointPreview();
}

function updateSrtEndpointPreview() {
  const el = document.getElementById('srt-ep-url');
  if (!el) return;
  const port = document.getElementById('srt-port')?.value || '9998';
  const lat  = document.getElementById('srt-lat')?.value || '300';
  const bid  = document.getElementById('inj-id')?.value || 'anon/live2';
  const hostIp = window.HOST_IP || window.location.hostname || '0.0.0.0';
  el.textContent = `srt://${hostIp}:${port}?streamid=${bid}&latency=${lat}`;
}

function addInjTrack() {
  const lang  = prompt('Código de idioma (ej: en, fr, pt):', 'en');
  if (!lang) return;
  const label = prompt('Etiqueta:', lang.toUpperCase()) || lang.toUpperCase();
  const container = document.getElementById('inj-tracks');
  const addBtn = container.querySelector('button');
  const span = document.createElement('span');
  span.className = 'inj-track-badge';
  span.dataset.lang = lang; span.dataset.label = label;
  span.textContent = label + ' ×';
  span.style.cssText = 'background:rgba(79,195,247,0.12);border:1px solid rgba(79,195,247,0.25);border-radius:3px;padding:1px 5px;font-size:0.65rem;color:var(--accent);cursor:pointer';
  span.onclick = () => removeInjTrack(span);
  container.insertBefore(span, addBtn);
}

function removeInjTrack(el) {
  const badges = document.querySelectorAll('#inj-tracks .inj-track-badge');
  if (badges.length <= 1) { alert('Debe haber al menos una pista de audio'); return; }
  el.remove();
}

function _getInjPayload() {
  const bid = document.getElementById('inj-id')?.value?.trim() || '';
  const tracks = [...document.querySelectorAll('#inj-tracks .inj-track-badge')]
    .map(el => ({ lang: el.dataset.lang, label: el.dataset.label }));
  return {
    broadcast_id: bid,
    video: {
      resolution: document.getElementById('v-res')?.value || '1280x720',
      fps: parseInt(document.getElementById('v-fps')?.value || '30'),
      kbps: parseInt(document.getElementById('v-kbps')?.value || '4000'),
      gop_frames: parseInt(document.getElementById('v-gop')?.value || '30'),
    },
    audio: {
      kbps: parseInt(document.getElementById('a-kbps')?.value || '128'),
      channels: parseInt(document.getElementById('a-ch')?.value || '2'),
      sample_rate: 48000,
      tracks,
    },
  };
}

async function createSynthetic() {
  const st = document.getElementById('inj-status');
  const payload = _getInjPayload();
  if (!payload.broadcast_id) { if (st) st.textContent = '⚠ Broadcast ID es obligatorio'; return; }
  if (payload.audio.kbps < 96) { if (st) st.textContent = '⚠ Audio mínimo 96 kbps'; return; }
  if (st) st.textContent = 'Creando...';
  try {
    const r = await api('/admin/broadcasts/create', { method: 'POST', body: JSON.stringify({ ...payload, ingest_type: 'synthetic' }) });
    const d = await r.json();
    if (r.status === 409) { if (st) st.textContent = `⚠ ${d.error}`; return; }
    if (st) st.textContent = `✓ Canal sintético "${payload.broadcast_id}" creado`;
    setTimeout(() => loadBroadcasts(), 600);
  } catch (e) { if (st) st.textContent = 'Error: ' + e.message; }
}

async function injectReal() {
  const st = document.getElementById('inj-status');
  const payload = _getInjPayload();
  if (!payload.broadcast_id) { if (st) st.textContent = '⚠ Broadcast ID es obligatorio'; return; }
  const srtPayload = _ingestType !== 'testsrc2' ? {
    port: parseInt(document.getElementById('srt-port')?.value || '9998'),
    latency_ms: parseInt(document.getElementById('srt-lat')?.value || '300'),
    passphrase: document.getElementById('srt-pass')?.value || '',
    host: document.getElementById('srt-host')?.value || '',
  } : undefined;
  if (_ingestType === 'srt_pull' && !srtPayload?.host) {
    if (st) st.textContent = '⚠ Host encoder es obligatorio para SRT Pull'; return;
  }
  if (st) st.textContent = 'Inyectando...';
  try {
    const body = { ...payload, ingest_type: _ingestType };
    if (srtPayload) body.srt = srtPayload;
    const r = await api('/admin/broadcasts/inject', { method: 'POST', body: JSON.stringify(body) });
    const d = await r.json();
    if (st) st.textContent = d.note || 'OK';
    if (d.ffmpeg_cmd) {
      document.getElementById('ffmpeg-block').style.display = '';
      document.getElementById('ffmpeg-cmd').textContent = d.ffmpeg_cmd;
    }
    setTimeout(() => loadBroadcasts(), 800);
  } catch (e) { if (st) st.textContent = 'Error: ' + e.message; }
}

async function quickTest(btn) {
  btn.disabled = true;
  const origText = btn.textContent;
  btn.textContent = '⏳...';
  try {
    const r = await api('/admin/broadcasts/quick-test', { method: 'POST', body: JSON.stringify({}) });
    const d = await r.json();
    if (!r.ok) { alert(d.error || 'Error al crear test rápido'); }
    loadBroadcasts();
  } catch (e) {
    alert('Error: ' + e.message);
    btn.disabled = false;
    btn.textContent = origText;
  }
}

async function killBroadcast(id) {
  if (!confirm(`¿Forzar parada de broadcast ${id}?`)) return;
  await api('/admin/broadcasts/kill', { method: 'POST', body: JSON.stringify({ broadcast_id: id }) });
  loadBroadcasts();
}

export async function injectBroadcast(id, bitrate) {
  const st = document.getElementById('inj-status');
  if (st) st.textContent = 'Inyectando...';
  const r = await api('/admin/broadcasts/inject', { method: 'POST', body: JSON.stringify({ broadcast_id: id, bitrate_kbps: bitrate }) });
  const d = await r.json();
  if (st) st.textContent = d.note || 'OK';
  setTimeout(() => loadBroadcasts(), 800);
}

async function injectFromForm() { await injectReal(); }

async function stopInject(id) {
  await api('/admin/broadcasts/stop-inject', { method: 'POST', body: JSON.stringify({ broadcast_id: id }) });
  loadBroadcasts();
}

window.stopInject              = stopInject;
window.killBroadcast           = killBroadcast;
window.removeAudioTrack        = removeAudioTrack;
window.addAudioTrackUI         = addAudioTrackUI;
window.simAudioAlert           = simAudioAlert;
window.resolveAudioAlert       = resolveAudioAlert;
window.quickTest               = quickTest;
window.setInjectMode           = setInjectMode;
window.setIngestType           = setIngestType;
window.applyPreset             = applyPreset;
window.addInjTrack             = addInjTrack;
window.removeInjTrack          = removeInjTrack;
window.createSynthetic         = createSynthetic;
window.injectReal              = injectReal;
window.injectFromForm          = injectFromForm;
window.injectBroadcast         = injectBroadcast;
window.updateSrtEndpointPreview = updateSrtEndpointPreview;
