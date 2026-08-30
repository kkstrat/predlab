import React, { useEffect, useState } from 'react';
import { getGutCallCalibration } from '../api.js';

function CalTable({ rows, noteMode }) {
  return (
    <table>
      <thead>
        <tr>
          <th>{noteMode ? 'Note' : 'Tag'}</th>
          <th>n</th>
          <th>scored</th>
          <th>hits</th>
          <th>hit rate</th>
          <th>Brier</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={noteMode ? r.normalized : r.tag}>
            <td>{noteMode ? r.note : r.tag}</td>
            <td>{r.n}</td>
            <td>{r.scored}</td>
            <td>{r.hits}</td>
            <td>{r.hit_rate ?? '—'}</td>
            <td>{r.brier != null ? r.brier.toFixed(3) : '—'}</td>
          </tr>
        ))}
        {rows.length === 0 && (
          <tr><td colSpan={6} className="muted">No {noteMode ? 'notes' : 'tagged'} gut calls yet.</td></tr>
        )}
      </tbody>
    </table>
  );
}

export default function GCView() {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    getGutCallCalibration().then(setData).catch((err) => setError(err.message));
  }, []);

  if (error) return <div className="error-bar">{error}</div>;
  if (!data) return <p className="muted">Loading…</p>;

  return (
    <div>
      <h1>Gut Call Calibration</h1>
      <p className="muted">
        How recurring heuristics (tags and note codewords) hold up against their own
        track record, independent of probability-bucket calibration.
      </p>

      <div className="card">
        <h2>By tag</h2>
        <CalTable rows={data.by_tag} noteMode={false} />
      </div>

      <div className="card">
        <h2>By note</h2>
        <CalTable rows={data.by_note} noteMode />
      </div>
    </div>
  );
}
