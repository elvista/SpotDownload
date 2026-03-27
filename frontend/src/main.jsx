import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { Toaster } from 'sonner'
import App from './App.jsx'
import ErrorBoundary from './components/ErrorBoundary.jsx'
import { HeaderProvider } from './context/HeaderContext.jsx'
import { initTheme } from './utils/theme'
import './index.css'

initTheme()

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ErrorBoundary>
      <BrowserRouter>
        <HeaderProvider>
          <App />
          <Toaster richColors position="top-right" closeButton />
        </HeaderProvider>
      </BrowserRouter>
    </ErrorBoundary>
  </React.StrictMode>,
)
