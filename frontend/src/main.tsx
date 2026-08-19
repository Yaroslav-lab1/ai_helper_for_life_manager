import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { applyResolvedTheme, resolveTheme, storedTheme } from './lib/theme'
import './styles.css'

applyResolvedTheme(resolveTheme(storedTheme(), window.matchMedia('(prefers-color-scheme: dark)').matches))

createRoot(document.getElementById('root')!).render(
  <StrictMode><App /></StrictMode>,
)
