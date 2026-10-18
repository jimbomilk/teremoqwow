#!/usr/bin/env node

import * as Moq from '@moq/net';

// Parse arguments
const args = process.argv.slice(2);
let windowSeconds = 20;

for (let i = 0; i < args.length; i++) {
  if (args[i] === '--window' && i + 1 < args.length) {
    windowSeconds = parseInt(args[i + 1], 10);
    if (isNaN(windowSeconds) || windowSeconds < 1 || windowSeconds > 3600) {
      console.error(`ERROR: --window must be between 1 and 3600, got ${windowSeconds}`);
      process.exit(1);
    }
  }
}

// Configuration
const MOQ_URL = process.env.MOQ_URL || 'http://moq-relay:8090/';
const BROADCAST = process.env.BROADCAST || 'anon/live1-meta';
const TRACK = process.env.TRACK || 'heartbeat';

console.error(`[Observer] Connecting to ${MOQ_URL}`);
console.error(`[Observer] Broadcast: ${BROADCAST}, Track: ${TRACK}, Window: ${windowSeconds}s`);

/**
 * Lee todos los objetos JSON disponibles a través de múltiples grupos.
 * Usa el patrón Ordered.nextGroup() → GroupConsumer.readJson() para iterar.
 *
 * Detecta si el track se cierra mid-ventana y lo propaga como error.
 *
 * @param {Ordered} ordered - El reader ordenado del track
 * @param {number} deadline - Timestamp de fin de ventana
 * @returns {Promise<Array>} Array de objetos JSON leídos (o error si track cerrado)
 */
async function readJsonAcrossGroups(ordered, deadline) {
  const objects = [];

  // Monitorear cierre del track simultáneamente
  // IMPORTANTE: cuando ordered.closed se resuelve/rechaza, significa que el track
  // fue cerrado. Debemos detectarlo y propagarlo como error para interrumpir
  // lecturas en progreso.
  let trackClosedSignal = null;
  const trackClosedPromise = new Promise((resolve, reject) => {
    ordered.closed
      .then(
        (closeError) => {
          // Track closed; this resolves successfully
          trackClosedSignal = new Error(
            closeError ? `Track closed: ${closeError.message}` : 'Track closed'
          );
          reject(trackClosedSignal); // Reject so it wins in Promise.race()
        },
        (closeError) => {
          // Track closed with error; this rejects
          trackClosedSignal = new Error(
            closeError ? `Track closed: ${closeError.message}` : 'Track closed'
          );
          reject(trackClosedSignal);
        }
      )
      .catch(() => {
        // This should not be reached, but catch as safety
      });
  });

  while (Date.now() < deadline) {
    const timeRemaining = deadline - Date.now();
    if (timeRemaining <= 0) break;

    try {
      // Race: nextGroup, deadline timeout, O track closed
      const timeoutPromise = new Promise((_, reject) =>
        setTimeout(() => reject(new Error('nextGroup timeout')), timeRemaining)
      );

      const group = await Promise.race([
        ordered.nextGroup(),
        timeoutPromise,
        trackClosedPromise,  // Detecta cierre mid-ventana
      ]);

      if (!group) {
        // CRITICAL: According to @moq/net Ordered API, nextGroup() returns undefined
        // ONLY when track is closed, not when "no data available right now".
        // If we reach here before deadline (no timeout error thrown), it means:
        // - nextGroup() returned undefined (track closed)
        // - timeoutPromise did not reject (we still have time)
        // - trackClosedPromise did not throw (or threw but caught here as undefined)
        // This is a track closure that must be propagated as error, not silent break.
        if (trackClosedSignal) {
          throw trackClosedSignal;
        }
        throw new Error('Track closed: nextGroup() returned undefined before deadline');
      }

      // Read all JSON frames from this group, BUT race against deadline AND track closure
      // FIX #1: readJson() must not wait indefinitely past deadline
      // HIGH FIX: Must also race against trackClosedSignal to detect closure during read
      let obj;
      while (Date.now() < deadline) {
        const timeRemaining = deadline - Date.now();
        if (timeRemaining <= 0) break;

        const readTimeoutPromise = new Promise((_, reject) =>
          setTimeout(() => reject(new Error('readJson timeout')), timeRemaining)
        );

        try {
          obj = await Promise.race([
            group.readJson(),
            readTimeoutPromise,
            trackClosedPromise,  // HIGH FIX: Detect closure during readJson()
          ]);

          if (obj === undefined) {
            // Group exhausted, move to next group
            break;
          }
          objects.push(obj);
        } catch (readErr) {
          if (readErr.message.includes('readJson timeout')) {
            // Deadline expired while reading this group - stop reading and return
            throw new Error('readJson timeout');
          }
          if (readErr.message.includes('Track closed')) {
            // HIGH FIX: Closure detected during readJson - propagate immediately
            throw readErr;
          }
          throw readErr;
        }
      }
    } catch (err) {
      // Distinguir entre:
      // 1. Timeout de ventana → break (normal)
      // 2. Track cerrado → re-throw (error propagado)
      // 3. Timeout en readJson → break (deadline respetado)
      // 4. Otro error → re-throw (propagado)
      if (err.message === 'nextGroup timeout' || err.message.includes('nextGroup timeout')) {
        // Window expired, stop reading normally
        break;
      }
      if (err.message === 'readJson timeout' || err.message.includes('readJson timeout')) {
        // Deadline reached while reading group - this is normal deadline expiration
        break;
      }
      if (err.message.includes('Track closed')) {
        // Connection lost mid-window — ALWAYS propagate (FIX #2)
        // Even if deadline is close, closure error takes precedence
        throw err;
      }
      // Other errors: re-throw
      throw err;
    }
  }

  return objects;
}

