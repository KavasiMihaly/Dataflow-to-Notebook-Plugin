---
name: report-unknown-patterns
description: Optional. Reads `_Documentation/conversion-backlog.md` (auto-populated by m-query-analyst when unknown M patterns are detected), sanitizes the M snippets to redact connection strings and identifiers, and creates one GitHub issue per pattern against the plugin repo so the plugin author can add the pattern to the risk catalog in a future release. Privacy-preserving — preview the redacted output before posting and skip patterns marked sensitive. Only invoked when the user opts in via userConfig or the migration-analyst question.
allowed-tools: Bash Read Edit
---

# Report Unknown Patterns

This is an **opt-in** skill. It runs only when the user explicitly agrees — either by setting the `report_unknown_patterns` userConfig to `always`, or by answering "yes" to the migration-analyst's pattern-sharing question. The orchestrator does NOT invoke this skill silently.

## What it does

1. Read `_Documentation/conversion-backlog.md` — the table of unknown M patterns the converter encountered but doesn't have a reference example for.
2. For each row with `Status = Backlog` (i.e., not yet reported):
   - Extract the pattern name, sample M snippet, file references, occurrence count
   - **Sanitize** the M snippet by replacing:
     - URLs / connection strings with `<REDACTED_URL>`
     - GUIDs (workspace IDs, query IDs) with `<REDACTED_GUID>`
     - Quoted file paths matching `["'][^"']*\.(csv|xlsx|json|parquet)["']` with `<REDACTED_PATH>`
     - Identifiers matching common business-data patterns (postcodes, NHS codes, etc.) with `<REDACTED_DATA>`
   - Show the user the **before/after** sanitized snippet for review
   - Ask via `AskUserQuestion`: post / skip / additional-redactions-needed
3. For each approved pattern, run `gh issue create` against the plugin repo:
   - Title: `[Pattern] <pattern_name> — convert to PySpark`
   - Body: pattern signature, sanitized M snippet, sample file count, suggested mitigation if known
   - Label: `conversion-pattern`, `community-submitted`
4. Update `conversion-backlog.md` row's `Status` from `Backlog` to `Reported (#issue_number)`.

## Why opt-in only

Power Query M code can contain proprietary business logic, connection strings, schema names, and data identifiers. Auto-posting to a public GitHub repo without explicit consent is a leak risk. This skill enforces consent two ways:

1. **Skill is never invoked autonomously.** The orchestrator only calls it when `migration-design.md` Section 5 records `Report patterns: yes` (set via userConfig hard-code or the runtime question).
2. **Per-pattern approval.** Even when the skill runs, every pattern gets a sanitized preview and explicit user approval before any `gh` call.

For sensitive enterprises, leave `report_unknown_patterns` as `never` (the default behavior is to record patterns locally only).

## Prerequisites

- `gh` CLI installed and authenticated (`gh auth login` once before invoking)
- The plugin repo (where issues will be filed) is the one declared in plugin.json's `repository` field

## Usage

### Auto-invoked at Stage 13 (when user opted in)

The orchestrator runs this at the end of the pipeline if Section 5 recorded `yes`. No manual action needed.

### Manual invocation (any time)

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/report-unknown-patterns/scripts/report_patterns.py"
```

### Dry-run (preview only, no issues created)

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/report-unknown-patterns/scripts/report_patterns.py" --dry-run
```

Prints what would be reported without calling `gh`. Recommended first run.

### Specific patterns only

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/report-unknown-patterns/scripts/report_patterns.py" --pattern "Web.Contents"
```

### Custom backlog path

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/report-unknown-patterns/scripts/report_patterns.py" --backlog "_Documentation/conversion-backlog.md"
```

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `--backlog` | no | Path to backlog file. Default: `_Documentation/conversion-backlog.md` |
| `--pattern` | no | Filter to one pattern name (substring match) |
| `--dry-run` | no | Preview without creating issues |
| `--repo` | no | Override target repo. Default: read from plugin.json `repository` |
| `--auto-approve` | no | Skip per-pattern preview prompt. Use with care — only when you trust the sanitization |
| `--json` | no | Output JSON envelope |

## Output

JSON envelope:

```json
{
  "status": "success|partial|skipped",
  "mode": "dry-run|live",
  "scanned": <int>,
  "reported": [{"pattern": "...", "issue_url": "https://github.com/.../issues/N"}],
  "skipped_by_user": [{"pattern": "...", "reason": "..."}],
  "failed": [{"pattern": "...", "error": "..."}]
}
```

