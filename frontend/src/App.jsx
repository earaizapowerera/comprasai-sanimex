import { Route, Routes } from 'react-router-dom'
import Shell from './components/Shell.jsx'
import Dashboard from './pages/Dashboard.jsx'
import Placeholder from './pages/Placeholder.jsx'
import Balanceos from './pages/Balanceos.jsx'
import Sugeridos from './pages/Sugeridos.jsx'
import ChatPlanner from './pages/ChatPlanner.jsx'

export default function App() {
  return (
    <Shell>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route
          path="/inventarios"
          element={<Placeholder title="Inventarios & Cobertura" waykee="T8" />}
        />
        <Route path="/sugeridos" element={<Sugeridos />} />
        <Route path="/balanceos" element={<Balanceos />} />
        <Route
          path="/semaforo"
          element={<Placeholder title="Semáforo de Cumplimiento" waykee="T11" />}
        />
        <Route path="/chat" element={<ChatPlanner />} />
      </Routes>
    </Shell>
  )
}
