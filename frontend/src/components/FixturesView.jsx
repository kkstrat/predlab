import React, { useEffect, useState } from 'react';
import {
  getFixtures, getModelPreview, createPrediction, createGutCall, scoreFixture, utcLocal,
  getPredictions, getGutCalls, getGutCallNoteRecord,
} from '../api.js';

const MARKETS = ['1X2', 'OU_2.5', 'BTTS'];
const SELECTIONS = {
  '1X2': ['home', 'draw', 'away'],
  'OU_2.5': ['over', 'under'],
  BTTS: ['yes', 'no'],
};

function maxSelection(probs) {
  if (!probs) return null;
  let best = null;
  for (const [sel, prob] of Object.entries(probs)) {
    if (best === null || prob > best.prob) best = { sel, prob };
  }
  return best ? best.sel : null;
}

function FixtureCard({ fixture, onChanged, onError }) {
  const [models, setModels] = useState([]);
  const [prediction, setPrediction] = useState({
    market: '1X2',
    selection: 'home',
    final_probability: 0.5,
    adjustment_source: 'model_only',
  });
  const [gut, setGut] = useState({
    market: '1X2',
    selection: 'home',
    probability: 0.75,
    note: '',
    tag: '',
  });
  const [score, setScore] = useState({ home_score: '', away_score: '' });
  const [loggedPredictions, setLoggedPredictions] = useState([]);
  const [loggedGutCalls, setLoggedGutCalls] = useState([]);
  const [noteRecord, setNoteRecord] = useState(null);
  const [submittingGut, setSubmittingGut] = useState(false);
  const [submittingPrediction, setSubmittingPrediction] = useState(false);

  const loadLogged = async () => {
    try {
      const [preds, guts] = await Promise.all([
        getPredictions(fixture.id),
        getGutCalls(fixture.id),
      ]);
      setLoggedPredictions(preds);
      setLoggedGutCalls(guts);
    } catch (err) {
      onError(err?.response?.data?.error || err.message);
    }
  };

  useEffect(() => { loadLogged(); }, [fixture.id]);

  const loadNoteRecord = async (note) => {
    const trimmed = (note || '').trim();
    if (!trimmed) { setNoteRecord(null); return; }
    try {
      const rec = await getGutCallNoteRecord(trimmed);
      setNoteRecord(rec);
    } catch {
      setNoteRecord(null);
    }
  };

  useEffect(() => { loadNoteRecord(gut.note); }, [gut.note]);

  const loadModel = async () => {
    try {
      const data = await getModelPreview(fixture.id);
      setModels(data.models || []);
    } catch (err) {
      onError(err?.response?.data?.error || err.message);
    }
  };

  useEffect(() => { loadModel(); }, [fixture.id]);

  useEffect(() => {
    const mp = models[0]?.probabilities?.[prediction.market]?.[prediction.selection];
    if (mp != null) {
      setPrediction((p) => ({ ...p, final_probability: Number(mp.toFixed(4)) }));
    }
  }, [models, prediction.market, prediction.selection]);

  const submitPrediction = async (e) => {
    e.preventDefault();
    if (submittingPrediction) return;
    setSubmittingPrediction(true);

    const mp = models[0]?.probabilities?.[prediction.market]?.[prediction.selection];
    // GW3 forward: log all three markets instead of just the form's one.
    // 1X2 keeps the form's manual pick; O2.5 and BTTS take the model's
    // favoured selection at the model probability (model_only). GW1/GW2 keep
    // the single 1X2 row exactly as before.
    const gwMatch = String(fixture.external_id || '').match(/gw(\d+)/i);
    const useThreeMarkets = Boolean(gwMatch) && parseInt(gwMatch[1], 10) >= 3;

    const base = {
      fixture_id: fixture.id,
      final_probability: Number(prediction.final_probability),
    };

    try {
      if (useThreeMarkets && models[0]?.probabilities) {
        const probs = models[0].probabilities;
        const payloads = MARKETS.map((market) => {
          if (market === prediction.market) {
            return {
              ...base,
              market,
              selection: prediction.selection,
              model_probability: probs[market]?.[prediction.selection] ?? Number(prediction.final_probability),
              adjustment_source: prediction.adjustment_source,
            };
          }
          const sel = maxSelection(probs[market]);
          return {
            ...base,
            market,
            selection: sel,
            model_probability: probs[market][sel],
            final_probability: probs[market][sel],
            adjustment_source: 'model_only',
          };
        });
        await Promise.all(payloads.map((p) => createPrediction(p)));
      } else {
        await createPrediction({
          ...base,
          market: prediction.market,
          selection: prediction.selection,
          model_probability: mp ?? Number(prediction.final_probability),
          adjustment_source: prediction.adjustment_source,
        });
      }
      onChanged();
      loadLogged();
    } catch (err) {
      onError(err?.response?.data?.error || err.message);
    } finally {
      setSubmittingPrediction(false);
    }
  };

  const submitScore = async (e) => {
    e.preventDefault();
    if (score.home_score === '' || score.away_score === '') {
      onError('Enter both scores');
      return;
    }
    try {
      await scoreFixture(fixture.id, Number(score.home_score), Number(score.away_score));
      onChanged();
    } catch (err) {
      onError(err?.response?.data?.error || err.message);
    }
  };

  const submitGut = async (e) => {
    e.preventDefault();
    if (submittingGut) return;

    setSubmittingGut(true);
    try {
      await createGutCall({
        fixture_id: fixture.id,
        market: gut.market,
        selection: gut.selection,
        probability: Number(gut.probability),
        note: gut.note || null,
        tag: gut.tag || null,
      });
      onChanged();
      loadLogged();
    } catch (err) {
      onError(err?.response?.data?.error || err.message);
    } finally {
      setSubmittingGut(false);
    }
  };

  return (
    <div className="card">
      <div className="fixture-row">
        <span className="team">{fixture.home_team}</span>
        <span className="status">{utcLocal(fixture.date_utc)}</span>
        <span className="team" style={{ textAlign: 'right' }}>{fixture.away_team}</span>
      </div>
      <div className="muted" style={{ marginBottom: 8 }}>
        {fixture.competition}
        {fixture.is_friendly ? ' • friendly' : ''} •{' '}
        <span className={fixture.status === 'friendly' ? 'status friendly' : 'status'}>
          {fixture.status}
        </span>
      </div>

      {models.map((m) => (
        <div key={m.model_version} className="muted" style={{ marginTop: 8 }}>
          <span className="pl-model" style={{ fontFamily: 'var(--pl-font-mono)' }}><strong>{m.model_version}</strong></span>: home {' '}
          <span style={{ color: 'var(--pl-model)', fontFamily: 'var(--pl-font-mono)' }}>{m.probabilities['1X2'].home.toFixed(2)}</span> · draw{' '}
          <span style={{ color: 'var(--pl-model)', fontFamily: 'var(--pl-font-mono)' }}>{m.probabilities['1X2'].draw.toFixed(2)}</span> · away{' '}
          <span style={{ color: 'var(--pl-model)', fontFamily: 'var(--pl-font-mono)' }}>{m.probabilities['1X2'].away.toFixed(2)}</span> · O2.5{' '}
          <span style={{ color: 'var(--pl-model)', fontFamily: 'var(--pl-font-mono)' }}>{m.probabilities['OU_2.5'].over.toFixed(2)}</span> · BTTS yes{' '}
          <span style={{ color: 'var(--pl-model)', fontFamily: 'var(--pl-font-mono)' }}>{m.probabilities.BTTS.yes.toFixed(2)}</span>
        </div>
      ))}

      {loggedPredictions.length > 0 ? (
        <div className="muted" style={{ marginTop: 10 }}>
          {loggedPredictions.map((p) => (
            <div key={p.id}>
              ✔ prediction logged — {p.market} {p.selection} @ <span style={{ color: 'var(--pl-model)', fontFamily: 'var(--pl-font-mono)' }}>{p.final_probability.toFixed(2)}</span>
              {' '}({p.adjustment_source}, model said <span style={{ color: 'var(--pl-model)', fontFamily: 'var(--pl-font-mono)' }}>{p.model_probability.toFixed(2)}</span>)
              {p.brier_score != null && ` · scored, Brier ${p.brier_score.toFixed(3)}`}
            </div>
          ))}
        </div>
      ) : (
        <form className="quick-form" onSubmit={submitPrediction}>
          <select value={prediction.market} onChange={(e) => {
            const m = e.target.value;
            setPrediction({ ...prediction, market: m, selection: SELECTIONS[m][0] });
          }}>
            {MARKETS.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
          <select value={prediction.selection} onChange={(e) =>
            setPrediction({ ...prediction, selection: e.target.value })}>
            {SELECTIONS[prediction.market].map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <input type="number" min="0.01" max="0.99" step="any"
            value={prediction.final_probability}
            onChange={(e) => setPrediction({ ...prediction, final_probability: e.target.value })} />
          <select value={prediction.adjustment_source} onChange={(e) =>
            setPrediction({ ...prediction, adjustment_source: e.target.value })}>
            <option value="model_only">model_only</option>
            <option value="blended">blended</option>
          </select>
          <button type="submit" className="primary" disabled={submittingPrediction}>
            {submittingPrediction ? 'Logging…' : 'Log prediction'}
          </button>
        </form>
      )}

      {loggedGutCalls.length > 0 ? (
        <div className="muted" style={{ marginTop: 8 }}>
          {loggedGutCalls.map((g) => (
            <div key={g.id}>
              ✔ gut call logged — {g.market} {g.selection} @ <span style={{ color: 'var(--pl-gut)', fontFamily: 'var(--pl-font-mono)' }}>{g.probability.toFixed(2)}</span>
              {g.tag && ` · [${g.tag}]`}
              {g.note && ` · "${g.note}"`}
              {g.brier_score != null && ` · scored, Brier ${g.brier_score.toFixed(3)}`}
            </div>
          ))}
        </div>
      ) : (
        <form className="quick-form" onSubmit={submitGut}>
          <select value={gut.market} onChange={(e) => {
            const m = e.target.value;
            setGut({ ...gut, market: m, selection: SELECTIONS[m][0] });
          }}>
            {MARKETS.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
          <select value={gut.selection} onChange={(e) =>
            setGut({ ...gut, selection: e.target.value })}>
            {SELECTIONS[gut.market].map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <select value={gut.probability} onChange={(e) =>
            setGut({ ...gut, probability: e.target.value })}>
            <option value="0.95">0.95</option>
            <option value="0.75">0.75</option>
            <option value="0.50">0.50</option>
          </select>
          <select value={gut.tag} onChange={(e) => setGut({ ...gut, tag: e.target.value })}>
            <option value="">no tag</option>
            <option value="pattern">pattern</option>
            <option value="deep">deep</option>
          </select>
          <input placeholder="note (optional)" value={gut.note}
            onChange={(e) => setGut({ ...gut, note: e.target.value })} />
          {noteRecord && noteRecord.n > 0 && (
            <span className="note-reuse">
              reused: n={noteRecord.n} · hit rate {noteRecord.hit_rate ?? '—'}
            </span>
          )}
          <button type="submit" disabled={submittingGut}>
            {submittingGut ? 'Logging…' : 'Log gut call'}
          </button>
        </form>
      )}

      {fixture.status !== 'finished' && (
        <form className="quick-form" onSubmit={submitScore}>
          <span className="team">{fixture.home_team}</span>
          <input type="number" min="0" step="1" placeholder="0" style={{ width: 50 }}
            value={score.home_score}
            onChange={(e) => setScore({ ...score, home_score: e.target.value })} />
          <span className="muted">–</span>
          <input type="number" min="0" step="1" placeholder="0" style={{ width: 50 }}
            value={score.away_score}
            onChange={(e) => setScore({ ...score, away_score: e.target.value })} />
          <span className="team">{fixture.away_team}</span>
          <button type="submit" className="primary">Enter result & score</button>
        </form>
      )}
    </div>
  );
}

export default function FixturesView() {
  const [fixtures, setFixtures] = useState([]);
  const [error, setError] = useState('');

  const load = async () => {
    try {
      const data = await getFixtures(true);
      setFixtures(data);
    } catch (err) {
      setError(err?.response?.data?.error || err.message);
    }
  };

  useEffect(() => { load(); }, []);

  return (
    <div>
      <h1>Upcoming fixtures</h1>
      {error && <div className="error-bar">{error}</div>}
      {fixtures.length === 0 && <p className="muted">No upcoming fixtures yet. Seed some data or configure API keys.</p>}
      {fixtures.map((f) => (
        <FixtureCard key={f.id} fixture={f} onChanged={load} onError={setError} />
      ))}
    </div>
  );
}