/** In-memory Prometheus-style counters for the MCP gateway */

function escapeLabelValue(value) {
  return String(value ?? "")
    .replace(/\\/g, "\\\\")
    .replace(/\n/g, "\\n")
    .replace(/"/g, '\\"');
}

function labelsKey(labels) {
  return Object.keys(labels)
    .sort()
    .map((k) => `${k}=${labels[k]}`)
    .join("|");
}

export function createMetrics() {
  const toolCalls = new Map(); // key -> { labels, count }
  const httpRequests = new Map();
  let rateLimited = 0;
  let ipDenied = 0;
  let bodyTooLarge = 0;
  let upstreamTimeout = 0;
  let circuitOpen = 0;
  let webhookRetries = 0;
  let auditEvents = 0;

  function incToolCall({ tool, decision, tenant }) {
    const labels = {
      tool: tool || "unknown",
      decision: decision || "unknown",
      tenant: tenant || "none",
    };
    const key = labelsKey(labels);
    const cur = toolCalls.get(key);
    if (cur) cur.count += 1;
    else toolCalls.set(key, { labels, count: 1 });
  }

  function incRateLimited() {
    rateLimited += 1;
  }

  function incIpDenied() {
    ipDenied += 1;
  }

  function incBodyTooLarge() {
    bodyTooLarge += 1;
  }

  function incUpstreamTimeout() {
    upstreamTimeout += 1;
  }

  function incCircuitOpen() {
    circuitOpen += 1;
  }

  function incWebhookRetry() {
    webhookRetries += 1;
  }

  function setAuditEvents(n) {
    const v = typeof n === "number" && Number.isFinite(n) ? Math.floor(n) : 0;
    auditEvents = v < 0 ? 0 : v;
  }

  function incHttpRequest({ path: p, status }) {
    const labels = {
      path: p || "unknown",
      status: String(status ?? "0"),
    };
    const key = labelsKey(labels);
    const cur = httpRequests.get(key);
    if (cur) cur.count += 1;
    else httpRequests.set(key, { labels, count: 1 });
  }

  function formatGauge(name, help, value) {
    const n = typeof value === "number" && Number.isFinite(value) ? value : 0;
    return [`# HELP ${name} ${help}`, `# TYPE ${name} gauge`, `${name} ${n}`];
  }

  function formatCounter(name, help, entries, bareValue) {
    const lines = [`# HELP ${name} ${help}`, `# TYPE ${name} counter`];
    if (typeof bareValue === "number") {
      lines.push(`${name} ${bareValue}`);
      return lines;
    }
    if (!entries || entries.size === 0) {
      // expose a zero sample without labels so scrapers still see the metric name
      lines.push(`${name} 0`);
      return lines;
    }
    for (const { labels, count } of entries.values()) {
      const parts = Object.keys(labels)
        .sort()
        .map((k) => `${k}="${escapeLabelValue(labels[k])}"`)
        .join(",");
      lines.push(`${name}{${parts}} ${count}`);
    }
    return lines;
  }

  function render() {
    const lines = [
      ...formatCounter(
        "tool_calls_total",
        "Total tool call decisions by tool, decision, and tenant",
        toolCalls
      ),
      ...formatCounter(
        "rate_limited_total",
        "Total rate-limited tool call attempts",
        null,
        rateLimited
      ),
      ...formatCounter(
        "ip_denied_total",
        "Total requests denied by per-tenant IP allowlist",
        null,
        ipDenied
      ),
      ...formatCounter(
        "body_too_large_total",
        "Total requests rejected for exceeding maxBodyBytes",
        null,
        bodyTooLarge
      ),
      ...formatCounter(
        "upstream_timeout_total",
        "Total upstream HTTP/stdio calls aborted after timeoutMs",
        null,
        upstreamTimeout
      ),
      ...formatCounter(
        "circuit_open_total",
        "Total tools/call requests rejected because the upstream circuit breaker is open",
        null,
        circuitOpen
      ),
      ...formatCounter(
        "webhook_retries_total",
        "Total outbound audit webhook POST retries (OSS: one retry on 5xx or network/timeout)",
        null,
        webhookRetries
      ),
      ...formatCounter(
        "http_requests_total",
        "Total HTTP requests by path and status",
        httpRequests
      ),
      ...formatGauge(
        "audit_events",
        "In-memory audit events currently retained (ring buffer)",
        auditEvents
      ),
      ...formatGauge(
        "audit_retained",
        "In-memory audit events currently retained (alias of audit_events)",
        auditEvents
      ),
      "",
    ];
    return lines.join("\n");
  }

  return {
    incToolCall,
    incRateLimited,
    incIpDenied,
    incBodyTooLarge,
    incUpstreamTimeout,
    incCircuitOpen,
    incWebhookRetry,
    incHttpRequest,
    setAuditEvents,
    render,
  };
}
