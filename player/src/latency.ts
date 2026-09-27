/**
 * Cálculo de latencia glass-to-glass (PTS → render)
 *
 * La latencia se estima como:
 *   latency_ms = (wallclock_now - pts_timestamp) - offset_ntp
 *
 * donde:
 *   - wallclock_now: performance.now() en milisegundos (reloj local)
 *   - pts_timestamp: timestamp del frame en nanosegundos (PTS de MoQ, wallclock NTP)
 *   - offset_ntp: sincronización NTP estimada entre reloj local y servidor
 *
 * Phase 0 aproximación:
 *   - Asumimos que el catálogo proporciona `created_at` con `wallclock_ns` y `source: "ntp"`
 *   - Calculamos offset_ntp = (created_at_wallclock_ns / 1e6) - performance.now()
 *   - En cada frame, latency_ms ≈ (wallclock_now - pts_ms) - offset_ntp
 */

export interface LatencyMetrics {
  /** Latencia estimada glass-to-glass en milisegundos */
  latency_ms: number;
  /** Timestamp PTS del frame en milisegundos (convertido de nanosegundos) */
  pts_ms: number;
  /** Timestamp local (performance.now()) cuando se renderizó el frame */
  render_ts_ms: number;
  /** Offset NTP estimado para sincronización */
  ntp_offset_ms: number;
}

/**
 * Calcula el offset NTP usando el timestamp del catálogo.
 * Asume que `created_at.wallclock_ns` es un timestamp NTP absoluto.
 *
 * @param created_at_wallclock_ns - Timestamp NTP del catálogo en nanosegundos
 * @returns Offset NTP en milisegundos
 */
export function estimateNTPOffset(created_at_wallclock_ns: number): number {
  const created_at_ms = created_at_wallclock_ns / 1e6;
  const now_ms = performance.now();
  // Si el catálogo se creó hace poco, el offset refleja la diferencia entre
  // el reloj NTP del servidor y el reloj local.
  return created_at_ms - now_ms;
}

/**
 * Calcula la latencia glass-to-glass para un frame.
 *
 * @param frame_pts_ns - PTS del frame en nanosegundos (wallclock NTP del servidor)
 * @param ntp_offset_ms - Offset NTP estimado
 * @returns LatencyMetrics con la latencia calculada
 */
export function calculateLatency(frame_pts_ns: number, ntp_offset_ms: number): LatencyMetrics {
  const render_ts_ms = performance.now();
  const pts_ms = frame_pts_ns / 1e6;

  // latency_ms = (local_now - pts_remote) - offset
  // Esto aproxima: tiempo transcurrido desde que el servidor generó el frame
  // menos la diferencia de relojes.
  const latency_ms = render_ts_ms - pts_ms - ntp_offset_ms;

  return {
    latency_ms: Math.max(0, latency_ms), // No puede ser negativa
    pts_ms,
    render_ts_ms,
    ntp_offset_ms,
  };
}

/**
 * Formatea latencia para display.
 */
export function formatLatency(latency_ms: number): string {
  if (latency_ms < 0 || !isFinite(latency_ms)) {
    return '-- ms';
  }
  return `${Math.round(latency_ms)} ms`;
}
