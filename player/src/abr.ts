/**
 * Controlador ABR (Adaptive Bitrate) Client-Side
 *
 * Implementa un controlador de bitrate adaptativo con historial de throughput
 * y lógica de histeresis para evitar flapping de rendition.
 *
 * La conmutación se produce en fronteras de grupo MoQ (IDR frames),
 * típicamente cada 2 segundos en la configuración de Fase 1.
 */

export interface AbrConfig {
  /** Número de muestras de throughput para la media móvil (default: 5) */
  window: number;
  /** Milisegundos de gracia antes de subir calidad (default: 3000) */
  hysteresisUp: number;
  /** Milisegundos de gracia antes de bajar calidad (default: 1000) */
  hysteresisDown: number;
}

export interface Rendition {
  /** Nombre de la rendition ("video-high" | "video-medium" | "video-low") */
  name: string;
  /** Bitrate en kbps */
  bitrate_kbps: number;
  /** Throughput mínimo (kbps) para activar esta rendition */
  threshold_up: number;
  /** Throughput por debajo del cual se baja de esta rendition */
  threshold_down: number;
}

/**
 * Renditions por defecto para Fase 1
 * Umbrales derivados de: issue #60
 */
export const DEFAULT_RENDITIONS: Rendition[] = [
  {
    name: 'video-high',
    bitrate_kbps: 2500,
    threshold_up: 4000,
    threshold_down: 3500,
  },
  {
    name: 'video-medium',
    bitrate_kbps: 1200,
    threshold_up: 2500,
    threshold_down: 2000,
  },
  {
    name: 'video-low',
    bitrate_kbps: 600,
    threshold_up: 0,
    threshold_down: 0,
  },
];

export class AbrController {
  private config: AbrConfig;
  private throughputSamples: number[] = []; // historial de throughput (kbps)
  private currentRendition: Rendition;
  private lastSuggestion: Rendition | null = null;
  private lastUpChangeTime: number = 0;
  private lastDownChangeTime: number = 0;

  constructor(
    defaultRendition: Rendition = DEFAULT_RENDITIONS[1], // video-medium por defecto
    config: Partial<AbrConfig> = {}
  ) {
    this.config = {
      window: config.window ?? 5,
      hysteresisUp: config.hysteresisUp ?? 3000,
      hysteresisDown: config.hysteresisDown ?? 1000,
    };
    this.currentRendition = defaultRendition;
  }

  /**
   * Añade una muestra de throughput al historial.
   * Calcula kbps a partir de bytes y duración.
   *
   * @param bytes Bytes decodificados en el periodo
   * @param durationMs Duración del periodo en milisegundos
   */
  public addSample(bytes: number, durationMs: number): void {
    if (durationMs <= 0) return;

    // Calcular throughput en kbps: (bytes * 8) / (durationMs / 1000) / 1000
    const kbps = (bytes * 8) / (durationMs / 1000) / 1000;

    this.throughputSamples.push(kbps);

    // Mantener solo las últimas N muestras
    if (this.throughputSamples.length > this.config.window) {
      this.throughputSamples.shift();
    }
  }

  /**
   * Calcula el throughput suavizado (media móvil).
   * Devuelve 0 si no hay muestras suficientes.
   */
  public getSmoothedThroughput(): number {
    if (this.throughputSamples.length < this.config.window) {
      return 0;
    }

    const sum = this.throughputSamples.reduce((a, b) => a + b, 0);
    return sum / this.throughputSamples.length;
  }

  /**
   * Selecciona la mejor rendition según el throughput suavizado.
   * Aplica lógica de histeresis para evitar flapping.
   *
   * @param renditions Array de renditions disponibles (debe estar ordenado de mayor a menor bitrate)
   * @returns La rendition seleccionada
   */
  public selectRendition(renditions: Rendition[]): Rendition {
    const throughput = this.getSmoothedThroughput();

    // Si no tenemos suficientes muestras, mantener la rendition actual
    if (throughput === 0) {
      return this.currentRendition;
    }

    const now = Date.now();
    let candidate = this.currentRendition;

    // Iterar de mayor a menor bitrate
    for (const rendition of renditions) {
      if (throughput >= rendition.threshold_up) {
        candidate = rendition;
        break;
      }
    }

    // Aplicar histeresis
    if (candidate.bitrate_kbps > this.currentRendition.bitrate_kbps) {
      // Intentar subir: requiere tiempo de gracia
      if (now - this.lastUpChangeTime < this.config.hysteresisUp) {
        return this.currentRendition;
      }
      this.lastUpChangeTime = now;
    } else if (candidate.bitrate_kbps < this.currentRendition.bitrate_kbps) {
      // Intentar bajar: requiere tiempo de gracia
      if (now - this.lastDownChangeTime < this.config.hysteresisDown) {
        return this.currentRendition;
      }
      this.lastDownChangeTime = now;
    }

    this.currentRendition = candidate;
    return candidate;
  }

  /**
   * Obtiene la rendition sugerida comparando con la actual.
   * Devuelve null si no hay cambio.
   *
   * @param renditions Array de renditions disponibles
   * @returns Rendition sugerida o null si es la misma que la actual
   */
  public getSuggestion(renditions: Rendition[]): Rendition | null {
    const suggested = this.selectRendition(renditions);

    if (suggested.name !== this.currentRendition.name) {
      this.lastSuggestion = suggested;
      return suggested;
    }

    return null;
  }

  /**
   * Obtiene el estado actual del controlador
   */
  public getState() {
    return {
      currentRendition: this.currentRendition.name,
      throughput_kbps: this.getSmoothedThroughput(),
      samplesCollected: this.throughputSamples.length,
      samplesNeeded: this.config.window,
      lastSuggestion: this.lastSuggestion?.name ?? null,
    };
  }

  /**
   * Limpia el historial de muestras (útil para reseteos)
   */
  public reset(): void {
    this.throughputSamples = [];
    this.lastUpChangeTime = 0;
    this.lastDownChangeTime = 0;
  }
}
