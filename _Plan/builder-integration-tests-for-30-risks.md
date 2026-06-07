# Plan: Builder Integration Tests for the 30 Risk Patterns

**Status:** Draft (not started)
**Created:** 2026-05-25
**Last updated:** 2026-05-25
**Triggering question:** "Does the 0.5.0 catalog expansion mean the agent will convert more patterns with less human oversight?"
**Honest gap surfaced by that question:** the 0.5.0 PR added 15 new catalog entries and 64 *structural* assertions on the catalog file, but ZERO assertions that downstream consumers (`m-query-analyst` detection + `fabric-bronze-builder`/`fabric-silver-builder` snippet emission) actually use the new entries correctly. The catalog is the source of truth; consumption is LLM-based and untested.

## Goal

Convert the soft claim *"the catalog has the right answer"* into the verifiable claim *"the builder reliably uses the right answer."* Specifically:

1. Every RISK-NN detection regex in `reference/m-conversion-risk-catalog.md` actually matches the M pattern it claims to.
2. The deterministic converter (`skills/m-to-pyspark-converter/scripts/convert_m_to_pyspark.py`) emits the catalog snippet (or a known placeholder) when fed a `.pq` file containing each pattern.
3. (Optional, on-demand) The `fabric-bronze-builder` agent — when given a `.pq` containing pattern X — emits a notebook with the right snippet AND, for multi-context patterns, picks the right context.

## Why this matters (the real risk this catches)

Today's failure modes that nothing in the repo tests for:
- **Catalog rot:** someone edits `**Detection:**` regex and it no longer matches the pattern it documents → analyst silently stops flagging it → builder converts wrong / leaves as unknown
- **Snippet rot:** someone edits the PySpark snippet (e.g. removes the `F.concat_ws` callout from RISK-30 and replaces with `F.concat`) and reintroduces the silent-NULL-propagation bug we just fixed in 0.5.0 `function_map.py`
- **LLM drift:** Claude version change causes the builder to pick a different context for `List.Count` (4 valid contexts; only 1 is right per call site) → notebooks silently start emitting the wrong form
- **Detection-vs-converter mismatch:** the analyst detects RISK-20 but `convert_m_to_pyspark.py` has no handler for it → notebook has `# TODO` instead of best-effort PySpark

These are exactly the failure modes the 0.5.0 PR is at risk of introducing for the 15 new patterns. None are caught by any current test.

## Anti-scope

Things this plan deliberately does NOT cover:
- **Notebook execution.** We test that the *right snippet* is emitted; we do NOT spin up a Spark session and execute the notebook against real data. Notebook execution is the validator's job (`agents/fabric-pipeline-validator/`).
- **Full orchestrator runs.** End-to-end `claude --agent fabric-migration-orchestrator ...` runs are out of scope — they take 5–10 minutes and cost real money. The orchestrator's own validation runs them in dry-run mode separately.
- **OneLake shortcut creation.** RISK-16 SharePoint.Files needs a Fabric admin action no test can perform; the test asserts the TODO marker is emitted, nothing more.

## Vertical slices

Each slice ships end-to-end (fixture → invocation → assertion → CI-runnable) on its own. Confidence and cost both increase with slice number.

---

### Slice 1 — Detection regex coverage (cheap, broad, catches catalog rot)

**Goal:** for each of the 30 RISK entries, prove the `**Detection:**` regex compiles AND matches a synthetic .pq fixture that contains the pattern.

**Vertical scope (in):**
- Test runner: `tests/test_risk_detection_regex.py` (new, standalone like the other 3 tests)
- Fixtures: `tests/fixtures/m_queries/risk_XX_<pattern_slug>.pq` — one per RISK ID, ~5–10 lines each, containing the pattern in a realistic minimal form
- Catalog parser: extract `**Detection:**` line from each RISK-NN section using the same regex split logic already in `tests/test_risk_catalog.py`
- Assertion: regex compiles without error AND `re.search(pattern, fixture_text)` returns a match

**Vertical scope (out):** does NOT invoke any agent, does NOT call the m-to-pyspark converter, does NOT execute any notebook.

