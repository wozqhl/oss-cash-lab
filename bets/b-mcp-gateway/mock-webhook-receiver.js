#!/usr/bin/env node
/**
 * Tiny mock HTTP webhook receiver for B gateway local-mvp.
 * Writes the last POST body to --out (default data/webhook-last.json).
 * Optional --secret: verify X-Webhook-Signature HMAC-SHA256 of the raw body.
 * Optional --headers-out: persist last request headers (+ verified flag + timestamp).
 * Records X-Webhook-Timestamp when present (OSS; replay window = paid).
 * Optional --fail-once: first POST returns 500 (body not persisted); later POSTs 200.
 * GET /stats → {ok, requests} (POST count).
 *
 *   node mock-webhook-receiver.js --port 8792 --out data/webhook-last.json
 *   node mock-webhook-receiver.js --port 8797 --secret whsec_local_mvp \
 *     --out data/webhook-hmac-last.json --headers-out data/webhook-hmac-last.headers.json
 *   node mock-webhook-receiver.js --port 8785 --fail-once --out data/webhook-retry-last.json
 */
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { verifyWebhookSignature, SIGNATURE_HEADER, TIMESTAMP_HEADER } from "./src/webhooks.js";

function parseArgs(argv) {
  let port = 8792;
  let host = "127.0.0.1";
  let out = "data/webhook-last.json";
  let headersOut = null;
  let secret = null;
  let failOnce = false;
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--port") port = Number(argv[++i]);
    else if (a === "--host") host = argv[++i];
    else if (a === "--out") out = argv[++i];
    else if (a === "--headers-out") headersOut = argv[++i];
    else if (a === "--secret") secret = argv[++i];
    else if (a === "--fail-once") failOnce = true;
  }
  if (typeof secret === "string") {
    secret = secret.trim() || null;
  } else {
    secret = null;
  }
  return { port, host, out, headersOut, secret, failOnce };
}

const { port, host, out, headersOut, secret, failOnce } = parseArgs(process.argv);
const outAbs = path.isAbsolute(out) ? out : path.resolve(process.cwd(), out);
const headersAbs = headersOut
  ? path.isAbsolute(headersOut)
    ? headersOut
    : path.resolve(process.cwd(), headersOut)
  : secret
    ? outAbs.replace(/(\.json)?$/, ".headers.json")
    : null;

function writeFileSafe(abs, contents) {
  fs.mkdirSync(path.dirname(abs), { recursive: true });
  fs.writeFileSync(abs, contents, "utf8");
}

let postCount = 0;
let failRemaining = failOnce ? 1 : 0;

const server = http.createServer((req, res) => {
  const url = new URL(req.url || "/", `http://${req.headers.host || "localhost"}`);
  const method = (req.method || "GET").toUpperCase();

  if (method === "GET" && url.pathname === "/health") {
    const body = JSON.stringify({ ok: true, service: "mock-webhook-receiver" });
    res.writeHead(200, {
      "content-type": "application/json; charset=utf-8",
      "content-length": Buffer.byteLength(body),
    });
    return res.end(body);
  }

  if (method === "GET" && url.pathname === "/stats") {
    const body = JSON.stringify({ ok: true, requests: postCount });
    res.writeHead(200, {
      "content-type": "application/json; charset=utf-8",
      "content-length": Buffer.byteLength(body),
    });
    return res.end(body);
  }

  if (method === "POST") {
    const chunks = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => {
      postCount += 1;
      const raw = Buffer.concat(chunks).toString("utf8");
      if (failRemaining > 0) {
        failRemaining -= 1;
        const fail = JSON.stringify({ ok: false, error: "fail_once", requests: postCount });
        res.writeHead(500, {
          "content-type": "application/json; charset=utf-8",
          "content-length": Buffer.byteLength(fail),
        });
        return res.end(fail);
      }
      const sigHeader = req.headers["x-webhook-signature"] || req.headers[SIGNATURE_HEADER.toLowerCase()] || "";
      const tsHeader = req.headers["x-webhook-timestamp"] || req.headers[TIMESTAMP_HEADER.toLowerCase()] || "";
      let verified = null;
      if (secret) {
        verified = verifyWebhookSignature(secret, raw, sigHeader);
      }
      try {
        writeFileSafe(outAbs, raw || "");
        if (headersAbs) {
          const meta = {
            signature: sigHeader || null,
            timestamp: tsHeader || null,
            verified,
            headers: { ...req.headers },
          };
          writeFileSafe(headersAbs, JSON.stringify(meta, null, 2) + "\n");
        }
      } catch (err) {
        const msg = JSON.stringify({ ok: false, error: String(err?.message || err) });
        res.writeHead(500, {
          "content-type": "application/json; charset=utf-8",
          "content-length": Buffer.byteLength(msg),
        });
        return res.end(msg);
      }
      if (secret && verified === false) {
        const deny = JSON.stringify({
          ok: false,
          error: "invalid_signature",
          received: true,
          verified: false,
          bytes: Buffer.byteLength(raw),
        });
        res.writeHead(401, {
          "content-type": "application/json; charset=utf-8",
          "content-length": Buffer.byteLength(deny),
        });
        return res.end(deny);
      }
      const ack = JSON.stringify({
        ok: true,
        received: true,
        bytes: Buffer.byteLength(raw),
        verified,
      });
      res.writeHead(200, {
        "content-type": "application/json; charset=utf-8",
        "content-length": Buffer.byteLength(ack),
      });
      res.end(ack);
    });
    req.on("error", () => {
      res.writeHead(400);
      res.end();
    });
    return;
  }

  res.writeHead(404, { "content-type": "application/json; charset=utf-8" });
  res.end(JSON.stringify({ error: "not_found" }));
});

server.listen(port, host, () => {
  console.log(
    `mock-webhook-receiver listening on http://${host}:${port} out=${outAbs}` +
      (secret ? " verify=hmac" : "") +
      (failOnce ? " fail-once" : "") +
      (headersAbs ? ` headers=${headersAbs}` : "")
  );
});
