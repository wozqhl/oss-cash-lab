#!/usr/bin/env python3
"""Print WeCom-like msg_signature for token/timestamp/nonce/encrypt."""
import hashlib
import os
import sys

def main() -> int:
    token = os.environ["WECOM_TOKEN"]
    ts = os.environ.get("WECOM_TS", "1710000200")
    nonce = os.environ.get("WECOM_NONCE", "wnonce")
    if len(sys.argv) >= 2 and sys.argv[1] != "-":
        encrypt = sys.argv[1]
    else:
        encrypt = sys.stdin.read()
    pieces = sorted([token, ts, nonce, encrypt])
    sig = hashlib.sha1("".join(pieces).encode("utf-8")).hexdigest()
    print(ts)
    print(nonce)
    print(sig)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