**Per-layer deliverables:**
| Layer | Deliverable |
|---|---|
| Data | 30 .pq fixtures under `tests/fixtures/m_queries/` (~150 LOC total) |
| Processing | Catalog parser reusing `re.split(r"^## RISK-(\d+) ", ...)` from `test_risk_catalog.py` |
| Presentation | Test runner prints `PASS RISK-NN — <pattern_name> regex matched fixture` |
| Test | Itself — this slice IS the test |

**Tests (TDD red phase — write these before the runner):**
- 30 assertions: "RISK-NN's **Detection:** regex matches `tests/fixtures/m_queries/risk_NN_*.pq`"
- 1 assertion: every RISK-NN has a corresponding fixture file (catches "added catalog entry, forgot fixture")
- 1 assertion: every fixture file has a corresponding RISK-NN (catches "added fixture, forgot catalog entry")
- 1 assertion: every regex compiles (`re.compile(detection)` raises nothing) — this is the *first* failing test to write because it's the most basic guarantee

**Cost / runtime:** <1 second. Pure regex + file reads. Runs in CI on every commit.

**Success criteria:**
- All 32 assertions green
- `tests/preshipment_audit.py` still PASS (no regressions)
- Adding a 31st RISK entry without adding a fixture fails the test loudly
- Editing a detection regex to be syntactically broken fails the test loudly

**Security:** No external network, no auth, no LLM calls. Test fixtures contain only synthetic .pq snippets — no real customer M code, connection strings, or secrets. Fixture content must pass the same sanitization rules `report-unknown-patterns` already enforces (URLs, GUIDs, file paths get placeholder values).

**Demoable as:** `python tests/test_risk_detection_regex.py` — runs in <1s, prints 30 PASS lines.

**Slice-1 done means:** if anyone breaks a detection regex in the catalog, CI catches it before merge.

---

### Slice 2 — Static converter snippet emission (medium cost, tests the deterministic path)

**Goal:** for each of the 30 RISK patterns, prove `convert_m_to_pyspark.py` emits the expected PySpark substring (or the documented `# TODO` placeholder for High-severity todo-only entries) when fed the fixture .pq.

**Vertical scope (in):**
- Test runner: `tests/test_converter_emits_snippet.py` (new)
- Reuses Slice 1's fixtures (no new files needed)
- Expected-substring map: a small dict in the test file: `{"RISK-23": "F.lower", "RISK-30": "F.concat_ws", "RISK-16": "TODO", ...}` — derived from the catalog's recommended snippets but pinned in the test (NOT re-parsed from the catalog, so the test catches drift between catalog and converter)
- Invocation: `subprocess.run(["python", "skills/m-to-pyspark-converter/scripts/convert_m_to_pyspark.py", "--m-file", fixture_path], capture_output=True)`

