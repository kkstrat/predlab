import { test } from 'node:test';
import assert from 'node:assert/strict';
import { competitionRanks } from './ranking.js';

test('non-tied teams get unique sequential ranks', () => {
  assert.deepEqual(competitionRanks([3, 1, 2]), [1, 3, 2]);
  assert.deepEqual(competitionRanks([1500, 1490, 1480, 1470]), [1, 2, 3, 4]);
});

test('tied teams share a rank and the next rank skips correctly', () => {
  assert.deepEqual(competitionRanks([100, 95, 95, 90, 85]), [1, 2, 2, 4, 5]);
  assert.deepEqual(competitionRanks([95, 95, 95, 90]), [1, 1, 1, 4]);
});

test('a tie at the very bottom shares the final rank, no phantom next rank', () => {
  const elos = [
    1500, 1490, 1480, 1470, 1460, 1450, 1440, 1430, 1420, 1410,
    1400, 1390, 1380, 1370, 1360, 1350, 1340, 1330, 1320, 1320,
  ];
  const ranks = competitionRanks(elos);
  assert.equal(ranks[18], 19);
  assert.equal(ranks[19], 19);
  assert.ok(!ranks.includes(20), 'no rank 20 should exist for tied bottom teams');
});

test('empty and single-element inputs', () => {
  assert.deepEqual(competitionRanks([]), []);
  assert.deepEqual(competitionRanks([1400]), [1]);
});