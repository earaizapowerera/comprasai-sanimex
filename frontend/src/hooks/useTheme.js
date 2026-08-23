import { useCallback, useEffect, useState } from 'react'

const STORAGE_KEY = 'comprasai-theme'

function readInitialTheme() {
  if (typeof window === 'undefined') return null
  const saved = window.localStorage.getItem(STORAGE_KEY)
  return saved === 'light' || saved === 'dark' ? saved : null
}

/** Tema persistente en localStorage; sin preferencia explícita respeta el SO (ver design-tokens.css). */
export function useTheme() {
  const [theme, setTheme] = useState(readInitialTheme)

  useEffect(() => {
    if (theme) {
      document.documentElement.setAttribute('data-theme', theme)
      window.localStorage.setItem(STORAGE_KEY, theme)
    } else {
      document.documentElement.removeAttribute('data-theme')
      window.localStorage.removeItem(STORAGE_KEY)
    }
  }, [theme])

  const toggle = useCallback(() => {
    setTheme((current) => {
      if (current === 'dark') return 'light'
      if (current === 'light') return 'dark'
      // Sin preferencia guardada: alterna respecto a lo que el SO esté mostrando ahora.
      const prefersDark = window.matchMedia?.('(prefers-color-scheme: dark)').matches
      return prefersDark ? 'light' : 'dark'
    })
  }, [])

  return { theme, toggle }
}
