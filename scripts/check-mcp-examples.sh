#!/usr/bin/env bash
# Parse-only check for examples/mcp (HTTP MCP client config). No Cursor, no B process.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec python3 "$ROOT/scripts/check-mcp-examples.py" "$ROOT"
