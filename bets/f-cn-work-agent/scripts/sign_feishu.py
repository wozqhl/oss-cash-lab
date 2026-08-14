#!/usr/bin/env python3
"""Print timestamp, nonce, signature for a request body (stdin or argv)."""
import hashlib
import os
import sys

def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] != "-":
        body = sys.argv[1].encode("utf-8")
    else:
        body = sys.stdin.buffer.read()
    ts = os.environ.get("FEISHU_TS", "1710000000")
    nonce = os.environ.get("FEISHU_NONCE", "nonce-mvp")
    key = os.environ["FEISHU_ENCRYPT_KEY"]
    sig = hashlib.sha256((f"{ts}{nonce}{key}").encode("utf-8") + body).hexdigest()
    print(ts)
    print(nonce)
    print(sig)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
