// Standard competition ranking for a list of numeric scores (e.g. Elo).
// rank = 1 + count of entries with a strictly higher value.
// Tied values share a rank; the next rank skips by the number tied.
//   [100, 95, 95, 90] -> [1, 2, 2, 4]
export function competitionRanks(values) {
  const n = values.length;
  const order = values.map((v, i) => i).sort((a, b) => values[b] - values[a]);
  const ranks = new Array(n);
  let bandStart = 0;
  for (let k = 1; k <= n; k++) {
    if (k === n || values[order[k]] !== values[order[bandStart]]) {
      const rank = bandStart + 1;
      for (let j = bandStart; j < k; j++) ranks[order[j]] = rank;
      bandStart = k;
    }
  }
  return ranks;
}