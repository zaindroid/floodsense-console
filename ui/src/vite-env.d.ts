/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL: string;
  readonly VITE_API_TIMEOUT_MS?: string;
  readonly VITE_REPLAY_RUN_ID?: string;
  readonly VITE_ASK_CONTEXT?: string;
  readonly VITE_AHR_SOURCE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
