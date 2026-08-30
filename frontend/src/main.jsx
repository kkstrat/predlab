import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom';
import HomeView from './components/HomeView.jsx';
import FixturesView from './components/FixturesView.jsx';
import DashboardView from './components/DashboardView.jsx';
import HistoryView from './components/HistoryView.jsx';
import GCView from './components/GCView.jsx';
import './index.css';

function App() {
  return (
    <BrowserRouter>
      <div className="app-shell">
        <nav className="topnav">
          <span className="brand">PredLab</span>
          <NavLink to="/" end className={({ isActive }) => (isActive ? 'active' : '')}>
            Home
          </NavLink>
          <NavLink to="/fixtures" className={({ isActive }) => (isActive ? 'active' : '')}>
            Fixtures
          </NavLink>
          <NavLink to="/history" className={({ isActive }) => (isActive ? 'active' : '')}>
            History
          </NavLink>
          <NavLink to="/dashboard" className={({ isActive }) => (isActive ? 'active' : '')}>
            Dashboard
          </NavLink>
          <NavLink to="/gc" className={({ isActive }) => (isActive ? 'active' : '')}>
            GC
          </NavLink>
        </nav>
        <main className="content">
          <Routes>
            <Route path="/" element={<HomeView />} />
            <Route path="/fixtures" element={<FixturesView />} />
            <Route path="/history" element={<HistoryView />} />
            <Route path="/dashboard" element={<DashboardView />} />
            <Route path="/gc" element={<GCView />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);