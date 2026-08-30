import axios from 'axios';

const client = axios.create({ baseURL: '/api' });

export async function getFixtures(upcoming = true) {
  const { data } = await client.get('/fixtures', { params: { upcoming } });
  return data;
}

export async function getModelPreview(fixtureId) {
  const { data } = await client.get(`/fixtures/${fixtureId}/model`);
  return data;
}

export async function createPrediction(payload) {
  const { data } = await client.post('/predictions', payload);
  return data;
}

export async function createGutCall(payload) {
  const { data } = await client.post('/gut_calls', payload);
  return data;
}

export async function getDashboardStats() {
  const { data } = await client.get('/dashboard/stats');
  return data;
}

export async function scoreFixture(fixtureId, homeScore, awayScore) {
  const { data } = await client.post(`/fixtures/${fixtureId}/score`, {
    home_score: homeScore,
    away_score: awayScore,
  });
  return data;
}

export async function getFixturesHistory() {
  const { data } = await client.get('/fixtures/history');
  return data;
}

export async function getPredictions(fixtureId) {
  const { data } = await client.get(`/fixtures/${fixtureId}/predictions`);
  return data;
}

export async function getGutCalls(fixtureId) {
  const { data } = await client.get(`/fixtures/${fixtureId}/gut_calls`);
  return data;
}

export async function getGutCallCalibration() {
  const { data } = await client.get('/gut_calls/calibration');
  return data;
}

export async function getGutCallNoteRecord(note) {
  const { data } = await client.get('/gut_calls/notes', { params: { q: note } });
  return data;
}

export function utcLocal(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return isNaN(d) ? iso : d.toLocaleString();
}