export function gameweekLabel(externalId) {
  if (externalId == null || externalId === '') return 'Other';
  const m = String(externalId).match(/gw(\d+)/i);
  return m ? `GW${parseInt(m[1], 10)}` : String(externalId);
}

export function gwNumber(label) {
  const m = String(label || '').match(/gw(\d+)/i);
  const n = m ? parseInt(m[1], 10) : NaN;
  return Number.isFinite(n) ? n : Number.MAX_SAFE_INTEGER;
}