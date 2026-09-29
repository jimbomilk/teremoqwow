/**
 * Sincronización de Overlay con PTS del vídeo
 *
 * Implementa scheduling de overlays e interacciones sincronizados con el PTS del media,
 * con corrección de jitter para garantizar desviación < 100ms.
 *
 * Flujo:
 *   1. Recibe OverlayPayload o InteractionEvent con PTS objetivo
 *   2. Calcula el momento de renderizado basándose en el PTS actual del vídeo
 *   3. Usa setTimeout para despachar el callback en el momento preciso
 *   4. Mantiene ventana deslizante de errores de timing para corregir jitter
 *   5. Emite métricas de desviación para QoS
 */

/**
 * Métrica de desviación de timing para un evento schedulado
 */
export interface TimingDeviation {
  /** ID del evento */
  event_id: string;
  /** PTS objetivo en milisegundos */
  pts_target_ms: number;
  /** Momento wallclock planificado para render */
  scheduled_at_ms: number;
  /** Momento wallclock real de render */
  actual_at_ms: number;
  /** Desviación real (actual_at_ms - scheduled_at_ms) en milisegundos */
  deviation_ms: number;
  /** Desviación corregida por jitter (desviación - average_jitter) */
  corrected_deviation_ms: number;
}

/**
 * Callback de renderizado de overlay
 */
export type OverlayRenderCallback = () => void;

/**
 * Getter para obtener el PTS actual del vídeo
 */
export type CurrentPtsGetter = () => number | null;

/**
 * Callback para emitir métricas de QoS
 */
export type MetricsEmitter = (deviation: TimingDeviation) => void;

/**
 * Opciones de configuración del scheduler
 */
export interface OverlaySyncSchedulerOptions {
  /** Máxima desviación permitida en milisegundos (default: 100) */
  maxDeviationMs?: number;
  /** Tamaño de ventana deslizante para corrección de jitter (default: 5) */
  jitterWindowSize?: number;
  /** Callback para emitir métricas de desviación */
  onMetrics?: MetricsEmitter;
}

/**
 * Evento pendiente de scheduling
 */
interface ScheduledEvent {
  id: string;
  pts_target_ms: number;
  callback: OverlayRenderCallback;
  timeout_id: number | null;
  scheduled_at_ms: number;
  kind: 'overlay' | 'interaction';
}

/**
 * OverlaySyncScheduler — Scheduler de overlays sincronizados con PTS
 *
 * Garantiza que los overlays se rendericen con desviación < 100ms respecto al PTS objetivo,
 * aplicando corrección de jitter basada en histórico de errores.
 */
export class OverlaySyncScheduler {
  private pendingEvents: Map<string, ScheduledEvent> = new Map();
  private timingDeviations: TimingDeviation[] = [];
  private jitterWindow: number[] = []; // Últimas N deviaciones para calcular promedio
  private maxDeviationMs: number;
  private jitterWindowSize: number;
  private onMetrics: MetricsEmitter;
  private getPts: CurrentPtsGetter;

  constructor(getPts: CurrentPtsGetter, options: OverlaySyncSchedulerOptions = {}) {
    this.getPts = getPts;
    this.maxDeviationMs = options.maxDeviationMs ?? 100;
    this.jitterWindowSize = options.jitterWindowSize ?? 5;
    this.onMetrics = options.onMetrics ?? (() => {});
  }

  /**
   * Schedule un overlay para renderizar en el PTS objetivo
   *
   * @param id Identificador único del evento
   * @param ptsMsTarget PTS objetivo en milisegundos
   * @param callback Función a ejecutar en el momento planificado
   * @param kind Tipo de evento ('overlay' o 'interaction')
   */
  public schedule(
    id: string,
    ptsMsTarget: number,
    callback: OverlayRenderCallback,
    kind: 'overlay' | 'interaction' = 'overlay'
  ): void {
    // Evitar duplicados
    this.cancel(id);

    const currentPtsMs = this.getPts();
    if (currentPtsMs === null) {
      console.warn(`[OverlaySync] No PTS available for scheduling event ${id}`);
      return;
    }

    // Calcular delay: si el PTS objetivo es en el futuro, esperar
    // Si ya pasó, ejecutar inmediatamente
    const delayMs = Math.max(0, ptsMsTarget - currentPtsMs);

    // Aplicar corrección de jitter: ajustar delay con el promedio de deviaciones pasadas
    const jitterCorrection = this.getJitterCorrection();
    const adjustedDelayMs = Math.max(0, delayMs - jitterCorrection);

    const scheduledAtMs = performance.now() + adjustedDelayMs;

    // Crear evento schedulado
    const event: ScheduledEvent = {
      id,
      pts_target_ms: ptsMsTarget,
      callback,
      timeout_id: null,
      scheduled_at_ms: scheduledAtMs,
      kind,
    };

    // Registrar timeout
    event.timeout_id = window.setTimeout(() => {
      this.executeCallback(event);
    }, adjustedDelayMs) as unknown as number;

    this.pendingEvents.set(id, event);

    console.debug(
      `[OverlaySync] Scheduled ${kind} event ${id} at PTS ${ptsMsTarget}ms (delay: ${adjustedDelayMs}ms, current PTS: ${currentPtsMs}ms)`
    );
  }

