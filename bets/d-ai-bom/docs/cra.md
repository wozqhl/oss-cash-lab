# EU Cyber Resilience Act (CRA) notes

This page is **orientation for operators**, not legal advice and **not a certification**.
ai-bom does not claim CRA conformity, CE marking, notified-body assessment, or BSI approval.

Official CRA overview (European Commission):
<https://digital-strategy.ec.europa.eu/en/policies/cyber-resilience-act>

Regulation (EU) **2024/2847** entered into force on **10 December 2024**.

## Article 14 vs December 2027

Two dates people mix up:

| When | What |
|------|------|
| **11 September 2026** | **Article 14** reporting obligations begin (manufacturer vulnerability / severe-incident reporting). This is **not** the date when a machine-readable SBOM becomes a general essential requirement. |
| **11 December 2027** | Full **essential cybersecurity requirements** apply, including the obligation to identify and document components (the CRA “SBOM” duty for in-scope products with digital elements). |

Until December 2027, an SBOM export from this tool is a **preparation / inventory aid**, not proof that a product meets CRA essential requirements. After that date, manufacturers still need their own legal assessment of scope, product class, and residual risk. This scanner does not decide whether your product is in scope.

**Article 14 (from 11 September 2026)** is a **24-hour reporting clock** (actively exploited vulnerabilities / severe incidents). That clock needs two mechanical pieces this tool can help with: an **inventory** of what you ship, and a **match** against issues you already know about. It does **not** need a complete NVD mirror. This repo ships a conservative offline gate: `scan --advisories <file> --gate-vulns` compares scanned component name/purl/version and recorded versionRange operators to a **local fixture**. Shipped IDs are `ADV-FIXTURE-*` placeholders, not real CVE matches against the internet. A buyer who later trusts OSV or GitHub Advisory can run `convert-advisories --from-osv` on an offline dump and point `--advisories` at the export — the CLI still does not fetch NVD/OSV/GHSA. A green gate is “no hit in *this* file,” not “no CVEs exist.”

BSI **TR-03183-2** (German interpretation of CRA SBOM practice) treats **CycloneDX 1.6+** or **SPDX 3.0.1+** as the expected machine-readable forms. This tool emits **CycloneDX 1.7** (JSON and XML), **SPDX 2.3** (JSON and XML, existing consumers), and **SPDX 3.0.1** JSON (`--format spdx3`). CycloneDX 1.7 satisfies the CycloneDX 1.6+ reading; SPDX 3.0.1 satisfies the SPDX 3.0.1+ reading. The “either format” claim is therefore honest. SPDX 2.3 remains available and does **not** itself claim SPDX 3 compatibility.

## What this tool emits

- **Internal AI-BOM JSON** (default): CycloneDX-like `bomFormat` + `specVersion` plus a custom `summary` (policy hits, license counts). Not a conformance document.
- **CycloneDX 1.7** (`--format cyclonedx` / `cyclonedx-xml`): `bomFormat=CycloneDX`, `specVersion=1.7`, XML `xmlns` `http://cyclonedx.org/schema/bom/1.7`. Components keep `type` / `name` / `version` / `purl` / `licenses[]`. Models map to `machine-learning-model` with a `modelCard` filled **only** from scan data the scanner already has (`aibom:format` such as `gguf`, `aibom:sourcePath` basename). Prompts map to `data` + a `data[]` configuration entry (name only — **no file contents**). Policy hits are BOM `properties` (`aibom:policyHits`, optional `aibom:forbiddenLicenses`), **not** `vulnerabilities`.
- **SPDX 2.3** (`--format spdx` / `spdx-xml`): packages + `licenseConcluded` from scanned manifests (existing consumers unchanged).
- **SPDX 3.0.1** (`--format spdx3`): compact JSON with `spdxId`, `name`, `creationInfo.specVersion=3.0.1`, and `element` packages/licenses from the same scan. `ai_AIPackage` + `profileConformance` `ai` only when a model path+sha256 or model-card fields were observed. Not a full SPDX 3 graph (no invented files, hashes, metrics, trainedOn datasets, security profile, or CBOM).
- **SARIF 2.1.0** / Markdown / GHA annotations / HTML: review formats, not SBOMs.
- **License-policy gate**: `policies/default.json` `forbiddenLicenseIds` (GPL-3.0 / AGPL-3.0 / SSPL-1.0 + variants). `--gate-licenses` exits **1** on a match; `--strict` also fails on pickle / disclosure gaps.
- **Advisory-match gate** (Article 14 inventory+match): `scan --advisories examples/advisories/sample.json --gate-vulns` exits **1** on a local-list hit. Offline OSV/GHSA dumps go through `convert-advisories --from-osv` into the same schema. Not a CVE database.
- **OpenVEX 0.2.0** (`scan --advisories FILE --vex out.json`; packed as `vex.json` in `evidence-pack`): exploitability statements from observed local-fixture matches only. Status is derived (`affected`; `not_affected` only with a justification the fixture recorded; otherwise `under_investigation`; `fixed` only when the fixture records `fixedVersion`). VEX is an exploitability statement helper for Article 14-style reporting, **not** a CRA conformity claim.

CycloneDX has supported **ML-BOM** since **1.5**. Spec **1.7** was published **21 October 2025**. The OWASP **Authoritative Guide to ML-BOM** (10 June 2026):
<https://cyclonedx.org/guides/OWASP_CycloneDX-Authoritative-Guide-to-AI-ML-BOM-en.pdf>

