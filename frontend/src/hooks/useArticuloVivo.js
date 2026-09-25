import { useEffect, useState } from 'react'
import { api } from '../lib/api.js'

/** Lectura en vivo (HANA) de un artículo, opcionalmente de un solo centro.
 * { data, error, loading }; data.fuente dice si fue en vivo o respaldo. */
export default function useArticuloVivo(materialId, plant) {
  const [state, setState] = useState({ data: null, error: null, loading: true })
  useEffect(() => {
    if (!materialId) return undefined
    let alive = true
    setState({ data: null, error: null, loading: true })
    api.articulos
      .vivo(materialId, plant)
      .then((data) => alive && setState({ data, error: null, loading: false }))
      .catch((error) => alive && setState({ data: null, error, loading: false }))
    return () => {
      alive = false
    }
  }, [materialId, plant])
  return state
}
