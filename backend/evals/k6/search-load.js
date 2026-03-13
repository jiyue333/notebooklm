import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  vus: Number(__ENV.VUS || 5),
  duration: __ENV.DURATION || '1m',
  thresholds: {
    http_req_failed: ['rate<0.05'],
    http_req_duration: ['p(95)<5000'],
  },
};

const BASE_URL = (__ENV.BASE_URL || 'http://127.0.0.1:8080/api').replace(/\/$/, '');
const TOKEN = __ENV.TOKEN || '';
const NOTEBOOK_ID = __ENV.NOTEBOOK_ID || '';

export default function () {
  const res = http.post(
    `${BASE_URL}/notebooks/${NOTEBOOK_ID}/sources/search`,
    JSON.stringify({
      query: __ENV.QUERY || 'latest ai observability best practices',
      mode: __ENV.MODE || 'auto',
      maxResults: Number(__ENV.MAX_RESULTS || 10),
      freshnessHours: Number(__ENV.FRESHNESS_HOURS || 24),
    }),
    {
      headers: {
        'Content-Type': 'application/json',
        ...(TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {}),
      },
    }
  );
  check(res, { 'search status is 200': (r) => r.status === 200 });
  sleep(1);
}
