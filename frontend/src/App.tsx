import { BrowserRouter, Routes, Route } from 'react-router-dom'
import LandingPage from './pages/LandingPage'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<LandingPage />} />
        {/* /plan, /trip/:id etc. get added as those pages get built */}
      </Routes>
    </BrowserRouter>
  )
}