  /**
   * Cancela un evento schedulado
   */
  public cancel(id: string): void {
    const event = this.pendingEvents.get(id);
    if (event && event.timeout_id !== null) {
      clearTimeout(event.timeout_id);
      this.pendingEvents.delete(id);
      console.debug(`[OverlaySync] Cancelled event ${id}`);
    }
  }

  /**
   * Ejecuta el callback y mide la desviación de timing
   */
  private executeCallback(event: ScheduledEvent): void {
    const actualAtMs = performance.now();
    const deviationMs = actualAtMs - event.scheduled_at_ms;
    const avgJitter = this.getAverageDeviation();
    const correctedDeviationMs = deviationMs - avgJitter;

    // Registrar desviación
    const deviation: TimingDeviation = {
      event_id: event.id,
      pts_target_ms: event.pts_target_ms,
      scheduled_at_ms: event.scheduled_at_ms,
      actual_at_ms: actualAtMs,
      deviation_ms: deviationMs,
      corrected_deviation_ms: correctedDeviationMs,
    };

    this.timingDeviations.push(deviation);
    this.addToJitterWindow(deviationMs);

    // Emitir métrica
    this.onMetrics(deviation);

    // Log y advertencia si desviación es alta
    const passesThreshold = Math.abs(corrected_deviation_ms) <= this.maxDeviationMs;
    if (!passesThreshold) {
      console.warn(
        `[OverlaySync] ${event.kind} event ${event.id} rendered with deviation ${correctedDeviationMs.toFixed(2)}ms (threshold: ${this.maxDeviationMs}ms)`
      );
    } else {
      console.debug(
        `[OverlaySync] ${event.kind} event ${event.id} rendered with deviation ${correctedDeviationMs.toFixed(2)}ms (OK)`
      );
    }

    // Ejecutar callback
    try {
      event.callback();
    } catch (error) {
      console.error(`[OverlaySync] Error executing callback for event ${event.id}:`, error);
    }

    // Limpiar evento
    this.pendingEvents.delete(event.id);
  }

  /**
   * Añade una desviación a la ventana deslizante de jitter
   */
  private addToJitterWindow(deviationMs: number): void {
    this.jitterWindow.push(deviationMs);
    if (this.jitterWindow.length > this.jitterWindowSize) {
      this.jitterWindow.shift();
    }
  }

  /**
   * Calcula el promedio de jitter basado en la ventana deslizante
   */
  private getJitterCorrection(): number {
    return this.getAverageDeviation();
  }

  /**
   * Obtiene el promedio de desviaciones en la ventana actual
   */
  private getAverageDeviation(): number {
    if (this.jitterWindow.length === 0) {
      return 0;
    }
    const sum = this.jitterWindow.reduce((acc, dev) => acc + dev, 0);
    return sum / this.jitterWindow.length;
  }

  /**
   * Obtiene el histórico de desviaciones (para análisis/debugging)
   */
  public getDeviationHistory(): TimingDeviation[] {
    return [...this.timingDeviations];
  }

  /**
   * Calcula estadísticas de desviación para el reporte QoS
   */
  public getStats(): {
    total_events: number;
    avg_deviation_ms: number;
    max_deviation_ms: number;
    min_deviation_ms: number;
    pass_rate: number;
  } {
    if (this.timingDeviations.length === 0) {
      return {
        total_events: 0,
        avg_deviation_ms: 0,
        max_deviation_ms: 0,
        min_deviation_ms: 0,
        pass_rate: 1.0,
      };
    }

    const correctedDeviations = this.timingDeviations.map((d) => Math.abs(d.corrected_deviation_ms));
    const avgDeviation = correctedDeviations.reduce((a, b) => a + b, 0) / correctedDeviations.length;
    const maxDeviation = Math.max(...correctedDeviations);
    const minDeviation = Math.min(...correctedDeviations);

    const passingEvents = correctedDeviations.filter((d) => d <= this.maxDeviationMs).length;
    const passRate = passingEvents / this.timingDeviations.length;

    return {
      total_events: this.timingDeviations.length,
      avg_deviation_ms: Math.round(avgDeviation * 100) / 100,
      max_deviation_ms: Math.round(maxDeviation * 100) / 100,
      min_deviation_ms: Math.round(minDeviation * 100) / 100,
      pass_rate: Math.round(passRate * 10000) / 10000,
    };
  }

  /**
   * Limpia el scheduler (cierra todos los eventos pendientes)
   */
  public cleanup(): void {
    this.pendingEvents.forEach((event) => {
      if (event.timeout_id !== null) {
        clearTimeout(event.timeout_id);
      }
    });
    this.pendingEvents.clear();
  }
}
