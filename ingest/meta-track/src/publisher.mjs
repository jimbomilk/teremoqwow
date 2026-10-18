#!/usr/bin/env node

import * as Moq from '@moq/net';
import { writeFileSync } from 'node:fs';

// Configuration from environment
const MOQ_URL = process.env.MOQ_URL || 'http://moq-relay:8090/';
const BROADCAST = process.env.BROADCAST || 'anon/live1-meta';
const TRACK = process.env.TRACK || 'heartbeat';
const INTERVAL_MS = parseInt(process.env.INTERVAL_MS || '1000', 10);
const HEALTH_MARKER_PATH = process.env.HEALTH_MARKER_PATH || '/tmp/meta-publisher-health';

// Enmienda H2 (2026-10-18, contrato #206 opción B): reconexión finita.
// Intentos consecutivos fallidos de conexión antes de exit(1); Docker
// (restart: unless-stopped) reinicia el servicio. Default 30 = producción,
// por eso docker-compose.prod.yml NO añade la env.
const DEFAULT_MAX_RECONNECT_ATTEMPTS = 30;

/**
 * Valida MAX_RECONNECT_ATTEMPTS: entero > 0. Ausente o inválida → default 30
 * (contrato enmienda H2). Acepta number entero finito o string de dígitos
 * (whitespace tolerado; "0"/"-2"/"abc"/"2.5"/"1e3" → default).
 * @param {string|number|undefined|null} raw
 * @returns {number} entero > 0
 */
function parseMaxReconnectAttempts(raw) {
  if (raw === undefined || raw === null || raw === '') {
    return DEFAULT_MAX_RECONNECT_ATTEMPTS;
  }
  if (typeof raw === 'number') {
    return Number.isInteger(raw) && raw > 0 ? raw : DEFAULT_MAX_RECONNECT_ATTEMPTS;
  }
  if (typeof raw !== 'string' || !/^\s*\d+\s*$/.test(raw)) {
    return DEFAULT_MAX_RECONNECT_ATTEMPTS;
  }
  const n = parseInt(raw, 10);
  return Number.isSafeInteger(n) && n > 0 ? n : DEFAULT_MAX_RECONNECT_ATTEMPTS;
}

const MAX_RECONNECT_ATTEMPTS = parseMaxReconnectAttempts(process.env.MAX_RECONNECT_ATTEMPTS);

// Guard: reject non-anon/live1-meta broadcasts
if (BROADCAST !== 'anon/live1-meta') {
  console.error(`ERROR: BROADCAST must be 'anon/live1-meta', got '${BROADCAST}'`);
  process.exit(1);
}

// Validate interval
if (INTERVAL_MS < 100 || INTERVAL_MS > 10000) {
  console.error(`ERROR: INTERVAL_MS must be between 100 and 10000, got ${INTERVAL_MS}`);
  process.exit(1);
}

// Generate random boot_id (16 hex characters)
function generateBootId() {
  let id = '';
  for (let i = 0; i < 16; i++) {
    id += Math.floor(Math.random() * 16).toString(16);
  }
  return id;
}

// Write health marker
function updateHealthMarker() {
  try {
    const path = process.env.HEALTH_MARKER_PATH || '/tmp/meta-publisher-health';
    writeFileSync(path, Date.now().toString(), 'utf-8');
  } catch (err) {
    // Ignore health marker write errors
  }
}

// Timer with drift correction
class DriftCorrectionTimer {
  constructor(interval) {
    this.interval = interval;
    this.nextFireTime = Date.now() + interval;
  }

  async wait() {
    const now = Date.now();
    const delay = Math.max(0, this.nextFireTime - now);
    this.nextFireTime += this.interval;

    if (delay > 0) {
      await new Promise(resolve => setTimeout(resolve, delay));
    }
  }
}

/**
 * Publica un heartbeat como UN GRUPO CERRADO por evento
 * @param {TrackProducer} track - El track donde publicar
 * @param {object} heartbeat - El objeto heartbeat a publicar
 */
