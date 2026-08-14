/** Upstream circuit breaker (closed → open → half-open probe). */

export const DEFAULT_BREAKER_FAILURE_THRESHOLD = 3;
export const DEFAULT_BREAKER_OPEN_MS = 2000;

function positiveInt(v, fallback) {
  if (typeof v === "number" && Number.isFinite(v) && v > 0) return Math.floor(v);
  if (typeof v === "string" && v.trim() !== "") {
    const n = Number(v);
    if (Number.isFinite(n) && n > 0) return Math.floor(n);
  }
  return fallback;
}

/**
 * Resolve `upstream.breaker`. Omitted / false / enabled:false / failureThreshold 0 → disabled
 * (existing timeout/proxy proves stay unaffected). When present, defaults:
 * `{ failureThreshold: 3, openMs: 2000 }`.
 */
export function resolveBreakerConfig(upstreamConfig = {}) {
  const b = upstreamConfig?.breaker;
  const defaults = {
    enabled: false,
    failureThreshold: DEFAULT_BREAKER_FAILURE_THRESHOLD,
    openMs: DEFAULT_BREAKER_OPEN_MS,
  };
  if (b == null || b === false) return defaults;
  if (typeof b !== "object") return defaults;
  if (b.enabled === false) {
    return {
      enabled: false,
      failureThreshold: positiveInt(b.failureThreshold, DEFAULT_BREAKER_FAILURE_THRESHOLD),
      openMs: positiveInt(b.openMs, DEFAULT_BREAKER_OPEN_MS),
    };
  }
  const failureThreshold = positiveInt(b.failureThreshold, DEFAULT_BREAKER_FAILURE_THRESHOLD);
  const openMs = positiveInt(b.openMs, DEFAULT_BREAKER_OPEN_MS);
  // Explicit 0 / "0" disables (high-threshold alternative is a large positive int).
  if (b.failureThreshold === 0 || b.failureThreshold === "0") {
    return { enabled: false, failureThreshold: DEFAULT_BREAKER_FAILURE_THRESHOLD, openMs };
  }
  return { enabled: true, failureThreshold, openMs };
}

/**
 * Consecutive-failure breaker.
 * - closed: calls pass; failures increment until failureThreshold → open
 * - open: allow() is false until openMs elapsed → half_open
 * - half_open: exactly one probe; success → closed; failure → open again
 */
export function createCircuitBreaker(resolved = {}, opts = {}) {
  const now = typeof opts.now === "function" ? opts.now : () => Date.now();
  const enabled = Boolean(resolved?.enabled);
  const failureThreshold = positiveInt(
    resolved?.failureThreshold,
    DEFAULT_BREAKER_FAILURE_THRESHOLD
  );
  const openMs = positiveInt(resolved?.openMs, DEFAULT_BREAKER_OPEN_MS);

  let state = "closed"; // closed | open | half_open
  let failures = 0;
  let openedAt = 0;
  let probeInFlight = false;

  function transitionToHalfOpenIfDue() {
    if (state === "open" && now() - openedAt >= openMs) {
      state = "half_open";
      probeInFlight = false;
    }
  }

  function allow() {
    if (!enabled) return true;
    transitionToHalfOpenIfDue();
    if (state === "open") return false;
    if (state === "half_open") {
      if (probeInFlight) return false;
      probeInFlight = true;
      return true;
    }
    return true;
  }

  function recordSuccess() {
    if (!enabled) return;
    failures = 0;
    state = "closed";
    probeInFlight = false;
    openedAt = 0;
  }

  /** @returns {boolean} true when this failure opened (or re-opened) the circuit */
  function recordFailure() {
    if (!enabled) return false;
    probeInFlight = false;
    if (state === "half_open") {
      state = "open";
      openedAt = now();
      return true;
    }
    failures += 1;
    if (failures >= failureThreshold) {
      state = "open";
      openedAt = now();
      return true;
    }
    return false;
  }

  function snapshot() {
    if (enabled) transitionToHalfOpenIfDue();
    let openUntil = null;
    if (enabled && state === "open") {
      openUntil = new Date(openedAt + openMs).toISOString();
    }
    return {
      enabled,
      state: enabled ? state : "closed",
      failures,
      failureThreshold,
      openMs,
      probeInFlight,
      openUntil,
    };
  }

  /** Public GET /health payload: { state, failures, openUntil } or null when disabled. No secrets. */
  function healthSnapshot() {
    if (!enabled) return null;
    const s = snapshot();
    return { state: s.state, failures: s.failures, openUntil: s.openUntil };
  }

  /**
   * GET /ready: 200 {ok:true} when disabled or closed/half_open;
   * 503 {ok:false, reason:"circuit_open"} when state is open.
   * Includes breaker snapshot when enabled (same keys as healthSnapshot; no secrets).
   * Does not call allow() — readiness must not consume the half-open probe.
   */
  function readyPayload() {
    const snap = healthSnapshot();
    if (!snap) {
      return { status: 200, body: { ok: true } };
    }
    if (snap.state === "open") {
      return {
        status: 503,
        body: { ok: false, reason: "circuit_open", breaker: snap },
      };
    }
    return { status: 200, body: { ok: true, breaker: snap } };
  }

  /**
   * Seconds for HTTP Retry-After on 503 circuit_open.
   * Remaining time until openUntil, rounded up, minimum 1.
   * Half-open (probe in flight) or disabled → 1.
   */
  function retryAfterSeconds() {
    if (!enabled) return 1;
    transitionToHalfOpenIfDue();
    if (state === "open") {
      const remainingMs = openedAt + openMs - now();
      return Math.max(1, Math.ceil(remainingMs / 1000));
    }
    return 1;
  }

  return { allow, recordSuccess, recordFailure, snapshot, healthSnapshot, readyPayload, retryAfterSeconds };
}
