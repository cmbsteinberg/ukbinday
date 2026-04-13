/**
 * k6 load test — ramping traffic pattern simulating realistic usage.
 *
 * Usage:
 *   k6 run tests/battletest/k6_load.js
 *   k6 run --env BASE_URL=http://localhost:8000 tests/battletest/k6_load.js
 */

import { check, sleep } from "k6";
import http from "k6/http";
import { Rate, Trend } from "k6/metrics";

const BASE = __ENV.BASE_URL || "https://ukbinday.co.uk";

const errorRate = new Rate("errors");
const scraperDuration = new Trend("scraper_duration", true);

// Ramp: warm up → peak → sustain → cool down
// Conservative targets for CX33 (8GB total, ~4GB for API)
export const options = {
	stages: [
		{ duration: "30s", target: 5 }, // warm up
		{ duration: "1m", target: 15 }, // ramp to peak
		{ duration: "2m", target: 15 }, // sustain peak
		{ duration: "30s", target: 0 }, // cool down
	],
	thresholds: {
		http_req_failed: ["rate<0.1"], // <10% failure rate
		http_req_duration: ["p(95)<10000"], // 95th percentile under 10s
		errors: ["rate<0.15"],
	},
};

const POSTCODES = ["SW1A1AA", "EH1 1YZ", "B1 1BB", "LS1 1UR", "CF10 1EP"];
const TEST_UPRNS = ["000151124612", "100062209109", "100030011612"];

export default function () {
	// 50% of traffic: lightweight endpoints
	// 30% of traffic: council lookup
	// 20% of traffic: scraper lookup
	const roll = Math.random();

	if (roll < 0.5) {
		// Lightweight: status, councils, health
		const endpoints = ["/api/v1/status", "/api/v1/councils", "/api/v1/health"];
		const endpoint = endpoints[Math.floor(Math.random() * endpoints.length)];
		const res = http.get(`${BASE}${endpoint}`, { timeout: "10s" });
		check(res, { "status 200": (r) => r.status === 200 }) || errorRate.add(1);
	} else if (roll < 0.8) {
		// Council lookup
		const pc = POSTCODES[Math.floor(Math.random() * POSTCODES.length)];
		const encoded = encodeURIComponent(pc);
		const res = http.get(`${BASE}/api/v1/council/${encoded}`, {
			timeout: "15s",
		});
		check(res, {
			"council lookup ok": (r) => r.status === 200 || r.status === 404,
		}) || errorRate.add(1);
	} else {
		// Scraper lookup (heavy)
		const uprn = TEST_UPRNS[Math.floor(Math.random() * TEST_UPRNS.length)];
		const start = Date.now();
		const res = http.get(`${BASE}/api/v1/lookup/${uprn}`, { timeout: "60s" });
		scraperDuration.add(Date.now() - start);
		check(res, {
			"scraper returned data": (r) =>
				r.status === 200 || r.status === 404 || r.status === 429,
		}) || errorRate.add(1);
	}

	sleep(Math.random() * 2 + 0.5); // 0.5–2.5s between requests
}
