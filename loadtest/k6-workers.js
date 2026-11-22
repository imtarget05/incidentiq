import { http, check, sleep } from "k6";
import { Rate, Trend, Counter } from "k6/metrics";

// Custom metrics cho SLI/SLO
const errorRate = new Rate("errors");
const latencyP95 = new Trend("latency_p95");
const httpRequests = new Counter("http_requests_total");

export const options = {
  stages: [
    { duration: "1m", target: 10 },   // warm-up
    { duration: "3m", target: 50 },   // spike load (ingest / query spike)
    { duration: "2m", target: 0 },    // ramp-down
  ],
  thresholds: {
    // SLI: error rate < 1%
    errors: ["rate < 0.01"],
    // SLI: p95 latency < 500ms
    latency_p95: ["p(95) < 500"],
    // SLI: p99 latency < 1000ms
    http_req_duration: ["p(99) < 1000"],
  },
};

const BASE_URL = __ENV.BASE_URL || "https://ai-knowledge-platform.workers.dev";

export default function () {
  // 1) Health check (Cloudflare Worker)
  const healthRes = http.get(`${BASE_URL}/health`);
  httpRequests.add(1);
  errorRate.add(healthRes.status >= 500);
  check(healthRes, {
    "health is 200": (r) => r.status === 200,
  });

  sleep(0.5);

  // 2) Document ingest / ETL enqueue spike
  const ingestRes = http.post(`${BASE_URL}/api/ingest`, JSON.stringify({
    url: "https://example.com/document.pdf",
    mode: "inline",
  }), { headers: { "Content-Type": "application/json" } });
  httpRequests.add(1);
  latencyP95.add(ingestRes.timings.duration);
  errorRate.add(ingestRes.status >= 500);
  check(ingestRes, {
    "ingest is 200/202": (r) => r.status === 200 || r.status === 202,
    "ingest latency < 500ms": (r) => r.timings.duration < 500,
  });

  sleep(0.5);

  // 3) Semantic search query spike
  const searchRes = http.post(`${BASE_URL}/api/search`, JSON.stringify({
    query: "hội thảo văn bản pháp luật",
    topK: 5,
  }), { headers: { "Content-Type": "application/json" } });
  httpRequests.add(1);
  latencyP95.add(searchRes.timings.duration);
  errorRate.add(searchRes.status >= 500);
  check(searchRes, {
    "search is 200": (r) => r.status === 200,
    "search latency < 500ms": (r) => r.timings.duration < 500,
  });

  sleep(0.5);
}
