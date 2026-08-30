const W = 640;
const H = 180;
const PAD_L = 10;
const PAD_R = 12;
const PAD_T = 14;
const PAD_B = 26;
const GRID = [0, 0.25, 0.5, 0.75, 1];

function shortDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return isNaN(d) ? '' : d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

export default function TraceChart({ points }) {
  if (!points || points.length === 0) {
    return <p className="muted" style={{ margin: 0 }}>No scored gameweeks yet.</p>;
  }

  const innerW = W - PAD_L - PAD_R;
  const innerH = H - PAD_T - PAD_B;
  const n = points.length;
  const x = (i) => (n === 1 ? W / 2 : PAD_L + (innerW * i) / (n - 1));
  const y = (v) => PAD_T + (1 - Math.min(1, Math.max(0, v))) * innerH;
  const linePoints = (key) => points
    .map((p, i) => (p[key] == null ? null : `${x(i).toFixed(1)},${y(p[key]).toFixed(1)}`))
    .filter(Boolean)
    .join(' ');

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      aria-label="Model and gut Brier trend by gameweek"
      style={{ width: '100%', height: 'auto', display: 'block' }}
    >
      {GRID.map((g) => (
        <line key={g} x1={PAD_L} x2={W - PAD_R} y1={y(g)} y2={y(g)} stroke="var(--pl-hairline)" strokeWidth="1" />
      ))}
      <polyline points={linePoints('model')} fill="none" stroke="var(--pl-model)" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
      <polyline points={linePoints('gut')} fill="none" stroke="var(--pl-gut)" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
      <text x={PAD_L} y={H - 8} fill="var(--pl-text-muted)" fontSize="10" fontFamily="'IBM Plex Mono', monospace">
        {shortDate(points[0].date)}
      </text>
      <text x={W - PAD_R} y={H - 8} fill="var(--pl-text-muted)" fontSize="10" fontFamily="'IBM Plex Mono', monospace" textAnchor="end">
        {shortDate(points[points.length - 1].date)}
      </text>
    </svg>
  );
}