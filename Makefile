# oss-cash-lab portfolio orchestration
.PHONY: list smoke local-mvp wire-a-to-b dogfood-a-b dogfood-a-c dogfood-a-d dogfood-a-e dogfood-a-f demo-f stack-demo compose-smoke security-scan check-k8s check-helm check-dockerfiles check-gha-examples check-grafana check-prom-rules check-oss-hygiene check-mcp-examples version help

ROOT := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))

help:
	@echo Targets: list smoke local-mvp wire-a-to-b dogfood-a-b dogfood-a-c dogfood-a-d dogfood-a-e dogfood-a-f demo-f stack-demo compose-smoke security-scan check-k8s check-helm check-dockerfiles check-gha-examples check-grafana check-prom-rules check-oss-hygiene check-mcp-examples version
	@echo Version source of truth: $(ROOT)VERSION

list:
	@echo OSS Cash Lab bets:
	@echo "  A  bets/a-sdk-mcp-gen     (TypeScript) local-mvp"
	@echo "  B  bets/b-mcp-gateway     (TypeScript) local-mvp"
	@echo "  C  bets/c-agent-ci        (Python)     local-mvp"
	@echo "  D  bets/d-ai-bom          (Python)     local-mvp"
	@echo "  E  bets/e-otel-ai-cost    (TypeScript) local-mvp"
	@echo "  F  bets/f-cn-work-agent   (Python)     local-mvp"
	@echo Phase priority: 1=B+C  2=A+D  3=E+F
	@echo Stack demo: make stack-demo  # B+C+D+E+F HTTP without Docker
	@echo Dogfood A→B OpenAPI: make dogfood-a-b
	@echo Dogfood A→C OpenAPI: make dogfood-a-c
	@echo Dogfood A→D OpenAPI: make dogfood-a-d
	@echo Dogfood A→E OpenAPI: make dogfood-a-e
	@echo Dogfood A→F OpenAPI: make dogfood-a-f
	@echo Security scan: make security-scan  # ai-bom + secret grep (separate from local-mvp)
	@echo K8s manifests: make check-k8s  # parse-only deploy/k8s (also hooked from smoke; no cluster)
	@echo Helm chart: make check-helm  # parse-only deploy/helm (also hooked from smoke; helm template if helm on PATH; skip like docker)
	@echo Dockerfiles: make check-dockerfiles  # parse-only B-F FROM/EXPOSE/CMD/HEALTHCHECK /health (also hooked from smoke; skip docker build if no docker)
	@echo GHA examples: make check-gha-examples  # parse-only examples/github-actions A OpenAPI drift + C JUnit + run-vs-run diff + D SARIF + E GHA annotations (also hooked from smoke)
	@echo Grafana JSON: make check-grafana  # parse-only deploy/grafana (also hooked from smoke; no Grafana process)
	@echo Prometheus rules: make check-prom-rules  # parse-only deploy/prometheus + prometheusrule.yaml (also hooked from smoke; no Prometheus)
	@echo OSS hygiene: make check-oss-hygiene  # NOTICE + .editorconfig + SECURITY.md + CODE_OF_CONDUCT.md (also hooked from smoke; no restyle)
	@echo MCP client example: make check-mcp-examples  # parse-only examples/mcp B HTTP gateway snippet (also hooked from smoke; no Cursor)
	@echo Portfolio version: make version  # reads root VERSION

smoke:
	@bash "$(ROOT)scripts/smoke.sh"

local-mvp:
	@bash "$(ROOT)scripts/local-mvp.sh"

wire-a-to-b:
	@bash "$(ROOT)scripts/wire-a-to-b.sh"

dogfood-a-b:
	@bash "$(ROOT)scripts/generate-gateway-sdk.sh"

dogfood-a-c:
	@bash "$(ROOT)scripts/generate-runner-sdk.sh"

dogfood-a-d:
	@bash "$(ROOT)scripts/generate-bom-sdk.sh"

dogfood-a-e:
	@bash "$(ROOT)scripts/generate-cost-sdk.sh"

dogfood-a-f:
	@bash "$(ROOT)scripts/generate-agent-sdk.sh"

demo-f:
	@bash "$(ROOT)bets/f-cn-work-agent/scripts/demo-ask-reply.sh"

stack-demo:
	@bash "$(ROOT)scripts/local-stack.sh"

compose-smoke:
	@bash "$(ROOT)scripts/compose-smoke.sh"

security-scan:
	@bash "$(ROOT)scripts/security-scan.sh"

check-k8s:
	@bash "$(ROOT)scripts/check-k8s.sh"

check-helm:
	@bash "$(ROOT)scripts/check-helm.sh"

check-dockerfiles:
	@bash "$(ROOT)scripts/check-dockerfiles.sh"

check-gha-examples:
	@bash "$(ROOT)scripts/check-gha-examples.sh"

check-grafana:
	@bash "$(ROOT)scripts/check-grafana.sh"

check-prom-rules:
	@bash "$(ROOT)scripts/check-prometheus-rules.sh"

check-oss-hygiene:
	@bash "$(ROOT)scripts/check-oss-hygiene.sh"

check-mcp-examples:
	@bash "$(ROOT)scripts/check-mcp-examples.sh"

# Single source of truth: ./VERSION (bets may mirror in package.json / pyproject / CLI constants)
version:
	@cat "$(ROOT)VERSION"