function publishHeartbeatAsGroup(track, heartbeat) {
  // Contrato #206: Un grupo MoQ por evento, un frame por grupo
  const group = track.appendGroup();
  try {
    group.writeJson(heartbeat);
    group.close(); // Cerrar el grupo después de escribir el JSON
  } catch (err) {
    // Si hay error, cerramos con abort
    group.close(err);
    throw err;
  }
}

/**
 * Main publisher loop with injectable dependencies for testing
 * @param {object} options - Injectable dependencies for testing
 * @param {Function} options.connect - Connect function (default: Moq.Connection.connect)
 * @param {object} options.origin - MoQ origin (default: new Moq.Origin.Producer())
 * @param {object} options.track - Track object (default: created from origin)
 * @param {object} options.timer - Timer instance (default: new DriftCorrectionTimer)
 * @param {number} options.maxPublishes - Max publishes before exit (test only)
 * @param {number} options.maxReconnectAttempts - Consecutive failed reconnect
 *   attempts before exit(1) (default: MAX_RECONNECT_ATTEMPTS from env, 30)
 * @param {Function} options.sleep - Sleep function for backoff waits
 *   (default: real setTimeout promise; injectable for tests)
 * @param {Function} options.exit - Exit function on fatal errors
 *   (default: process.exit; injectable for tests)
 */
