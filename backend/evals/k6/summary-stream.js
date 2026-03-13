import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  vus: Number(__ENV.VUS || 3),
  duration: __ENV.DURATION || '1m',
  thresholds: {
    http_req_failed: ['rate<0.05'],
    http_req_duration: ['p(95)<15000'],
  },
};

const BASE_URL = (__ENV.BASE_URL || 'http://127.0.0.1:8080/api').replace(/\/$/, '');
const TOKEN = __ENV.TOKEN || '';
const NOTEBOOK_ID = __ENV.NOTEBOOK_ID || '';
const ARTICLE_ID = __ENV.ARTICLE_ID || '';

export default function () {
  const res = http.post(
    `${BASE_URL}/notebooks/${NOTEBOOK_ID}/articles/${ARTICLE_ID}/summary/stream`,
    null,
    {
      headers: {
        Accept: 'text/event-stream',
        ...(TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {}),
      },
    }
  );
  check(res, {
    'summary stream status is 200': (r) => r.status === 200,
    'summary stream contains done event': (r) => r.body.includes('event: done'),
  });
  sleep(1);
}
