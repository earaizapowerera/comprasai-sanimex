import { Route, Routes } from 'react-router-dom'
import Shell from './components/Shell.jsx'
import Dashboard from './pages/Dashboard.jsx'
import Balanceos from './pages/Balanceos.jsx'
import Sugeridos from './pages/Sugeridos.jsx'
import ChatPlanner from './pages/ChatPlanner.jsx'
import Inventarios from './pages/Inventarios.jsx'
import Semaforo from './pages/Semaforo.jsx'

export default function App() {
  return (
    <Shell>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/inventarios" element={<Inventarios />} />
        <Route path="/sugeridos" element={<Sugeridos />} />
        <Route path="/balanceos" element={<Balanceos />} />
        <Route path="/semaforo" element={<Semaforo />} />
        <Route path="/chat" element={<ChatPlanner />} />
      </Routes>
    </Shell>
  )
}
