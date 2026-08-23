// Iconos inline (stroke 1.75, 20x20) — evita dependencia de una librería de íconos
// para mantener el bundle ligero. Estilo consistente: trazo redondeado, sin relleno.
const base = {
  width: 20,
  height: 20,
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.75,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
}

export const IconDashboard = (p) => (
  <svg {...base} {...p}>
    <rect x="3" y="3" width="7" height="9" rx="1.5" />
    <rect x="14" y="3" width="7" height="5" rx="1.5" />
    <rect x="14" y="12" width="7" height="9" rx="1.5" />
    <rect x="3" y="16" width="7" height="5" rx="1.5" />
  </svg>
)

export const IconBox = (p) => (
  <svg {...base} {...p}>
    <path d="M3.5 7.5 12 3l8.5 4.5v9L12 21l-8.5-4.5v-9Z" />
    <path d="M3.5 7.5 12 12l8.5-4.5" />
    <path d="M12 12v9" />
  </svg>
)

export const IconCart = (p) => (
  <svg {...base} {...p}>
    <circle cx="9" cy="20" r="1.4" />
    <circle cx="17" cy="20" r="1.4" />
    <path d="M2.5 3h2l2.4 12.2a1.8 1.8 0 0 0 1.78 1.5h8.1a1.8 1.8 0 0 0 1.77-1.44L20.5 7.5H6" />
  </svg>
)

export const IconShuffle = (p) => (
  <svg {...base} {...p}>
    <path d="M3 6h3.6c1 0 1.9.53 2.42 1.38L15 18.6c.52.85 1.42 1.4 2.42 1.4H21" />
    <path d="M17 3h4v4M3 18h3.6c1 0 1.9-.53 2.42-1.38L11 12" />
    <path d="M17 21h4v-4" />
  </svg>
)

export const IconTrafficLight = (p) => (
  <svg {...base} {...p}>
    <rect x="8" y="2" width="8" height="18" rx="4" />
    <circle cx="12" cy="6.5" r="1.3" fill="currentColor" stroke="none" />
    <circle cx="12" cy="11" r="1.3" fill="currentColor" stroke="none" />
    <circle cx="12" cy="15.5" r="1.3" fill="currentColor" stroke="none" />
    <path d="M9 22h6" />
  </svg>
)

export const IconSparkleChat = (p) => (
  <svg {...base} {...p}>
    <path d="M4 4.5h11a2 2 0 0 1 2 2V13a2 2 0 0 1-2 2H10l-4 3v-3H4a2 2 0 0 1-2-2V6.5a2 2 0 0 1 2-2Z" />
    <path d="M18.5 2.5v3M17 4h3" />
    <path d="M19.5 14.5v2.4M18.3 15.7h2.4" />
  </svg>
)

export const IconSun = (p) => (
  <svg {...base} {...p}>
    <circle cx="12" cy="12" r="4.2" />
    <path d="M12 2.5v2.2M12 19.3v2.2M4.2 4.2l1.6 1.6M18.2 18.2l1.6 1.6M2.5 12h2.2M19.3 12h2.2M4.2 19.8l1.6-1.6M18.2 5.8l1.6-1.6" />
  </svg>
)

export const IconMoon = (p) => (
  <svg {...base} {...p}>
    <path d="M20 14.2A8.5 8.5 0 1 1 9.8 4a6.8 6.8 0 0 0 10.2 10.2Z" />
  </svg>
)

export const IconCollapse = (p) => (
  <svg {...base} {...p}>
    <rect x="3" y="4" width="18" height="16" rx="2.5" />
    <path d="M9.5 4v16" />
    <path d="M6.3 10.3 4.6 12l1.7 1.7" />
  </svg>
)

export const IconSearch = (p) => (
  <svg {...base} {...p}>
    <circle cx="11" cy="11" r="6.5" />
    <path d="m20 20-3.4-3.4" />
  </svg>
)

export const IconSend = (p) => (
  <svg {...base} {...p}>
    <path d="M21 3 3 10.5l7 2.5 2.5 7L21 3Z" />
    <path d="M12.5 13 21 3" />
  </svg>
)

export const IconUser = (p) => (
  <svg {...base} {...p}>
    <circle cx="12" cy="8.2" r="3.4" />
    <path d="M4.8 20c1.2-3.6 4-5.5 7.2-5.5s6 1.9 7.2 5.5" />
  </svg>
)