async function publishHeartbeats(options = {}) {
  // Defaults for production CLI
  const {
    connect = Moq.Connection.connect,
    origin = null, // Will be created if not provided
    track = null, // Will be created if not provided
    timer = null, // Will be created if not provided
    maxPublishes = Infinity, // Test limit
    maxReconnectAttempts = MAX_RECONNECT_ATTEMPTS, // Enmienda H2: finite reconnect
    sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms)),
    exit = (code) => process.exit(code),
  } = options;

  console.error(`[Publisher] Connecting to ${MOQ_URL}`);
  console.error(`[Publisher] Broadcast: ${BROADCAST}, Track: ${TRACK}, Interval: ${INTERVAL_MS}ms`);

  const relayUrl = new URL(MOQ_URL);
  const broadcastPath = BROADCAST.replace(/^\/+/, '');
  const bootId = generateBootId();
  let seq = 0;
  let reconnectBackoff = 1000; // ms
  let reconnectAttempts = 0; // Enmienda H2: intentos consecutivos fallidos
  let totalPublished = 0;

  while (totalPublished < maxPublishes) {
    try {
      console.error(`[Publisher] Connecting (backoff: ${reconnectBackoff}ms)...`);

      // Create or use injected origin and track
      let publishOrigin = origin;
      let publishTrack = track;

      if (!publishOrigin) {
        publishOrigin = new Moq.Origin.Producer();
      }

      if (!publishTrack) {
        const publishedBroadcast = publishOrigin.createBroadcast(Moq.Path.from(broadcastPath));
        publishTrack = publishedBroadcast.createTrack(TRACK, {
          timescale: 1000, // 1 ms = 1 unit
          maxAge: 60000, // 60 seconds
        });
        publishedBroadcast.announce();
      }

      const connection = await connect({
        url: relayUrl,
        publish: publishOrigin.consume(),
      });

      reconnectBackoff = 1000; // reset on successful connect
      console.error(`[Publisher] Connected! Starting to publish...`);

      // Use injected timer if provided
      const pubTimer = timer || new DriftCorrectionTimer(INTERVAL_MS);

      // Publish loop with connection monitoring
      let connectionLost = false;
      while (!connectionLost && totalPublished < maxPublishes) {
        try {
          // Wait for next publish interval OR connection closure, whichever comes first
          const raceResult = await Promise.race([
            pubTimer.wait(),
            connection.closed.then(() => {
              throw new Error('Connection closed by relay');
            }),
          ]);

          // CRITICAL: After Promise.race resolves, verify connection.closed state
          // because timer and closed might resolve simultaneously
          let closedState = false;
          try {
            // Check if closed is already resolved (will resolve immediately if true)
            await Promise.race([
              connection.closed.then(() => {
                closedState = true;
              }),
              Promise.resolve(), // if closed is pending, this wins
            ]);
          } catch (e) {
            // closed rejected or threw
            closedState = true;
          }

          if (closedState) {
            console.error(`[Publisher] Connection detected closed before publishing`);
            connectionLost = true;
            break;
          }

          const now = new Date();
          const heartbeat = {
            v: 1,
            boot_id: bootId,
            seq: seq++,
            emitted_at: now.toISOString(),
            source_id: 'anon/live1',
          };

          try {
            // FIX #206: Usar appendGroup() + writeJson() + close() en lugar de Stream.Producer
            publishHeartbeatAsGroup(publishTrack, heartbeat);
            totalPublished++;
            // Enmienda H2: publicación iniciada con éxito → reset del contador
            // de intentos consecutivos fallidos de reconexión.
            reconnectAttempts = 0;

            updateHealthMarker();

            if (seq % 60 === 0) {
              console.error(`[Publisher] Published ${seq} events, boot_id=${bootId}, seq=${heartbeat.seq}`);
            }
          } catch (err) {
            // Distinguish between permanent and recoverable errors
            const isApiError = err instanceof TypeError; // e.g., "write is not a function" or encoding errors
            const isPermanent = isApiError; // API errors cannot be recovered

            if (isPermanent) {
              console.error(`[Publisher] PERMANENT ERROR (API/encoding): ${err.message}`);
              process.exit(1); // exit with error code, per contract
            }

            // Transient error (e.g., connection issue)
            console.error(`[Publisher] Transient error publishing frame: ${err.message}`);
            connectionLost = true;
          }
        } catch (err) {
          // Caught connection.closed promise or other errors from Promise.race
          if (err.message === 'Connection closed by relay' || err.message.includes('closed')) {
            console.error(`[Publisher] Relay closed connection`);
            connectionLost = true;
          } else if (err instanceof TypeError) {
            // API error
            console.error(`[Publisher] PERMANENT ERROR (API/encoding): ${err.message}`);
            process.exit(1);
          } else {
            // Other error
            console.error(`[Publisher] Error during publish: ${err.message}`);
            connectionLost = true;
          }
        }
      }

      if (totalPublished >= maxPublishes) {
        // Test limit reached - FIX #4: close connection before exiting
        console.error(`[Publisher] Reached test limit of ${maxPublishes} publishes`);
        try { connection.close(); } catch (e) { /* ignore */ }
        break;
      }

      // Connection lost, close and reconnect
      try { connection.close(); } catch (e) { /* ignore */ }

      // Enmienda H2 (contrato #206, opción B): reconexión finita
      reconnectAttempts++;
      if (reconnectAttempts >= maxReconnectAttempts) {
        console.error(
          `[Publisher] FATAL: ${reconnectAttempts}/${maxReconnectAttempts} ` +
          `reconnect attempts exhausted (MAX_RECONNECT_ATTEMPTS=${maxReconnectAttempts}); exiting for restart`
        );
        exit(1);
        return;
      }

      reconnectBackoff = Math.min(reconnectBackoff * 1.5, 5000);
      console.error(`[Publisher] Reconnecting in ${reconnectBackoff}ms...`);
      await sleep(reconnectBackoff);
    } catch (err) {
      console.error(`[Publisher] Connection error: ${err.message}`);

      // Enmienda H2 (contrato #206, opción B): reconexión finita
      reconnectAttempts++;
      if (reconnectAttempts >= maxReconnectAttempts) {
        console.error(
          `[Publisher] FATAL: ${reconnectAttempts}/${maxReconnectAttempts} ` +
          `reconnect attempts exhausted (MAX_RECONNECT_ATTEMPTS=${maxReconnectAttempts}); exiting for restart`
        );
        exit(1);
        return;
      }

      // Exponential backoff with cap at 5s
      reconnectBackoff = Math.min(reconnectBackoff * 1.5, 5000);
      console.error(`[Publisher] Reconnecting in ${reconnectBackoff}ms...`);

      await sleep(reconnectBackoff);
    }
  }
}

// Export for testing
export {
  publishHeartbeats,
  generateBootId,
  DriftCorrectionTimer,
  updateHealthMarker,
  publishHeartbeatAsGroup,
  parseMaxReconnectAttempts,
  DEFAULT_MAX_RECONNECT_ATTEMPTS,
  MAX_RECONNECT_ATTEMPTS,
};
