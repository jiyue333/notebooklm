import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  vus: Number(__ENV.VUS || 2),
  duration: __ENV.DURATION || '1m',
  thresholds: {
    http_req_failed: ['rate<0.05'],
    http_req_duration: ['p(95)<20000'],
  },
};

const BASE_URL = (__ENV.BASE_URL || 'http://127.0.0.1:8080/api').replace(/\/$/, '');
const TOKEN = __ENV.TOKEN || '';
const NOTEBOOK_ID = __ENV.NOTEBOOK_ID || '';
const SEARCH_SESSION_ID = __ENV.SEARCH_SESSION_ID || '';
const SEARCH_RESULT_IDS = (__ENV.SEARCH_RESULT_IDS || '').split(',').filter(Boolean);

export default function () {
  const res = http.post(
    `${BASE_URL}/notebooks/${NOTEBOOK_ID}/sources/import`,
    JSON.stringify({
      searchSessionId: SEARCH_SESSION_ID,
      searchResultIds: SEARCH_RESULT_IDS,
    }),
    {
      headers: {
        'Content-Type': 'application/json',
        ...(TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {}),
      },
    }
  );
  check(res, { 'source import status is 200': (r) => r.status === 200 });
  sleep(1);
}
