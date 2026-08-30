import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  getFixtures, getFixturesHistory, getDashboardStats, getGutCallCalibration,
} from '../api.js';
import { buildBrierTrace, currentGameweekLabel, fmtBrier, sectionStatuses, TILES } from '../home.js';
import TraceChart from './TraceChart.jsx';

export default function HomeView() {
  const [state, setState] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    Promise.all([
      getFixtures(true),
      getFixturesHistory(),
      getDashboardStats(),
      getGutCallCalibration(),
    ])
      .then(([upcoming, history, totals, calibration]) => setState({ upcoming, history, totals, calibration }))
      .catch((err) => setError(err?.response?.data?.error || err.message));
  }, []);

  if (error) return <div className="error-bar">{error}</div>;
  if (!state) return <p className="muted">Loading…</p>;

  const { upcoming, history, totals, calibration } = state;
  const currentGW = currentGameweekLabel(upcoming, history);
  const statuses = sectionStatuses({ upcoming, history, totals, calibration });
  const trace = buildBrierTrace(history);
  const last = trace[trace.length - 1];

  return (
    <div className="home">
      <header className="pl-head">
        <span className="pl-wordmark">PredLab</span>
        <span className="pl-mono pl-head-meta">{currentGW} · {totals.totals.gut_calls_count} logged</span>
      </header>

      <section className="pl-panel pl-trace">
        <div className="pl-trace-readouts">
          <span style={{ color: 'var(--pl-model)' }}>MODEL — {fmtBrier(last && last.model)}</span>
          <span style={{ color: 'var(--pl-gut)' }}>GUT — {fmtBrier(last && last.gut)}</span>
        </div>
        <TraceChart points={trace} />
      </section>

      <nav className="pl-tile-grid" aria-label="Sections">
        {TILES.map((tile) => (
          <Link key={tile.path} to={tile.path} className="pl-tile">
            <div className="pl-tile-name">{tile.name}</div>
            <div className="pl-tile-status">{statuses[tile.key]}</div>
          </Link>
        ))}
      </nav>
    </div>
  );
}