## Sanitization rules

The redactor handles the most common privacy risks. Review the preview carefully — automated sanitization is best-effort, not guaranteed.

The rules apply in 4 layers, plus a token-aware string pass:

| Layer | Pattern | Replacement |
|---|---|---|
| 1 | `https://<account>.blob.core.windows.net/<container>/` | `<REDACTED_URL>/<REDACTED_CONTAINER>/` |
| 1 | `https://<account>.dfs.core.windows.net/...` | `<REDACTED_URL>/...` |
| 1 | Any other `https?://...` URL | `<REDACTED_URL>` |
| 1 | `Sql.Database("<server>", "<db>")` | `Sql.Database("<REDACTED_SERVER>", "<REDACTED_DB>")` |
| 1 | GUIDs (`xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`) | `<REDACTED_GUID>` |
| 1 | Quoted file paths ending in `.csv\|.xlsx\|.json\|.parquet\|.tsv\|.txt` | `<REDACTED_PATH>` |
| 1 | `Item = "<sheet>"` (Excel sheet selector) | `Item = "<REDACTED_SHEET>"` |
| 2 | **Column references** `[ColumnName]` (no `=` inside the brackets) | `[<REDACTED_COL>]` |
| 2 | **Quoted identifiers** `#"Step Or Column Name"` | `#"<REDACTED_IDENT>"` |
| 3 | **Remaining string literals** with at least one word char (e.g. column lists in `Table.RenameColumns`, `Table.SelectColumns`, filter values in `each [X] = "Y"`, conditional value branches in `each if [X] = "Z" then ...`) | `"<REDACTED_VALUE>"` |
| 4 | Numeric literals ≥ 100 (filter thresholds, IDs, large constants) | `<REDACTED_NUMBER>` |

**Preserved deliberately:**
- M function names (`Table.SelectRows`, `AzureStorage.Blobs`, `Web.Contents`, etc.) — required to identify the pattern
- Single characters and 1-2 char strings without word chars (delimiters like `","`, `"\n"`)
- Small integers (0-99) — typically structural (`Table.Skip(_, 4)`, `{0}`)
- Bracket structure — readers can see record vs. column-ref shape

Layer 3 uses a **token-aware string pass** rather than a regex, walking the M code character-by-character to pair quotes correctly. This prevents the catchall from accidentally matching the comma between two adjacent quoted args (`"<REDACTED_SERVER>"` `,` `"<REDACTED_DB>"`).

Add custom rules by editing `scripts/report_patterns.py`'s `SANITIZE_RULES` list (for regex-based) or `_redact_remaining_strings` (for token-aware).

### What's left after sanitization

A typical sanitized snippet looks like:

```m
let
  Source = AzureStorage.Blobs("<REDACTED_URL>/"),
  Navigation = Source{[<REDACTED_COL>]}[<REDACTED_COL>],
  #"<REDACTED_IDENT>" = Table.SelectRows(Navigation, each [<REDACTED_COL>] = "<REDACTED_VALUE>"),
  #"<REDACTED_IDENT>" = Table.AddColumn(_, "<REDACTED_VALUE>", each if [<REDACTED_COL>] = "<REDACTED_VALUE>" then 1 else 2)
in
  #"<REDACTED_IDENT>"
```

The reader of the GitHub issue can see: AzureStorage.Blobs is used, then a record-field navigation, then a SelectRows filter, then an AddColumn with conditional logic. **They cannot see column names, filter values, or business literals.**

## What goes in each GitHub issue

```markdown
## Pattern: <name>

**Detected occurrences:** N across M files
**First seen:** <date>

### Sanitized M snippet

```m
<sanitized snippet>
```

### Suggested mitigation (if known)

<text from m-conversion-risk-catalog.md, or "unknown" if not yet documented>

### Plugin context

- Plugin: fabric-dataflow-migration-toolkit v<version>
- Reporter is opting in to share this anonymized pattern; no actual customer data included.

---
*Auto-filed via the `report-unknown-patterns` skill. See `_Documentation/conversion-backlog.md` in the plugin source.*
```

## Failure handling

The script never raises uncaught exceptions. Each pattern is processed independently:
- Sanitization failure → user prompted to manually edit the snippet, or skip
- `gh` CLI failure → error captured, pattern's status remains `Backlog`, processing continues
- Network failure on issue creation → captured in `failed[]` list, exit code 1
