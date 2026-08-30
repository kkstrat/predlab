import { test } from 'node:test';
import assert from 'node:assert/strict';
import { gameweekLabel, gwNumber } from './gameweek.js';

test('gw-prefixed external ids become GW labels, digits kept separate', () => {
  assert.equal(gameweekLabel('gw1-7'), 'GW1');
  assert.equal(gameweekLabel('GW2-3'), 'GW2');
  assert.equal(gameweekLabel('gw10-1'), 'GW10');
});

test('unrecognized ids and missing ids fall back', () => {
  assert.equal(gameweekLabel('t-1'), 't-1');
  assert.equal(gameweekLabel(null), 'Other');
  assert.equal(gameweekLabel(''), 'Other');
});

test('gwNumber orders numerically, unknown labels sort last', () => {
  assert.equal(gwNumber('GW2'), 2);
  assert.equal(gwNumber('gw10'), 10);
  assert.equal(gwNumber('t-1'), Number.MAX_SAFE_INTEGER);
});