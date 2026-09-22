// Load local fonts and mount the routed SmartRoute workspace.
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import '@fontsource-variable/manrope'
import '@fontsource-variable/jetbrains-mono'
import AuthGate from './components/AuthGate'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter><AuthGate /></BrowserRouter>
  </StrictMode>,
)
