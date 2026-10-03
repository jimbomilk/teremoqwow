/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_MOQ_RELAY_URL?: string;
  readonly VITE_RELAY_BROADCAST?: string;
  readonly VITE_MOQ_CERT_HASH?: string;
  readonly VITE_HTTPS?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
