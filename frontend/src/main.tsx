import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

const mountNode = document.getElementById('app-root') ?? document.getElementById('root')

if (!mountNode) {
  throw new Error('React mount node not found.')
}

createRoot(mountNode).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
