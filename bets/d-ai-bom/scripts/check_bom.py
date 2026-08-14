import json
from pathlib import Path
bom = json.loads(Path("out/bom.json").read_text())
assert bom.get("bomFormat") == "CycloneDX"
comps = bom["components"]
assert comps
names = " ".join(c.get("name", "") for c in comps).lower()
assert "openai" in names
assert any("bert" in (c.get("name") or "").lower() or "huggingface" in (c.get("name") or "").lower() for c in comps)
assert any((c.get("name") or "").endswith(".gguf") or c.get("format") == "gguf" for c in comps)
assert any(c.get("type") == "mcp-server" for c in comps)
# SPDX / CycloneDX licenses on components
assert all(isinstance(c.get("licenses"), list) and c["licenses"] for c in comps), "every component needs licenses[]"
assert any(
    (e.get("license") or {}).get("id") == "MIT"
    for c in comps
    for e in (c.get("licenses") or [])
), "expected MIT from sample-app package.json"
assert "MIT" in json.dumps(bom)
lic_summary = (bom.get("summary") or {}).get("licenses") or {}
assert lic_summary.get("MIT", 0) >= 1, lic_summary
print("bom checks ok", len(comps), "components", "licenses=", lic_summary)
