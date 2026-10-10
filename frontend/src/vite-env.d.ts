/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_USE_FIXTURES?: string;
  readonly VITE_FIXTURE_SET?: string;
  /** API mode only: stored (default), replay (P1 discovery from its cassette) or live (P1 discovery on Ethereum now). */
  readonly VITE_DISCOVERY?: string;
}