## What this tool does **not** claim

- CRA, EU AI Act, or any other **certification**, attestation, or CE mark.
- Completeness of the component inventory (heuristic directory scan; caps; no registry enrichment).
- Vulnerability intelligence, exploitability, NVD completeness, or Article 14 incident reporting. The advisory gate only matches a file you pass in.
- A full SPDX 3 relationship graph, cryptographic-asset (CBOM) completeness, or model-card / AI-profile fields the scan did not observe (no invented architecture, datasets, metrics, trainedOn, or energy). SPDX 3.0.1 export is compact; AI profile appears only when observed.
- That emitting CycloneDX 1.7 **equals** CRA essential-requirement compliance.

Use the license fixtures to see the gate, not a regulator:

```bash
cd bets/d-ai-bom
export PYTHONPATH=src
python3 -m ai_bom scan examples/cra-fixtures/license-pass --policy policies/default.json --gate-licenses
python3 -m ai_bom scan examples/cra-fixtures/license-fail --policy policies/default.json --gate-licenses

# Article 14 inventory+match (local fixture; not NVD)
python3 -m ai_bom scan examples/sample-app --advisories examples/advisories/sample.json --gate-vulns
python3 -m ai_bom scan examples/sample-app --advisories examples/advisories/clean.json --gate-vulns

# Offline OSV dump → same schema (no fetch)
python3 -m ai_bom convert-advisories --from-osv examples/advisories/osv-sample.json --out /tmp/from-osv.json
python3 -m ai_bom scan examples/sample-app --advisories /tmp/from-osv.json --gate-vulns
python3 -m ai_bom evidence-pack --dir examples/sample-app --out /tmp/cra-pack
# optional calendar freeze + zip: --as-of 2026-08-26 --zip /tmp/cra-pack.zip
```

## Window clock (calendar helper, not a certificate)

`evidence-pack` writes `pack.json` (also listed in `--zip` and MANIFEST) with a **`clock`** section:

| Field | Meaning |
|-------|---------|
| `asOf` | UTC calendar date used for the math (default today; `--as-of YYYY-MM-DD`) |
| `windows.article14Reporting` | daysUntil / daysOverdue vs **2026-09-11** |
| `windows.sbom` | daysUntil / daysOverdue vs **2027-12-11** |
| `observedVulns[]` | Each `--gate-vulns` / converted-advisory hit inherits those same two windows |

Print the same windows **without** packing a zip (from `bets/d-ai-bom`; default as-of today UTC):

```bash
python3 -m pip install -e .
ai-bom clock --format text
# equivalent: python3 -m ai_bom clock --format text
```

This is a **calendar/evidence helper**. It is **not** a CRA compliance certificate, conformity claim, CE mark, or notified-body assessment. A fixture `ADV-FIXTURE-*` hit showing `daysUntil=16` on `--as-of 2026-08-26` only means the calendar offset was computed — not that a report is due, not that a CVE exists, and not that the product is in scope.


## OpenVEX (exploitability helper, not a claim)

`scan --advisories <file> --vex out.json` (and `evidence-pack` `vex.json`) emits an **OpenVEX 0.2.0** document whose statements are generated **only** from components the scanner actually saw against the local advisory fixture. Status is derived, never invented: a real fixture match is `affected`; a match whose recorded `versionRange` excludes the observed version is `not_affected` **only if** the fixture recorded a spec justification (otherwise `under_investigation`); `fixed` is emitted only when the fixture literally records a `fixedVersion` equal to the observed version. This is an exploitability statement helper for Article 14-style reporting. It is **not** a CRA conformity claim, CE mark, or notified-body assessment. **中文:** OpenVEX 是第 14 条风格报告的可利用性声明辅助，**不是**符合性主张。

## 中文（摘要）

《网络弹性法案》Regulation (EU) 2024/2847 于 **2024-12-10** 生效。**第 14 条**报告义务自 **2026-09-11** 起；含 SBOM 在内的完整基本要求自 **2027-12-11** 起适用。二者不是同一天。

本工具导出 **CycloneDX 1.7**（JSON/XML）、**SPDX 2.3**（兼容旧消费者）与 **SPDX 3.0.1** JSON（`--format spdx3`），并带许可证策略门禁（`--gate-licenses`）与**本地 advisory 对照门禁**（`--advisories` + `--gate-vulns`）。第 14 条（2026-09-11）是 24 小时报告钟，需要库存+对照已知问题，不是 NVD 全量库；完整 SBOM 基本要求仍自 **2027-12-11** 起。买家日后可将 OSV / GitHub Advisory 离线导出经 `convert-advisories --from-osv` 转成同一 JSON，CLI 不联网拉取。`evidence-pack` 的 `pack.json` 含 **window clock**（`daysUntil` / `daysOverdue` 相对上述两日，观察到的 fixture 漏洞继承同一日历）。**这是日历/证据辅助，不是 CRA 合格证书。** 这是库存/准备辅助，**不是** CRA 合格评定、CE 标志或 BSI 认证。BSI TR-03183-2 的解读是 CycloneDX 1.6+ **或** SPDX 3.0.1+；二者现均可导出，故“任一格式”的说法是诚实的。未观察到的 SPDX 3 图/模型卡字段不会编造。正式页面：<https://digital-strategy.ec.europa.eu/en/policies/cyber-resilience-act>；ML-BOM 指南：<https://cyclonedx.org/guides/OWASP_CycloneDX-Authoritative-Guide-to-AI-ML-BOM-en.pdf>。
