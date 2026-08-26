# ROADMAP · C · agent-ci

Bet-local. Portfolio root ROADMAP is updated separately.

## Shipped here

- [x] Promptfoo JSON → JUnit/TAP adapter (`from-promptfoo`; existing reporters)
- [x] Composite Action (action.yml; results and/or command, fail-under, junit)
- [x] Example workflow + artifact upload (examples/github-actions/agent-ci-promptfoo.yml)
- [x] Checked-in good/bad fixtures (no network promptfoo in smoke)
- [x] Existing DeepEval/Inspect-shaped JUnit/TAP/Markdown emit kept
- [x] Optional DeepEval JSON adapter (`from-deepeval`; fixture-only, not full compatibility)
- [x] GitHub Action job summary (GFM pass/fail table from fixture eval; `$GITHUB_STEP_SUMMARY`; no live keys)

## Still open

- [ ] Live `npx promptfoo eval` in a consumer repo (needs Node + provider keys)
- [ ] Copy action.yml into a standalone repo if this bet is extracted
- [ ] Hosted runner seats / real GitHub Checks token posting (paid later)
