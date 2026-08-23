import { useEffect, useState } from 'react'
import { NavLink } from 'react-router-dom'
import { useTheme } from '../hooks/useTheme.js'
import {
  IconDashboard,
  IconBox,
  IconCart,
  IconShuffle,
  IconTrafficLight,
  IconSparkleChat,
  IconSun,
  IconMoon,
  IconCollapse,
  IconSearch,
  IconUser,
} from './icons.jsx'

const NAV_ITEMS = [
  { to: '/', label: 'Dashboard', icon: IconDashboard, end: true },
  { to: '/inventarios', label: 'Inventarios', icon: IconBox },
  { to: '/sugeridos', label: 'Sugeridos', icon: IconCart },
  { to: '/balanceos', label: 'Balanceos', icon: IconShuffle },
  { to: '/semaforo', label: 'Semáforo', icon: IconTrafficLight },
  { to: '/chat', label: 'Chat', icon: IconSparkleChat, ai: true },
]

const COLLAPSE_KEY = 'comprasai-sidebar-collapsed'

export default function Shell({ children }) {
  const { theme, toggle } = useTheme()
  const [collapsed, setCollapsed] = useState(
    () => typeof window !== 'undefined' && window.localStorage.getItem(COLLAPSE_KEY) === '1',
  )
  const isDark = theme === 'dark' || (!theme && window.matchMedia?.('(prefers-color-scheme: dark)').matches)

  useEffect(() => {
    window.localStorage.setItem(COLLAPSE_KEY, collapsed ? '1' : '0')
  }, [collapsed])

  return (
    <div className={`app-shell ${collapsed ? 'app-shell--collapsed' : ''}`}>
      <header className="app-topbar">
        <div className="app-topbar__brand">
          <span className="app-topbar__logo" aria-hidden="true">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
              <path
                d="M12 2 3 6.5v11L12 22l9-4.5v-11L12 2Z"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinejoin="round"
              />
              <path d="M3 6.5 12 11l9-4.5M12 11v11" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
            </svg>
          </span>
          <span className="app-topbar__title">ComprasAI</span>
          <span className="app-topbar__subtitle">Sanimex</span>
        </div>

        <button type="button" className="app-topbar__search" aria-label="Buscar (⌘K)">
          <IconSearch />
          <span>Buscar…</span>
          <kbd>⌘K</kbd>
        </button>

        <div className="app-topbar__actions">
          <button
            type="button"
            className="app-icon-btn"
            onClick={toggle}
            aria-label={isDark ? 'Cambiar a tema claro' : 'Cambiar a tema oscuro'}
            title={isDark ? 'Tema claro' : 'Tema oscuro'}
          >
            {isDark ? <IconSun /> : <IconMoon />}
          </button>
          <div className="app-avatar" title="Planeador · Demo">
            <IconUser />
          </div>
        </div>
      </header>

      <div className="app-body">
        <nav className="app-sidebar" aria-label="Navegación principal">
          <ul className="app-nav">
            {NAV_ITEMS.map(({ to, label, icon: Icon, end, ai }) => (
              <li key={to}>
                <NavLink
                  to={to}
                  end={end}
                  className={({ isActive }) =>
                    `app-nav__item ${isActive ? 'app-nav__item--active' : ''} ${ai ? 'app-nav__item--ai' : ''}`
                  }
                >
                  <Icon className="app-nav__icon" />
                  <span className="app-nav__label">{label}</span>
                  {ai && <span className="app-nav__spark" aria-hidden="true">✨</span>}
                </NavLink>
              </li>
            ))}
          </ul>

          <button
            type="button"
            className="app-sidebar__collapse"
            onClick={() => setCollapsed((v) => !v)}
            aria-label={collapsed ? 'Expandir menú' : 'Colapsar menú'}
          >
            <IconCollapse />
            <span className="app-nav__label">Colapsar</span>
          </button>
        </nav>

        <main className="app-content">{children}</main>
      </div>
    </div>
  )
}
