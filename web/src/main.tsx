import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

// The level is not kept on the device any more (#91): the key an earlier build left goes.
try {
  localStorage.removeItem('dm-level')
} catch {
  // storage blocked: there is nothing to remove
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
