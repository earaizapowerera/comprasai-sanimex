/**
 * Placeholder elegante para pantallas aún no entregadas por su tarea dueña.
 * Sustituir por el componente real cuando la tarea correspondiente (T8-T11)
 * publique su pantalla — no bloquea la navegación mientras tanto.
 */
import { Link } from 'react-router-dom'

export default function Placeholder({ title, waykee, star }) {
  return (
    <>
      <header className="app-page-header">
        <h1 className="h1 app-page-header__title">
          {title} {star && <span aria-hidden="true">⭐</span>}
        </h1>
        <p className="app-page-header__subtitle">Vitrina de la demo ComprasAI Sanimex — Fase 1</p>
      </header>

      <div className="card empty">
        <div className="empty__icon" aria-hidden="true">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.3">
            <rect x="3" y="4" width="18" height="16" rx="2.5" />
            <path d="M3 9h18" />
            <path d="M8 4v5" />
          </svg>
        </div>
        <h3 className="h3">Próximamente</h3>
        <p className="body text-secondary" style={{ maxWidth: 420 }}>
          Esta pantalla está en construcción ({waykee}) como parte de la demo Fase 1. Mientras tanto,
          puedes explorar el <Link to="/chat">Chat del Planeador</Link> ✨ para preguntarle a los datos en
          lenguaje natural.
        </p>
      </div>
    </>
  )
}
