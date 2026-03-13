import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  vus: Number(__ENV.VUS || 10),
  duration: __ENV.DURATION || '1m',
  thresholds: {
    http_req_failed: ['rate<0.05'],
    http_req_duration: ['p(95)<2000'],
  },
};

const BASE_URL = (__ENV.BASE_URL || 'http://127.0.0.1:8080/api').replace(/\/$/, '');
const TOKEN = __ENV.TOKEN || '';
const NOTEBOOK_ID = __ENV.NOTEBOOK_ID || '';

export default function () {
  const res = http.get(`${BASE_URL}/notebooks/${NOTEBOOK_ID}`, {
    headers: TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {},
  });
  check(res, { 'detail status is 200': (r) => r.status === 200 });
  sleep(Number(__ENV.SLEEP_SECONDS || 2));
}
