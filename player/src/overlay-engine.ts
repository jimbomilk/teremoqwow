// Dispatcher de overlays — recibe OverlayCommand del track MoQ y gestiona iframes por zona

export type OverlayZone =
  | 'top-left' | 'top-center' | 'top-right'
  | 'middle-left' | 'center' | 'middle-right'
  | 'bottom-left' | 'bottom-center' | 'bottom-right'
  | 'bottom-bar' | 'top-bar' | 'full';

export interface ActiveOverlay {
  id: string;
  zone: OverlayZone;
  templateId: string;
  iframe: HTMLIFrameElement;
  container: HTMLDivElement;
  dismissTimer: ReturnType<typeof setTimeout> | null;
}

export class OverlayEngine {
  private _active = new Map<string, ActiveOverlay>(); // key: overlay_id
  private _zoneMap = new Map<OverlayZone, string>();  // zone → overlay_id
  private _root: HTMLElement;
  private _templatesBase: string;

  constructor(root: HTMLElement, templatesBase = '/overlays/templates') {
    this._root = root;
    this._templatesBase = templatesBase;
  }

  async publish(payload: {
    id: string;
    template_id: string;
    zone: OverlayZone;
    duration_ms: number;
    animation?: string;
    data: Record<string, unknown>;
    style_overrides?: Record<string, unknown>;
  }): Promise<void> {
    // 1. Si hay un overlay en esa zona → unpublish el anterior
    if (this._zoneMap.has(payload.zone)) {
      this.unpublish(this._zoneMap.get(payload.zone)!);
    }

    // 2. Crear contenedor posicionado
    const container = this._createContainer(payload.zone, payload.animation);

    // 3. Crear iframe sandboxed
    const iframe = document.createElement('iframe') as HTMLIFrameElement;
    iframe.setAttribute('sandbox', 'allow-scripts');
    iframe.setAttribute('title', `overlay-${payload.template_id}`);
    iframe.style.cssText = 'width:100%;height:100%;border:none;background:transparent;';
    iframe.src = `${this._templatesBase}/${payload.template_id}/index.html`;

    container.appendChild(iframe);
    this._root.appendChild(container);

    // 4. Cuando el iframe esté listo, enviar los datos
    const sendData = () => {
      iframe.contentWindow?.postMessage({
        type: 'overlay:data',
        payload: payload.data,
        styleOverrides: payload.style_overrides ?? {},
        animation: payload.animation ?? 'fade',
      }, '*');
    };
    iframe.addEventListener('load', sendData, { once: true });

    // 5. Registrar
    const active: ActiveOverlay = {
      id: payload.id,
      zone: payload.zone,
      templateId: payload.template_id,
      iframe,
      container: container as HTMLDivElement,
      dismissTimer: null,
    };

    if (payload.duration_ms > 0) {
      active.dismissTimer = setTimeout(() => this.unpublish(payload.id), payload.duration_ms);
    }

    this._active.set(payload.id, active);
    this._zoneMap.set(payload.zone, payload.id);
  }

  unpublish(overlayId: string): void {
    const ov = this._active.get(overlayId);
    if (!ov) return;
    if (ov.dismissTimer) clearTimeout(ov.dismissTimer);
    ov.container.style.opacity = '0';
    ov.container.style.transition = 'opacity 0.4s';
    setTimeout(() => ov.container.remove(), 450);
    this._active.delete(overlayId);
    this._zoneMap.delete(ov.zone);
  }

  unpublishZone(zone: OverlayZone): void {
    const id = this._zoneMap.get(zone);
    if (id) this.unpublish(id);
  }

  clearAll(): void {
    for (const id of [...this._active.keys()]) {
      this.unpublish(id);
    }
  }

  activeCount(): number { return this._active.size; }

  activeIds(): string[] { return [...this._active.keys()]; }

  // Verifica si una WindowProxy pertenece a algún iframe gestionado por el engine
  isKnownSource(source: WindowProxy): boolean {
    for (const ov of this._active.values()) {
      if (ov.iframe.contentWindow === source) return true;
    }
    return false;
  }

  private _createContainer(zone: OverlayZone, animation?: string): HTMLDivElement {
    const div = document.createElement('div') as HTMLDivElement;
    div.style.position = 'absolute';
    div.style.zIndex = '100';
    div.style.transition = animation !== 'none' ? 'opacity 0.3s' : '';

    const zoneStyles: Record<OverlayZone, string> = {
      'top-left':      'top:1%;left:1%;width:25%;height:auto;',
      'top-center':    'top:1%;left:50%;transform:translateX(-50%);width:40%;',
      'top-right':     'top:1%;right:1%;width:25%;height:auto;',
      'middle-left':   'top:50%;left:1%;transform:translateY(-50%);width:25%;',
      'center':        'top:50%;left:50%;transform:translate(-50%,-50%);width:40%;',
      'middle-right':  'top:50%;right:1%;transform:translateY(-50%);width:25%;',
      'bottom-left':   'bottom:8%;left:1%;width:25%;height:auto;',
      'bottom-center': 'bottom:8%;left:50%;transform:translateX(-50%);width:40%;',
      'bottom-right':  'bottom:8%;right:1%;width:25%;height:auto;',
      'bottom-bar':    'bottom:0;left:0;width:100%;height:60px;',
      'top-bar':       'top:0;left:0;width:100%;height:60px;',
      'full':          'top:0;left:0;width:100%;height:100%;',
    };
    div.style.cssText += zoneStyles[zone] ?? '';
    return div;
  }
}