**Vertical scope (out):** does NOT spawn the bronze/silver builder agent, does NOT invoke any LLM, does NOT verify the output is a valid `.ipynb` (that's Slice 3).

**Per-layer deliverables:**
| Layer | Deliverable |
|---|---|
| Data | Slice 1's fixtures + an expected-substring map (30 key/value pairs in the test) |
| Processing | Subprocess call to `convert_m_to_pyspark.py`; capture stdout |
| Presentation | Test prints `PASS RISK-NN — converter emitted "<substring>"` |
| Test | The substring assertion itself |

**Tests:**
- 30 assertions: "RISK-NN converter output contains the expected substring"
- 2 assertions: converter doesn't crash on any fixture (returncode 0 AND no Python exception in stderr)
- 1 assertion: for the 2 todo-only patterns (RISK-16 SharePoint.Files, possibly RISK-20 ReplaceErrorValues), output contains the literal string `TODO` or `HIGH RISK / HUMAN REVIEW REQUIRED`
- 1 negative assertion: RISK-30 output contains `F.concat_ws` AND does NOT contain `F.concat(` (without the `_ws` suffix) — pinning the 0.5.0 fix so the bug can't silently regress

**Cost / runtime:** ~30 seconds (30 subprocess calls × ~1s each). Still cheap enough for CI on every commit, but maybe slow enough to gate behind a `make test-slow` rather than the default audit.

**Success criteria:**
- All 34 assertions green
- Editing the converter's case for `Text.Lower` to emit `F.upper` (typo) fails the test
- Removing a pattern's converter case entirely fails the test
- The 0.5.0 `F.concat → F.concat_ws` fix in `function_map.py` is permanently locked in

**Security:** Same as Slice 1 — no network, no auth, no secrets. Subprocess invocation is local-only; converter takes a single `--m-file` arg, no shell injection surface (use `subprocess.run` with a list, never `shell=True`).

**Risks / open questions:**
- **Does the static converter actually handle all 30 patterns today?** Almost certainly not — it had a function map of ~50 entries before 0.5.0, with no per-RISK handlers. Slice 2 will surface this honestly: the first run will show how many of the 30 the converter ACTUALLY produces useful output for vs how many fall through to `# unknown`. This is itself a finding worth shipping.
- If the converter falls through for many, Slice 2 becomes a forcing function for converter improvements OR for relaxing the expected-substring to accept `# unknown` placeholders for patterns the static converter genuinely can't handle (and the LLM has to handle in Slice 3).

**Demoable as:** `python tests/test_converter_emits_snippet.py` — prints 30 PASS lines + a coverage summary (`24/30 patterns produce best-effort PySpark; 6 require LLM-level handling`).

**Slice-2 done means:** if anyone breaks the deterministic converter path for a pattern, CI catches it; the 0.5.0 silent-NULL-propagation fix is locked.

---

### Slice 3 — Builder agent end-to-end snapshot (expensive, opt-in, tests LLM judgment)

**Goal:** for each multi-context pattern (5 patterns: RISK-18, 19, 27, 28, 29 — plus RISK-16, 20 for the High markers), spawn the real `fabric-bronze-builder` agent on a minimal synthetic project containing one .pq file, capture the emitted notebook, assert the right snippet AND the right context choice appear.

**Vertical scope (in):**
- Test runner: `tests/test_builder_agent_e2e.py` (new, opt-in via env var `RUN_LLM_TESTS=1`)
- Synthetic project fixture: minimal `2 - Source Files/m_queries/<test>/<test>.pq` + `6 - Agentic Resources/reference/m-conversion-risk-catalog.md` (copied from the real catalog)
- Builder invocation: `Agent(subagent_type: "fabric-dataflow-migration-toolkit:fabric-bronze-builder:fabric-bronze-builder", prompt: ..., mode: "acceptEdits")` — issued from the test runner via a small Python wrapper that uses Claude Agent SDK (or marks the test SKIP if SDK not installed)
- Snapshot file: `tests/snapshots/risk_NN_expected.ipynb_substring` — pinned subsection of the expected notebook output
- Assertion: emitted notebook contains the snapshot substring

**Vertical scope (out):** does NOT run the full orchestrator, does NOT execute the emitted notebook against Spark, does NOT validate the notebook against Fabric.

**Per-layer deliverables:**
| Layer | Deliverable |
|---|---|
| Data | 7 synthetic project fixtures (one per multi-context or High pattern) under `tests/fixtures/projects/risk_NN/` |
| Processing | Python wrapper that calls `claude --agent ...` or uses the Agent SDK; captures the emitted .ipynb |
| Presentation | Test prints `PASS RISK-NN — builder emitted <context_label>` |
| Test | Snapshot comparison (substring match, NOT byte-equal — LLM output varies) |

**Tests:**
- For each multi-context pattern (RISK-18, 19, 27, 28, 29): 2 fixtures per pattern — one in Context A, one in Context B; assert builder picks the right one for each
- For RISK-16 SharePoint.Files: assert emitted notebook contains `HIGH RISK / HUMAN REVIEW REQUIRED` AND `OneLake shortcut` AND the `learn.microsoft.com/fabric/onelake/create-onedrive-sharepoint-shortcut` URL
- For RISK-20 Table.ReplaceErrorValues: assert emitted notebook contains `HIGH RISK` AND either `fillna` or `try_cast`
- 1 assertion: total LLM cost stays under $X per full run (track via response metadata if available)

**Cost / runtime:** ~5–15 minutes for a full run (~12 agent spawns × ~30–60s each), real Claude API cost (estimate: $0.50–$2.00 per full run depending on model). NOT CI-gated by default — opt-in via `RUN_LLM_TESTS=1 python tests/test_builder_agent_e2e.py`. Recommended cadence: run before each catalog edit AND before each plugin release.

**Success criteria:**
- All snapshot assertions green when `RUN_LLM_TESTS=1`
- Snapshot updates require explicit `--update-snapshots` flag (so accidental LLM drift can't silently rewrite the expectations)
- Test SKIPs cleanly (exit 0) when `RUN_LLM_TESTS` is unset OR Agent SDK unavailable
- The five multi-context patterns each have at least 2 fixtures exercising different contexts

**Security:**
- **API keys handling:** Test reads `ANTHROPIC_API_KEY` from env (never hardcodes); skips if unset. Do not log key value. Do not commit `.env` files.
- **Synthetic fixtures only:** Same sanitization rule as Slices 1+2 — no real customer M code. Use `tests/fixtures/projects/.gitignore` to exclude any accidental real-data dumps.
- **Cost cap:** Wrapper should set a max-tokens budget per spawn (e.g., 50K) and abort if any single spawn exceeds it. Prevents accidental runaway cost.
- **Reproducibility:** Pin Claude model ID in test wrapper (e.g., `claude-sonnet-4-6` for cost; `claude-opus-4-7` if precision matters). Document which model the snapshots were captured against; CI runs MUST use the same model.

**Risks / open questions:**
- **LLM non-determinism:** even with temperature 0, builder output isn't byte-identical run-to-run. Snapshots must be *substring* assertions (e.g. "emitted code contains `F.concat_ws`"), NOT diff-style snapshots. Same trade-off `vcr.py` etc. solve in other ecosystems but adds tape-management complexity not worth it here.
- **Agent SDK availability:** if the SDK isn't pip-installable in the user's env, the test must SKIP gracefully — never fail with `ImportError`.
- **Fabric workspace dependency:** the bronze-builder agent today only writes a `.ipynb` to disk; it does NOT deploy to Fabric. So this test does NOT need a real Fabric workspace. (Verify before starting Slice 3 — if any builder side-effect changes this, the test scope changes too.)
- **Cost scaling:** if the plugin grows to 50+ patterns, full Slice 3 runs may exceed $5 each. Consider sampling — random 5 patterns per CI run, full sweep nightly.

**Demoable as:** `RUN_LLM_TESTS=1 python tests/test_builder_agent_e2e.py` — prints PASS lines as each agent finishes, total cost summary at the end.

**Slice-3 done means:** LLM-version drift, builder-prompt drift, and catalog/builder consumption mismatches are all caught — but only by an opt-in human-triggered run, NOT by every-commit CI.

---

## Implementation order + dependencies

Strict order. Slice N+1 depends on Slice N's fixtures.

1. **Slice 1 first** — 1 hour of work, ships value immediately, zero LLM dependency. Catalog rot is the most likely failure mode and the cheapest to catch.
2. **Slice 2 second** — 2–3 hours including any converter fixes the test surfaces. Will reveal honest converter coverage (probably 15–20 of 30 patterns produce useful output today; the gap itself is a finding worth shipping as a 0.5.1 release note).
3. **Slice 3 last** — 4–6 hours including snapshot capture + cost-cap wrapper. Optional from a release-gating perspective; recommended before any major catalog edit AND before any new model rollout.

**Total estimate:** 7–10 hours across all 3 slices. Slice 1 alone is the highest leverage 1 hour to spend.

## Test plan (cross-slice)

The plan IS test-first (TDD). Each slice's "Tests" subsection enumerates failing tests to write first; implementation makes them pass. Done criteria for each slice include CI integration.

| Slice | Test runner | LOC estimate | CI inclusion |
|---|---|---|---|
| 1 | `tests/test_risk_detection_regex.py` | ~100 | Always |
| 2 | `tests/test_converter_emits_snippet.py` | ~150 | Always (or `make test-slow` if 30s is too slow for default) |
| 3 | `tests/test_builder_agent_e2e.py` | ~300 + snapshots | Opt-in via env var |

`tests/preshipment_audit.py` already runs the other three test files indirectly via its "required files" gate; add the new test files to its expected-files list as each slice ships.

## Security plan (cross-slice)

| Concern | Mitigation |
|---|---|
| Fixture leakage of real M code | Synthetic fixtures only; PR review checks for URLs, GUIDs, table/column names that look real; sanitization rules from `report-unknown-patterns/scripts/report_patterns.py:SANITIZE_RULES` re-applied as a pre-commit hook on `tests/fixtures/` |
| LLM API key leakage (Slice 3) | Read from env, never hardcode; CI uses GitHub-Actions-encrypted secret; key never logged; `.env` excluded via `.gitignore`; test SKIPs on missing key rather than failing loudly with key value in trace |
| Runaway LLM cost | Per-spawn token budget; total per-run cost cap; CI cancels job if cumulative cost > $X |
| Subprocess injection (Slice 2) | `subprocess.run(list, shell=False)`; never f-string user input into command; fixture paths validated against an allowlist regex `^tests/fixtures/m_queries/risk_\d+_[\w.]+\.pq$` before passing to subprocess |
| Snapshot tampering | Snapshots are committed alongside the test; PR diff must show snapshot edits explicitly; `--update-snapshots` requires explicit human flag (no auto-update on failure) |

## Success criteria (whole plan)

- **Slice 1 done:** 32 assertions green; CI runs on every commit; editing a detection regex in the catalog to be malformed fails the build
- **Slice 2 done:** 34 assertions green; the 0.5.0 `F.concat_ws` fix is permanently locked; coverage summary published in CI output (e.g. "Static converter covers 22/30 patterns")
- **Slice 3 done:** snapshots captured for all 7 critical patterns; opt-in test runnable in <15 min for under $3 cost per run; documented in `CONTRIBUTING.md` as the gate before catalog edits
- **Whole plan done:** the original honest gap — "catalog has the right answer but nothing tests builder consumption" — is closed. Catalog rot, converter regression, and LLM drift are all caught at the appropriate price points (free / cheap / opt-in).

## Open questions before starting

1. **Does the m-to-pyspark-converter script currently handle each of the 30 RISK patterns, or does it fall through to `# unknown` for many?** Slice 2 will answer this empirically — first run gives the honest baseline. Slice 2's expected-substring map needs to accept `# unknown` for patterns the static converter genuinely can't handle, with a note that those patterns rely on LLM-level handling (which Slice 3 then verifies).
2. **Which Claude model do snapshots target?** Default to whatever the user runs in their daily migrations (probably Opus 4.7 per `agents/fabric-migration-orchestrator/agent.md` if model is pinned there; otherwise document the default). Snapshots are model-specific; CI MUST match.
3. **Are bronze-builder agent prompts deterministic enough to snapshot?** Probably yes if model temperature is 0 and the prompt + .pq input are identical, but verify on first capture. If output drifts even at temp 0, fall back to substring assertions and abandon byte-snapshot ambition.
4. **CI cost budget?** Slice 1+2 are free. Slice 3 needs explicit budget approval before enabling in CI. Until then, run locally before catalog edits.

## Out-of-scope follow-ons (NOT this plan)

- Performance testing of the converter (Slice 2 already times each subprocess; if any exceeds 5s, flag for refactor — but not as part of this plan)
- Cross-version Spark testing (e.g. RISK-24 `F.btrim` requires Spark 3.5+; tests do NOT verify the fallback path executes on older Spark)
- Notebook validity testing (`fabric-pipeline-validator` agent already covers this in real migrations; tests do NOT spin up a Fabric workspace)
- Catalog auto-generation from a richer source (e.g. machine-readable RISK-NN entries) — interesting but separate plan
