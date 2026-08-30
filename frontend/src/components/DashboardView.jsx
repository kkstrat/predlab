import React, { useEffect, useState } from 'react';
import { getDashboardStats } from '../api.js';
import { competitionRanks } from '../ranking.js';

function Metric({ label, value, sub }) {
  return (
    <div className="card">
      <div className="metric">{value ?? '—'}</div>
      <div className="muted">{label}</div>
      {sub && <div className="muted">{sub}</div>}
    </div>
  );
}

export default function DashboardView() {
  const [stats, setStats] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    getDashboardStats().then(setStats).catch((err) => setError(err.message));
  }, []);

  if (error) return <div className="error-bar">{error}</div>;
  if (!stats) return <p className="muted">Loading…</p>;

  const t = stats.totals;
  const eloRanks = competitionRanks(stats.team_ratings.map((r) => r.elo));

  return (
    <div>
      <h1>Dashboard</h1>
      <div className="grid-2">
        <Metric label="Predictions scored" value={t.scored_count} sub={`${t.predictions_count} logged`} />
        <Metric label="Model Brier (avg)" value={t.model_brier?.toFixed(4)} sub="lower is better" />
        <Metric label="Final Brier (avg)" value={t.final_brier?.toFixed(4)} sub="model + adjustments" />
        <Metric label="Gut calls" value={t.gut_scored_count} sub={`${t.gut_calls_count} logged`} />
        <Metric label="Gut Brier (avg)" value={t.gut_brier?.toFixed(4)} sub={`${t.gut_hit_count} hits`} />
        <Metric label="Avg CLV" value={stats.clv.avg_clv_pct ? `${stats.clv.avg_clv_pct.toFixed(2)}%` : '—'} sub={`${stats.clv.with_clv} scored with closing odds`} />
      </div>

      <div className="grid-2">
        <div className="card">
          <h2>Brier trend</h2>
          {stats.scores_over_time.length === 0 && <p className="muted">No scored predictions yet.</p>}
          {stats.scores_over_time.map((row) => (
            <div key={row.day} className="muted">
              {row.day}: model {row.model_brier?.toFixed(3)} · final {row.final_brier?.toFixed(3)}
            </div>
          ))}
        </div>

        <div className="card">
          <h2>Gut call calibration</h2>
          <table>
            <thead>
              <tr><th>Bucket</th><th>n</th><th>scored</th><th>hit rate</th><th>Brier</th></tr>
            </thead>
            <tbody>
              {stats.gut_calibration.map((r) => (
                <tr key={r.probability}>
                  <td>{r.probability}</td>
                  <td>{r.n}</td>
                  <td>{r.scored}</td>
                  <td>{r.hit_rate ?? '—'}</td>
                  <td>{r.brier != null ? r.brier.toFixed(3) : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="grid-2">
        <div className="card">
          <h2>By market</h2>
          <table>
            <thead><tr><th>Market</th><th>n</th><th>model Brier</th><th>final Brier</th></tr></thead>
            <tbody>
              {stats.by_market.map((r) => (
                <tr key={r.market}>
                  <td>{r.market}</td>
                  <td>{r.n}</td>
                  <td>{r.model_brier != null ? r.model_brier.toFixed(3) : '—'}</td>
                  <td>{r.final_brier != null ? r.final_brier.toFixed(3) : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="card">
          <h2>By competition</h2>
          <table>
            <thead><tr><th>Competition</th><th>n</th><th>final Brier</th></tr></thead>
            <tbody>
              {stats.by_competition.map((r) => (
                <tr key={r.competition}>
                  <td>{r.competition}</td>
                  <td>{r.n}</td>
                  <td>{r.final_brier != null ? r.final_brier.toFixed(3) : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {stats.team_ratings.length > 0 && (
        <div className="card">
          <h2>Team ratings (Elo)</h2>
          <table>
            <thead><tr><th>Rank</th><th>Team</th><th>GP</th><th>Elo</th><th>GF/gm</th><th>GA/gm</th></tr></thead>
            <tbody>
              {stats.team_ratings.map((r, i) => (
                <tr key={r.team}>
                  <td>{eloRanks[i]}</td>
                  <td>{r.team}</td>
                  <td>{r.games_played}</td>
                  <td>{Math.round(r.elo)}</td>
                  <td>{r.avg_goals_for?.toFixed(2) ?? '—'}</td>
                  <td>{r.avg_goals_against?.toFixed(2) ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}