#!/usr/bin/env node

const [action, rawPayload] = process.argv.slice(2);
const baseUrl = process.env.HARNESS_STUB_URL ?? "http://127.0.0.1:8000";
if (action === "describe" && !rawPayload) {
  const response = await fetch(`${baseUrl}/contract`);
  const body = await response.text();
  if (!response.ok) {
    console.error(body);
    process.exit(1);
  }
  console.log(body);
  process.exit(0);
}
if (!action || !rawPayload) {
  console.error("usage: harness-stub ACTION JSON_OBJECT");
  process.exit(2);
}

let payload;
try {
  payload = JSON.parse(rawPayload);
} catch {
  console.error("payload must be valid JSON");
  process.exit(2);
}

const response = await fetch(`${baseUrl}/invoke`, {
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify({ action, payload }),
});
const body = await response.text();
if (!response.ok) {
  console.error(body);
  process.exit(1);
}
console.log(body);
