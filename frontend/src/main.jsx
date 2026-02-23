import React from 'react'
import ReactDOM from 'react-dom/client'
import { Toaster } from 'sonner'
import App from './App.jsx'
import ErrorBoundary from './components/ErrorBoundary.jsx'
import { initTheme } from './utils/theme'
import './index.css'

initTheme()

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
      <Toaster richColors position="top-right" closeButton />
    </ErrorBoundary>
  </React.StrictMode>,
)
