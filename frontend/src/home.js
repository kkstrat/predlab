import { gameweekLabel, gwNumber } from './gameweek.js';

export const TILES = [
  { key: 'fixtures', name: 'Fixtures', path: '/fixtures' },
  { key: 'history', name: 'History', path: '/history' },
  { key: 'dashboard', name: 'Dashboard', path: '/dashboard' },
  { key: 'gc', name: 'GC', path: '/gc' },
];

export function average(values) {
  return values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
}

export function fmtBrier(value, digits = 3) {
  return value == null ? '—' : Number(value).toFixed(digits);
}

export function homeHeroMetrics({ totals = {} } = {}) {
  const t = totals.totals || totals;
  return [
    { label: 'MODEL', value: fmtBrier(t.model_brier), color: 'var(--pl-model)' },
    { label: 'FINAL', value: fmtBrier(t.final_brier), color: 'var(--pl-text)' },
    { label: 'GUT', value: fmtBrier(t.gut_brier), color: 'var(--pl-gut)' },
  ];
}

export function getDefaultExpandedState(gameweeks = [], prevState = {}) {
  return gameweeks.reduce((acc, gw) => {
    acc[gw] = Boolean(prevState[gw]);
    return acc;
  }, {});
}

export function buildBrierTrace(history = [], lastN = 8) {
  const weeks = new Map();
  for (const f of history) {
    const label = f.gameweek;
    if (label == null) continue;
    let w = weeks.get(label);
    if (!w) {
      w = { label, model: [], final: [], gut: [], dates: [] };
      weeks.set(label, w);
    }
    for (const p of f.predictions || []) {
      if (p.model_brier_score != null) w.model.push(p.model_brier_score);
      if (p.brier_score != null) w.final.push(p.brier_score);
    }
    for (const g of f.gut_calls || []) {
      if (g.brier_score != null) w.gut.push(g.brier_score);
    }
    if (f.date_utc) w.dates.push(f.date_utc);
  }

  return [...weeks.values()]
    .filter((w) => w.model.length || w.final.length || w.gut.length)
    .map((w) => ({
      label: w.label,
      date: w.dates.length ? [...w.dates].sort()[0] : null,
      model: average(w.model),
      final: average(w.final),
      gut: average(w.gut),
    }))
    .sort((a, b) => gwNumber(a.label) - gwNumber(b.label))
    .slice(-lastN);
}

export function currentGameweekLabel(upcoming = [], history = []) {
  if (upcoming.length > 0) {
    return gameweekLabel(upcoming[0].external_id);
  }
  const labels = [...new Set((history || []).map((f) => f.gameweek).filter(Boolean))];
  if (labels.length === 0) return '—';
  labels.sort((a, b) => gwNumber(b) - gwNumber(a));
  return labels[0];
}

export function sectionStatuses({ upcoming = [], history = [], totals = {}, calibration = {} } = {}) {
  const t = totals.totals || {};
  const weeks = new Set((history || []).map((f) => f.gameweek).filter(Boolean));
  const byTag = (calibration && calibration.by_tag) || [];
  const byNote = (calibration && calibration.by_note) || [];
  const bySubject = (calibration && calibration.by_subject) || [];
  return {
    fixtures: `${upcoming.length} pending`,
    history: `${weeks.size} gameweeks logged`,
    dashboard: `MODEL ${fmtBrier(t.model_brier)} · FINAL ${fmtBrier(t.final_brier)}`,
    gc: `${byTag.length} tags · ${byNote.length} notes · ${bySubject.length} subjects`,
  };
}