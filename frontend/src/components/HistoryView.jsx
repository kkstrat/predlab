import React, { useEffect, useMemo, useState } from 'react';
import { getFixturesHistory, utcLocal } from '../api.js';
import { formatGutNote } from '../gutNote.js';
import { getDefaultExpandedState } from '../home.js';

function fmt(n, digits = 2) {
  return n == null ? '—' : Number(n).toFixed(digits);
}

function HistoryCard({ fixture }) {
  return (
    <div className="card">
      <div className="fixture-row">
        <span className="team">{fixture.home_team}</span>
        <span className="status">{utcLocal(fixture.date_utc)}</span>
        <span className="team" style={{ textAlign: 'right' }}>{fixture.away_team}</span>
      </div>
      <div className="muted">{fixture.competition}</div>

      <div style={{ marginTop: 8, fontSize: 18, fontWeight: 500 }}>
        {fixture.home_score} – {fixture.away_score}
      </div>

      {fixture.predictions.length === 0 && fixture.gut_calls.length === 0 && (
        <div className="muted" style={{ marginTop: 10 }}>
          No prediction or gut call was logged before this one was scored.
        </div>
      )}

      {fixture.predictions.map((p) => (
        <div key={`p${p.id}`} className="muted" style={{ marginTop: 10 }}>
          Prediction — {p.market} {p.selection} @ {fmt(p.final_probability)}
          {' '}({p.adjustment_source}, model said {fmt(p.model_probability)})
          {p.brier_score != null && (
            <> · final Brier <strong>{fmt(p.brier_score, 3)}</strong>
            {' '}· model Brier {fmt(p.model_brier_score, 3)}</>
          )}
        </div>
      ))}

      {fixture.gut_calls.map((g) => (
        <div key={`g${g.id}`} className="muted" style={{ marginTop: 6 }}>
          Gut call — {g.market} {g.selection} @ {fmt(g.probability)}
          {g.note && ` · "${formatGutNote(g.note, g.home_subject, g.away_subject)}"`}
          {g.brier_score != null && <> · Brier <strong>{fmt(g.brier_score, 3)}</strong></>}
        </div>
      ))}
    </div>
  );
}

export default function HistoryView() {
  const [history, setHistory] = useState([]);
  const [error, setError] = useState('');

  const load = async () => {
    try {
      const data = await getFixturesHistory();
      setHistory(data);
    } catch (err) {
      setError(err?.response?.data?.error || err.message);
    }
  };

  useEffect(() => { load(); }, []);

  const groups = useMemo(() => history.reduce((acc, f) => {
    (acc[f.gameweek] = acc[f.gameweek] || []).push(f);
    return acc;
  }, {}), [history]);

  const gameweeks = Object.keys(groups);
  const [expanded, setExpanded] = useState({});

  useEffect(() => {
    setExpanded((prev) => getDefaultExpandedState(gameweeks, prev));
  }, [gameweeks]);

  return (
    <div>
      <h1>History</h1>
      {error && <div className="error-bar">{error}</div>}
      {history.length === 0 && (
        <p className="muted">No fixtures scored yet. Once you enter a result on the Fixtures page, it shows up here.</p>
      )}
      {gameweeks.map((gw) => {
        const fixtures = groups[gw];
        const isOpen = !!expanded[gw];

        return (
          <div key={gw}>
            <button
              type="button"
              className="gw-header gw-toggle"
              aria-expanded={isOpen}
              onClick={() => setExpanded((prev) => ({ ...prev, [gw]: !prev[gw] }))}
            >
              <span>{gw}</span>
              <span aria-hidden="true">{isOpen ? '▾' : '▸'}</span>
            </button>
            {isOpen && fixtures.map((f) => <HistoryCard key={f.id} fixture={f} />)}
          </div>
        );
      })}
    </div>
  );
}
