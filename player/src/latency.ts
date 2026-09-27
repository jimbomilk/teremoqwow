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
 * **Catálogo Real (v1)**:
 *   El catálogo real proporciona `clock` con:
 *   - `clock.wall`: integer, microsegundos desde epoch UTC (1e6 = 1 segundo)
 *   - `clock.timescale`: integer, default 1000000 (divisor para convertir a segundos)
 *
 *   Para obtener offset NTP:
 *   - wallclock_ns = clock.wall * (1_000_000 / clock.timescale)
 *   - offset_ntp = (wallclock_ns / 1e6) - performance.now()
 *
 *   Alternativamente, si clock.wall ya está en microsegundos (timescale=1e6):
 *   - offset_ntp = (clock.wall / 1000) - performance.now()
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
 * Calcula el offset NTP usando el clock del catálogo real.
 *
 * Acepta tanto el formato antiguo (`wallclock_ns` en nanosegundos) como el real
 * con `clock.wall` (microsegundos) y `clock.timescale`.
 *
 * @param clockWallOrWallclockNs - clock.wall (microsegundos) o wallclock_ns (nanosegundos)
 * @param timescale - Divisor del clock (default 1000000 = microsegundos)
 * @returns Offset NTP en milisegundos
 */
export function estimateNTPOffset(
  clockWallOrWallclockNs: number,
  timescale: number = 1000000
): number {
  // Convertir clock.wall (microsegundos) o wallclock_ns (nanosegundos) a milisegundos
  let catalog_ms: number;

  if (clockWallOrWallclockNs > 1e12) {
    // Probablemente nanosegundos (muy grande para microsegundos)
    catalog_ms = clockWallOrWallclockNs / 1e6;
  } else {
    // Probablemente microsegundos, aplicar timescale
    catalog_ms = (clockWallOrWallclockNs * 1000) / timescale;
  }

  const now_ms = performance.now();

  // El offset refleja la diferencia entre el reloj NTP del servidor (catalog)
  // y el reloj local (performance.now).
  // Si catalog_ms > now_ms, el servidor está adelantado.
  return catalog_ms - now_ms;
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
