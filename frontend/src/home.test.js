import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  TILES, buildBrierTrace, currentGameweekLabel, sectionStatuses, fmtBrier,
} from './home.js';

test('TILES link to the four existing routes in nav order', () => {
  assert.deepEqual(TILES.map((t) => [t.key, t.path]), [
    ['fixtures', '/fixtures'],
    ['history', '/history'],
    ['dashboard', '/dashboard'],
    ['gc', '/gc'],
  ]);
});

test('buildBrierTrace aggregates model/gut brier per gameweek', () => {
  const history = [
    {
      gameweek: 'GW1', date_utc: '2026-08-22T11:30:00+00:00',
      predictions: [{ model_brier_score: 0.4 }], gut_calls: [{ brier_score: 0.5 }],
    },
    {
      gameweek: 'GW1', date_utc: '2026-08-21T19:00:00+00:00',
      predictions: [{ model_brier_score: 0.2 }], gut_calls: [{ brier_score: 0.2 }],
    },
    {
      gameweek: 'GW2', date_utc: '2026-08-28T19:00:00+00:00',
      predictions: [{ model_brier_score: 0.6 }],
    },
  ];
  const trace = buildBrierTrace(history);
  assert.equal(trace.length, 2);
  const gw1 = trace[0];
  assert.equal(gw1.label, 'GW1');
  assert.equal(gw1.date, '2026-08-21T19:00:00+00:00'); // earliest fixture in the week
  assert.ok(Math.abs(gw1.model - 0.3) < 1e-9); // (0.2 + 0.4) / 2
  assert.ok(Math.abs(gw1.gut - 0.35) < 1e-9); // (0.2 + 0.5) / 2
  const gw2 = trace[1];
  assert.equal(gw2.model, 0.6);
  assert.equal(gw2.gut, null); // no scored gut call that week
});

test('buildBrierTrace keeps the last N gameweeks, numeric order', () => {
  const history = Array.from({ length: 12 }, (_, i) => ({
    gameweek: `GW${i + 1}`,
    date_utc: `2026-08-${String(i + 1).padStart(2, '0')}T12:00:00+00:00`,
    predictions: [{ model_brier_score: 0.3 }],
    gut_calls: [{ brier_score: 0.4 }],
  }));
  const trace = buildBrierTrace(history, 8);
  assert.equal(trace.length, 8);
  assert.equal(trace[0].label, 'GW5'); // GW1..GW12 -> keeps GW5..GW12
  assert.equal(trace[7].label, 'GW12');
});

test('buildBrierTrace sorts GW10-style labels numerically, not lexically', () => {
  const history = [
    { gameweek: 'GW10', predictions: [{ model_brier_score: 0.5 }], gut_calls: [] },
    { gameweek: 'GW2', predictions: [{ model_brier_score: 0.1 }], gut_calls: [] },
  ];
  const trace = buildBrierTrace(history);
  assert.deepEqual(trace.map((p) => p.label), ['GW2', 'GW10']);
});

test('buildBrierTrace skips unscored/empty gameweeks and missing labels', () => {
  const history = [
    { gameweek: null, predictions: [{ model_brier_score: 0.5 }], gut_calls: [] },
    { gameweek: 'GW1', predictions: [], gut_calls: [] },
  ];
  assert.deepEqual(buildBrierTrace(history), []);
});

test('currentGameweekLabel uses earliest upcoming fixture, falls back to latest finished', () => {
  assert.equal(
    currentGameweekLabel([{ external_id: 'gw2-6' }, { external_id: 'gw2-7' }], []),
    'GW2',
  );
  assert.equal(
    currentGameweekLabel([], [{ gameweek: 'GW1' }, { gameweek: 'GW3' }, { gameweek: 'GW2' }]),
    'GW3',
  );
  assert.equal(currentGameweekLabel([], []), '—');
});

test('sectionStatuses renders one-line statuses', () => {
  const status = sectionStatuses({
    upcoming: [{ id: 1 }, { id: 2 }],
    history: [{ gameweek: 'GW1' }, { gameweek: 'GW1' }, { gameweek: 'GW2' }],
    totals: { totals: { model_brier: 0.25, final_brier: 0.2 } },
    calibration: { by_tag: [1], by_note: [1, 2], by_subject: [1] },
  });
  assert.equal(status.fixtures, '2 pending');
  assert.equal(status.history, '2 gameweeks logged');
  assert.equal(status.dashboard, 'MODEL 0.250 · FINAL 0.200');
  assert.equal(status.gc, '1 tags · 2 notes · 1 subjects');
});

test('fmtBrier renders missing values as an em dash', () => {
  assert.equal(fmtBrier(null), '—');
  assert.equal(fmtBrier(0.2555), '0.256');
});