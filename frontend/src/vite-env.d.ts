/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** "true" → use the in-browser mock API (src/mocks) instead of the FastAPI backend. */
  readonly VITE_USE_MOCKS?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
