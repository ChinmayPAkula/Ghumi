import { BrowserRouter, Routes, Route } from 'react-router-dom'
import LandingPage from './pages/LandingPage'
import PlanPage from './pages/PlanPage'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/plan" element={<PlanPage />} />
        {/* /trip/:id etc. get added as those pages get built */}
      </Routes>
    </BrowserRouter>
  )
}