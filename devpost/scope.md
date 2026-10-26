---
doc: scope
status: draft
---

# DataLens AI

Ask your spreadsheet a question and get an answer you can check.

## The Unique Kernel
**Every answer shows its receipts.** The AI never produces a number itself. It translates the question into a validated analytical operation from a fixed, safe set. Pandas or DuckDB computes the result. The answer then shows exactly how it was computed, the rows behind it, and a clear warning when the data makes the conclusion shaky (missing values, too few rows, excluded records).
The learner's own words: "answers backed by actual calculations," "never fabricate numerical results or execute arbitrary AI-generated code," "transparent analysis steps, supporting evidence, and clear warnings when conclusions are uncertain."

## Who It's For
**To confirm with the learner.** So far the vision describes "users" in general. We still need a specific person and what they do today instead.

## The Core Loop
The user uploads a CSV or Excel file and immediately sees a short health check (types, missing values, duplicates). They ask a question in plain English. They get an answer card containing the computed result, an auto-chosen chart, the operation that produced it, the evidence rows, and any caveats. Then they ask the next question.
They come back because they can trust the answer without redoing it in a spreadsheet.

## Inspiration & Identity
"A professional analytics application with a premium dashboard," not "a basic CSV uploader with an AI chatbot." It should feel polished, responsive, and calm, with meaningful loading and error states. `3-prd` will refine the visual direction.

## Why This Matters to the Learner
A strong Build With AI: Basics submission that is "genuinely useful," works end to end, and has no fake buttons, mock-only features, or placeholder analytics presented as real.

## What "Working" Looks Like
*(Proposed by Claude. Confirm or change.)*
1. Open the app, then upload the bundled sample dataset or your own file.
2. The health panel flags real issues, for example a column with missing values.
3. Ask, for example, "Which region's revenue dropped the most from Q2 to Q3?" A correct, computed answer appears with a chart.
4. **The "oh, that's cool" beat:** expand "How this was computed" to see the exact operation (filter → group → compare), the supporting rows, and a warning such as "14 rows with missing revenue were excluded."
5. Ask something the data can't answer, for example about a column that doesn't exist. DataLens says so plainly instead of making something up.

All of this has to be demonstrable on screen in a 1–3 minute video.

## The POC Boundary
*(Proposed by Claude. Confirm or change.)*
- Upload a single CSV or a single Excel sheet, with type, size, and row limits, clear validation errors, and a data preview.
- An automatic health check: column types, missing values, duplicates, and basic summary statistics.
- Natural-language questions turned into a JSON operation from a small allowlist: filter, group-by aggregate, sort/top-N, change over time, and correlation between two columns. Every operation is checked against the real column names and types before it runs.
- Execution in DuckDB or Pandas only. The explanation is written strictly from the computed result.
- Each answer card includes the result, an auto chart, a "How this was computed" panel, evidence rows, and uncertainty warnings.
- A refusal path for questions the data can't support.
- A realistic bundled sample dataset for the demo.
- Tests for the validator and executor.

## Later
- Anomaly detection with per-record explanations
- A correlation heatmap and a broader automated exploratory analysis view
- Downloadable PDF or HTML analysis reports
- Interactive filter and sort on result tables, and CSV export of results
- Multi-sheet workbooks, joins across files, and very large files with streaming or chunking
- Saved sessions and history

## Explicitly Cut
- **Executing AI-generated code.** This is unsafe, and it contradicts the kernel. The allowlisted operations replace it.
- **Accounts, login, multi-user workspaces.** None of this is needed to prove the kernel, and it costs hours.
- **Any placeholder or mock analytics shown as real.** This is the learner's own rule: if a feature isn't real, it isn't on screen.
