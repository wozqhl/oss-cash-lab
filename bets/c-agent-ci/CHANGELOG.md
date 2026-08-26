# Changelog · C · agent-ci

Bet-local notes. Portfolio root CHANGELOG is updated separately.

The format is based on Keep a Changelog.

## [Unreleased]

### Added

- Promptfoo adapter (`from-promptfoo`): read Promptfoo `eval --output` JSON
  (`results.results[].success` / `gradingResult`, plus outputs[] / table
  shapes) and emit JUnit XML + TAP13 via the existing reporters. Not a
  third eval DSL — wrap Promptfoo / keep DeepEval-shaped JUnit/TAP.
- Composite GitHub Action at action.yml (results path and/or a command
  that produces the JSON, fail-under, junit/tap paths). Consumers:
  `uses: wozqhl/oss-cash-lab/bets/c-agent-ci@main`. Fails on quality gate.
- Copy-paste workflow `examples/github-actions/agent-ci-promptfoo.yml`
  plus upload-artifact@v4. Smoke uses a checked-in fixture (no network
  promptfoo install). Optional live `npx promptfoo eval` documented.
- Fixtures `fixtures/promptfoo/good.json` (exit 0) and `bad.json` (exit 1).
- DeepEval-shaped JSON adapter (`from-deepeval`): map a consumer dump (`test_results[]` / `testCases[]` name/success/metrics) to the existing JUnit/TAP/Markdown reporters + `--fail-under`. Not full DeepEval compatibility; fixtures `fixtures/deepeval/good.json` / `bad.json` (no live DeepEval).
- GitHub Action job summary: `from-promptfoo` / `from-deepeval` write the existing GFM pass/fail table (`--md` / `--format md`) and append to `$GITHUB_STEP_SUMMARY` when that env is set. Composite Action `md` input (default `report.md`). Fixture-only; no live promptfoo / DeepEval / invented scores. smoke `gha-summary-ok`.
