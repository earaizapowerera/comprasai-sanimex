import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App.jsx'

// Orden de importación obligatorio (ver UX-SPEC.md §6): tokens -> componentes -> shell/pantallas.
import '../../design/design-tokens.css'
import '../../design/components.css'
import './styles/shell.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter basename={import.meta.env.BASE_URL}>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
)
