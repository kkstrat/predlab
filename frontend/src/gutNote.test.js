import { test } from 'node:test';
import assert from 'node:assert/strict';
import { formatGutNote } from './gutNote.js';

test('splits comma note and pairs parts with home/away subjects', () => {
  assert.equal(
    formatGutNote('home lock, away wildcard', 'Man Utd', 'Newcastle'),
    'home lock (Man Utd), away wildcard (Newcastle)',
  );
});

test('leaves no-comma notes unchanged', () => {
  assert.equal(formatGutNote('anfield fortress', 'Arsenal', 'Chelsea'), 'anfield fortress');
});

test('leaves raw note unchanged when subjects are missing', () => {
  assert.equal(formatGutNote('home lock, away wildcard', null, null), 'home lock, away wildcard');
  assert.equal(formatGutNote('home lock, away wildcard', 'Arsenal', null), 'home lock, away wildcard');
});

test('trims spaces around the first comma', () => {
  assert.equal(formatGutNote('home lock,away wildcard', 'Arsenal', 'Chelsea'), 'home lock (Arsenal), away wildcard (Chelsea)');
});

test('splits at the first comma only', () => {
  assert.equal(
    formatGutNote('hold the front, expect goals, both score', 'Arsenal', 'Chelsea'),
    'hold the front (Arsenal), expect goals, both score (Chelsea)',
  );
});

test('empty note stays empty', () => {
  assert.equal(formatGutNote('', 'Arsenal', 'Chelsea'), '');
  assert.equal(formatGutNote(null, 'Arsenal', 'Chelsea'), '');
});