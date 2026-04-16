/// <reference types="vite/client" />

import type { AppConfig, InitialData } from './types'

declare global {
  interface Window {
    __APP_CONFIG__?: AppConfig
    __INITIAL_DATA__?: InitialData
  }
}

export {}
