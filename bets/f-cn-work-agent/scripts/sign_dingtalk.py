#!/usr/bin/env python3
"""Print timestamp and DingTalk-like sign (hex hmac-sha256)."""
import hmac
import hashlib
import os
import sys

def main() -> int:
    ts = os.environ.get("DINGTALK_TS", "1710000100")
    secret = os.environ["DINGTALK_SECRET"]
    string_to_sign = f"{ts}\n{secret}".encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), string_to_sign, hashlib.sha256).hexdigest()
    print(ts)
    print(sig)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