/**
 * Observe track with optional injectable dependencies for testing
 * @param {object} options - Injectable dependencies
 * @param {Function} options.connect - Connection function (default: Moq.Connection.connect)
 * @param {object} options.origin - MoQ origin (default: new Moq.Origin.Producer())
 * @param {number} options.window - Override window seconds (default: env MOQ_WINDOW)
 * @param {Function} options.onResult - Callback for result JSON (default: console.log)
 */
async function observeTrack(options = {}) {
  let connection;

  // Define observeWindow at function scope so it's available in catch block
  const observeWindow = options.window || windowSeconds;

  try {
    const relayUrl = new URL(MOQ_URL);
    const broadcastPath = BROADCAST.replace(/^\/+/, '');

    // FIX #1: Reserve buffer for connection setup + reporting, but proportional to window
    // Minimum 500ms, maximum 2s, scaled: buffer = max(500, min(2000, window * 100))
    // For window=1s: buffer = 500ms (usable = 500ms)
    // For window=20s: buffer = 2000ms (usable = 18s)
    const reportingBufferMs = Math.max(500, Math.min(2000, observeWindow * 100));
    const deadline = Date.now() + (observeWindow * 1000) - reportingBufferMs;

    // Use injected origin or create new one
    const origin = options.origin || new Moq.Origin.Producer();

    // Use injected connect or Moq default
    const connectFn = options.connect || Moq.Connection.connect;

    // FIX #2: connectTimeout uses remaining observation budget (deadline - now)
    // with a conservative minimum. Allows healthy slow handshakes (up to 2s)
    // while ensuring we have time to read data after connect.
    // Min: 500ms (for very short windows), Max: 50% of remaining budget
    const remainingBudget = deadline - Date.now();
    const connectTimeoutMs = Math.max(500, Math.min(remainingBudget * 0.5, 5000));
    const connectController = new AbortController();
    const connectTimeoutHandle = setTimeout(() => connectController.abort(), connectTimeoutMs);

    try {
      connection = await Promise.race([
        connectFn({
          url: relayUrl,
          consume: origin,
          signal: connectController.signal,  // Propagate abort signal
        }),
        new Promise((_, reject) =>
          setTimeout(() => reject(new Error('Connection timeout')), connectTimeoutMs)
        ),
      ]);
    } finally {
      clearTimeout(connectTimeoutHandle);
    }

    const request = origin.request(Moq.Path.from(broadcastPath));
    let active = request.active.peek();

    // Wait for broadcast to be announced (with timeout)
    // Use Promise.race to apply timeout to the wait
    while (!active && Date.now() < deadline) {
      try {
        await Promise.race([
          request.active.changed(),
          new Promise((_, reject) =>
            setTimeout(() => reject(new Error('Timeout waiting for broadcast')),
              Math.max(0, deadline - Date.now()))
          ),
        ]);
      } catch (err) {
        if (err.message === 'Timeout waiting for broadcast' && Date.now() >= deadline) {
          break;
        }
        throw err;
      }
      active = request.active.peek();
    }

    if (!active) {
      throw new Error(`broadcast is not available: ${BROADCAST}`);
    }

    console.error(`[Observer] Connected and broadcast found!`);

    let objects = [];
    let firstSeq = null;
    let lastSeq = null;
    const bootIds = new Set();
    const seqByBootId = {};
    let monotonic = true;

    // Subscribe and read JSON across groups
    let subscriber;
    let ordered;
    let lastError;

    while (objects.length === 0 && Date.now() < deadline) {
      try {
        subscriber = active.track(TRACK).subscribe({ maxAge: windowSeconds * 1000 });
        ordered = subscriber.ordered();

        // Read all JSON objects across groups during observation window
        objects = await readJsonAcrossGroups(ordered, deadline);
      } catch (err) {
        lastError = err;
        if (subscriber) {
          try { subscriber.close(); } catch (e) { /* ignore */ }
        }
        if (Date.now() >= deadline) throw err;
        await new Promise(resolve => setTimeout(resolve, 200));
        // CRITICAL FIX #3: After retry sleep, check if deadline was crossed or if error was closure
        // If either happened, propagate error immediately instead of continuing
        if (Date.now() >= deadline || (lastError && lastError.message.includes('Track closed'))) {
          throw lastError || new Error('Deadline exceeded after retry sleep');
        }
      }
    }

    // CRITICAL FIX #3: Verify no closure error was silently swallowed before emitting success
    if (lastError && lastError.message.includes('Track closed')) {
      throw lastError;
    }

    // Process collected objects
    for (const obj of objects) {
      const data = JSON.stringify(obj);

      if (obj.boot_id && typeof obj.seq === 'number') {
        if (firstSeq === null) firstSeq = obj.seq;
        lastSeq = obj.seq;
        bootIds.add(obj.boot_id);

        if (!seqByBootId[obj.boot_id]) {
          seqByBootId[obj.boot_id] = [];
        }
        seqByBootId[obj.boot_id].push(obj.seq);
      }
    }

    // Check monotonicity per boot_id
    for (const seqs of Object.values(seqByBootId)) {
      for (let i = 1; i < seqs.length; i++) {
        if (seqs[i] <= seqs[i - 1]) {
          monotonic = false;
          break;
        }
      }
      if (!monotonic) break;
    }

    const bytes = objects.reduce((sum, obj) => sum + JSON.stringify(obj).length, 0);

    console.error(`[Observer] Observation complete: ${objects.length} objects, ${bytes} bytes`);

    // Emit result JSON
    const result = {
      connected: true,
      objects: objects.length,
      bytes,
      first_seq: firstSeq !== null ? firstSeq : 0,
      last_seq: lastSeq !== null ? lastSeq : 0,
      boot_ids: Array.from(bootIds),
      monotonic,
      window_seconds: observeWindow,
    };

    // Use injected callback or default console.log
    const emit = options.onResult || ((r) => console.log(JSON.stringify(r)));
    emit(result);

    // Cleanup
    if (subscriber) {
      try { subscriber.close(); } catch (e) { /* ignore */ }
    }
    if (connection) {
      try { connection.close(); } catch (e) { /* ignore */ }
    }
  } catch (err) {
    console.error(`[Observer] Error: ${err.message}`);

    // Emit failure result
    const result = {
      connected: false,
      objects: 0,
      bytes: 0,
      first_seq: 0,
      last_seq: 0,
      boot_ids: [],
      monotonic: false,
      window_seconds: observeWindow,
    };

    // Use injected callback or default console.log
    const emit = options.onResult || ((r) => console.log(JSON.stringify(r)));
    emit(result);

    // Cleanup on error
    if (connection) {
      try { connection.close(); } catch (e) { /* ignore */ }
    }
  }
}

// Export for testing
export { observeTrack, readJsonAcrossGroups };
