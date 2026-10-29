# DataLens AI

**Ask your spreadsheet a question. Check every answer.**

DataLens AI is an analytics workspace for CSV and Excel files. You ask questions in plain English, and an AI model turns each one into a single **allowlisted, validated analytical operation**. Pandas computes the result, and every answer shows:

- the computed result,
- a chart and a table,
- the exact calculation steps,
- the source rows behind it, and
- warnings whenever the data is thin, incomplete, or duplicated.

The AI never writes code, and it never supplies a number. When the data can't answer a question, DataLens says so plainly instead of guessing.

Built for the Devpost **Build With AI: Basics** hackathon.

---

## Features

| Area | What it does |
| --- | --- |
| **Upload** | Accepts CSV, TSV, and Excel (`.xlsx`/`.xlsm`). Validates the extension and the file content, detects the encoding and delimiter, and enforces size, row, and column limits. Blank or duplicate headers are cleaned up. Number, date, and true/false columns are detected automatically, including currency strings like `$1,200` and European formats like `1.234,50` and `15/01/2025`. Any interpretation choice, such as a decimal comma or ambiguous dates like 03/04, is shown on the dashboard. |
| **Data health** | A quality score, plus missing values per column, exact duplicate rows, constant columns, unusual values (the same robust rule Insights uses, so every screen reports the same records), and negative values in amount-like columns. For each column you get statistics, top values, and a distribution chart. |
| **Live dashboard** | The Overview opens with shared filters (date range, plus the dataset's main category columns), KPI tiles, and trend and breakdown charts. Every tile is a real allowlisted operation run on the server, labelled with its operation, row count, and timing. Changing a filter recomputes every tile. |
| **Accuracy benchmark** | The **Benchmark** screen runs 34 questions through the normal pipeline and compares the results with expected answers stored in `backend/benchmarks/suite_v1.json`. Those answers were computed independently with plain pandas by `scripts/compute_benchmark_expectations.py`; the edge-case set was also verified by hand. Results are tracked separately: calculation correctness (deterministic), chart consistency (deterministic), AI interpretation (needs an API key; otherwise reported as skipped, never scored), and explanation quality (not scored, because it's subjective). You can rerun any case or the whole suite, and each dataset is version-checked by SHA-256. The suite also runs in `pytest` as a regression guard. |
| **Data Detective** | Click **Investigate** on any finding to open a guided, four-step investigation. **1 · Verify:** rerun the calculation live and confirm it matches. **2 · Compare:** see the segment versus its baseline, including which categories are over- or under-represented and which numbers differ (standardized). **3 · Explore:** the exact records behind the finding, with one-click drill-down chips and a record inspector. **4 · Follow up:** related questions built from the finding and your real columns, which run without AI. |
| **What-If simulator** | Hypothetical recalculations: adjust columns by a percentage or exclude records, then compare the observed and scenario values, with a breakdown by group. A change only affects other measures through a relationship **detected in the data** (for example `revenue = units × unit_price × (1 − discount)` holding for 99.8% of rows). Anything else is refused rather than assumed. Every result shows the calculation, its assumptions, and a *Hypothetical scenario* label. |
| **Light / Dark / System themes** | Both themes are fully designed: surfaces, charts, tooltips, tables, dialogs, and native controls. The choice persists across reloads, applies before first paint (no flash), follows the OS in System mode, and the toggle is keyboard-operable. |
| **Record explorer** | The Data table and every investigation share a server-side explorer with filter chips, search, a column picker, sorting, paging, and a record inspector showing each number's percentile and whether it's statistically unusual. |
| **Insights (automatic)** | As soon as a dataset loads, DataLens runs up to 8 kinds of checks and shows the most useful findings (at most 8). The checks cover changes over time by group, trends, unusual periods, differences between groups, unusual values, relationships, missing-data patterns, and data-quality issues. Each card shows the finding, its supporting statistics, an evidence level, a chart or table, the method and steps, caveats, and the underlying records. You can turn any card into a full analysis with one click. |
| **Ask** | Natural-language questions are interpreted by the AI as one of 6 safe operation types. Each operation is validated against the real columns, types, and values. If the first attempt is invalid, the model gets one corrective retry. |
| **Suggested questions** | Questions are generated from the dataset's actual schema, including an automatically found biggest quarter-over-quarter drop and an "honesty check" question the data can't answer. Suggestions run **without** AI. |
| **Analysis builder** | Build any operation by hand: compare groups, trend over time, change between periods, relationship, distribution, top rows, and up to 6 filters. Works with no API key. |
| **Explainability** | Every answer card includes a numbered "How this was computed" trail, the exact operation JSON, the evidence rows taken straight from your data, and warnings. Warnings cover missing values that were excluded, small groups, incomplete periods, correlation is not causation, confidence intervals that cross zero, and duplicates. |
| **Data table** | Server-side pagination, sorting, and text search across all rows. |
| **Export** | Download any result as CSV (protected against spreadsheet formula injection), or download a full Markdown report containing the profile and every analysis from the session. |
| **Sample data** | `sample-data/retail_sales_2025.csv` contains 4,217 synthetic retail orders with real stories to find: a West-region slump in Q3, slower shipping linked to lower ratings, refunds, bulk orders, missing values, and duplicate rows. |

## Architecture

```
React + TypeScript (Vite, Tailwind, Recharts)
        │  /api (JSON)
        ▼
FastAPI ──► ingest.py      parse + validate + type inference
        ├─► profiling.py   data health (Pandas)
        ├─► llm.py         question ─► JSON operation (schema only, no rows)
        ├─► operations.py  Pydantic allowlist + schema validation
        ├─► executor.py    Pandas computation, steps, evidence, warnings
        ├─► insights.py    automatic insight discovery (reuses executor)
        ├─► investigation.py  focus filters, follow-ups, segment comparison, record queries
        ├─► scenarios.py   what-if: formula detection, validated hypothetical recalculation
        ├─► stats.py       Kruskal–Wallis, Mann–Kendall, chi-square, t (no SciPy)
        └─► report.py      Markdown report from computed results
```

**Why this design is safe**

1. **No code execution.** The model can only return one of 7 JSON shapes: `aggregate`, `top_rows`, `trend`, `period_change`, `correlation`, `distribution`, or `unanswerable`. Unknown types and unknown keys are rejected by Pydantic (`extra="forbid"`).
2. **Schema validation.** Columns must exist and their types must fit the operation (for example, `sum` needs a number column). Filter values must exist in the data, so a typo produces an error instead of a silent zero. Limits are enforced throughout.
3. **Numbers come only from Pandas.** The answer sentence, steps, and warnings are generated deterministically from the computation.
4. **Minimal data sent to the AI.** The model receives only column names, column types, value ranges, and up to 15 common values per category column. No raw rows are sent.
5. **Upload safeguards.** Uploads have size, row, and column caps. Excel files are content-sniffed and read as values only, so no formulas or macros run. Uploads are held in memory and never written to disk. Filenames are sanitized.
6. **Secrets.** API keys are read from environment variables only. They are never logged or returned by the API.

## Automatic insights: how they work

Discovery runs once per dataset, in the background after upload, and is cached. Everything is computed with Pandas and NumPy. The statistical functions live in `backend/app/stats.py` and are verified against SciPy reference values in the tests. **No language model is involved in finding, ranking or measuring anything.**

| Finding | Method | Reported when |
| --- | --- | --- |
| Change over time by group | Consecutive complete quarters (or months) per group, compared with the median change of the other groups. Supported by a chi-square test on the group's share of rows. | Change ≥ 20%, ≥ 25 points from the others' median, and adjusted p < 0.01. A sharp move followed by an opposite move is reported as one dip or spike. |
| Trend | Mann–Kendall test on complete periods, with Sen's slope for size. Incomplete first and last periods are excluded. | Adjusted p < 0.05 and a total change ≥ 10% of the typical level. |
| Unusual period | Each period compared with the median of its neighbours, scaled by the MAD. | Robust z ≥ 3.5 and a gap ≥ 15%. |
| Group difference | Kruskal–Wallis rank test (robust to skew and outliers), with ε² effect size. | Adjusted p < 0.01 and ε² ≥ 0.01. Near-deterministic links (ε² > 0.9, such as price set by product) are skipped. |
| Unusual values | Modified z-score from the median absolute deviation (Iglewicz–Hoaglin), on a log scale for right-skewed amounts and counts. This is the same detector used by Data health and the Distribution analysis. | \|z\| ≥ 3.5 and at most 2% of values. More than that means a real cluster or long tail, which is noted rather than flagged. |
| Relationship | Pearson r, confirmed by Spearman ρ. Pairs of amount columns are skipped because they're often arithmetically linked. | \|r\| ≥ 0.3, both measures agree, and adjusted p < 0.001. |
| Missing-data pattern | Chi-square test of missing versus present against each category and month, with Cramér's V. | Adjusted p < 0.01 and V ≥ 0.1. If no link is found and at least 5% of the column is missing, a note says the gaps look random. |
| Data quality | Negative values in amount-like columns, and exact duplicate rows with their effect on totals. | Whenever present. The top data-quality finding always gets a slot, because it changes how other numbers should be read. |

A few rules apply across all of these:

- Every p-value is **Bonferroni-adjusted** for the number of comparisons that detector tried.
- Findings are ranked by evidence and effect size, and capped per kind, so you see a varied, short list.
- The "What was checked" panel shows how many tests ran and why some checks didn't apply.

**Unusual is not wrong.** Anomaly cards are labelled "Statistically unusual, not a confirmed error". Data-quality cards are labelled "Possible data issue, not confirmed". No finding calls a value fraudulent or incorrect.

**Evidence levels:**

- *Strong evidence*: adjusted p < 0.001 plus a meaningful effect size.
- *Moderate evidence*: passed the adjusted test.
- *Worth a look*: a stated statistical rule rather than a significance test.
- *Data quality*.

**Optional AI wording.** With an API key configured, each card offers **Explain in plain words**. The model receives only the finding, its statistics, method, and caveats, never raw rows. Its reply is checked automatically: any number that doesn't match a computed statistic causes a retry, and if the second reply also fails, the explanation is discarded. Accepted explanations appear in a separate, clearly labelled box.

**Performance.** About 1.5 s for the 4,217-row sample, about 5 s at 250,000 rows, and about 8 s at 500,000 rows (the default upload limit), measured on the development machine. Above 100,000 rows, significance tests use a fixed random sample of 100,000 rows, which the app states on screen. Totals, charts and anomaly detection always use every row.

## Quick start

**Requirements:** Python 3.10 or newer (tested on 3.10, 3.12 and 3.14) and Node.js 18 or later (tested on 22).

### 1. Backend (terminal 1)

macOS / Linux:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env          # optional: add an API key
uvicorn app.main:app --reload --port 8000
```

Windows (PowerShell):

```powershell
cd backend
py -m venv .venv
.venv\Scripts\Activate.ps1   # if blocked: Set-ExecutionPolicy -Scope Process Bypass
pip install -r requirements-dev.txt
copy .env.example .env        # optional: add an API key
uvicorn app.main:app --reload --port 8000
```

### 2. Frontend (terminal 2)

```bash
cd frontend
npm install
npm run dev
```

Frontend tests (theme persistence and the no-flash startup script) run with `npm test`.

Open **http://localhost:5173** and click **Try the sample retail sales data**.

### Single-server mode (good for demos)

```bash
cd frontend && npm install && npm run build
cd ../backend && uvicorn app.main:app --port 8000
```

Open **http://localhost:8000**. FastAPI serves the built UI and the API from one process.

## Deploying (free)

DataLens deploys as **one container**: FastAPI serves both the API and the built web app.

**Render (recommended, free tier):**

1. Push this repository to GitHub.
2. In Render, choose **New → Blueprint**, then pick the repo. `render.yaml` configures everything.
3. When prompted, paste your **GEMINI_API_KEY**. It's stored as a secret in Render, never in the repo.
4. Open the URL Render gives you. The health check is `/api/status`.

**Any Docker host** (Railway, Fly.io, a VM, Hugging Face Spaces):

```bash
docker build -t datalens-ai .
docker run -p 8000:8000 -e GEMINI_API_KEY=your-key datalens-ai
```

Things to know about a public deployment:

- **No sign-in, by design.** Nothing is stored long-term: uploads live only in server memory and are never written to disk. Free hosts sleep when idle, which clears loaded datasets; users simply load or upload again.
- **Your key is protected.** AI requests are limited per visitor (`AI_RATE_PER_MINUTE`, default 8) and per day across everyone (`AI_DAILY_LIMIT`, default 300). When a limit is hit, users get a clear message, and every non-AI feature keeps working.
- **Offline demo.** `demo/index.html` is a single-file replay of the real app on the sample data (no server needed). Enable GitHub Pages on the `demo/` folder to give judges a link that always works.

## Enabling AI questions

Without a key, everything works except typed questions and AI explanations, and the UI explains this. To enable them, create a free Gemini key at https://aistudio.google.com/apikey, put it in `backend/.env`, and restart the backend:

```
GEMINI_API_KEY=...        # recommended: free tier
LLM_MODEL=auto            # picks the newest Flash model your key can use
# OPENAI_API_KEY=... or ANTHROPIC_API_KEY=... also work
```

Google retires Gemini models regularly, and new keys can't use older ones (they get HTTP 404). With `LLM_MODEL=auto`, DataLens lists the models your key can use and picks the newest stable Flash model. If a model returns 404 later, it switches to the next best one automatically. The sidebar shows the model in use.

The provider is auto-detected from whichever key is set. You can force one with `LLM_PROVIDER`, choose a model with `LLM_MODEL`, and route requests through a compatible gateway with `LLM_BASE_URL`. If the provider reports a model error, set `LLM_MODEL` to a model your account can use. The sidebar shows the active provider and model.

## Tests

```bash
cd backend
pytest
```

There are 143 backend tests (`pytest`, including the full accuracy benchmark as a regression guard) and 11 frontend tests (`npm test`). They cover:

- **Validation:** unknown operation types and extra keys are rejected, unknown columns are reported with alternatives, type mismatches are caught, filter values are checked against the data, period formats are validated, and limits are enforced.
- **Execution:** grouped sums and trends are checked against plain Pandas, along with exclusion of missing values, period change, honest errors for missing periods and for filters that match no rows, the correlation value and its caveats, top rows, distributions, and evidence rows coming from the matching group. The sample-data demo answer is also recomputed independently with Pandas.
- **Ingest:** currency, date, and US/European number detection; ambiguous and day-first dates; delimiter detection; duplicate headers; Excel round-trip and sheet selection; rejection of fake `.xlsx` files; unsupported types; empty files; row limits; malformed CSV; and filename sanitizing.
- **API:** the full upload → profile → suggestions → run flow, the upload size limit, the no-AI path, and AI interpretation through a mocked provider (including the check that raw rows are never sent). Also covered: the corrective retry, rejection of code injection, a rejected API key, malformed provider responses, the `LLM_BASE_URL` override, and report download with non-ASCII filenames.
- **Insights:**
  - The statistical functions match SciPy reference values.
  - Planted effects are found: a group difference with the right top group, an upward trend, a group's quarterly drop with exact before/after totals and its recovery, the planted outliers with their real values and reasons, concentrated missing values, and a correlation.
  - Pure noise produces no group difference and no trend.
  - An incomplete last month is excluded, and arithmetic pairs are skipped.
  - Edge cases are covered: small datasets, constant and mostly-identical columns, text-only data, and all-missing columns.
  - Evidence rows match each finding.
  - The AI number guard is checked, along with the endpoints, caching, the no-AI path, and the report section.
- **Analytical correctness:**
  - The shared outlier detector has a false-positive rate of 0.5% or less on clean normal data, finds planted outliers on both tails, and requires at least 20 values.
  - Constant and mostly identical columns are skipped, and missing values don't change the result.
  - Data health, the Distribution analysis, and Insights report the same records.
  - A fake drop inside an incomplete quarter isn't reported, and small samples never get significance labels.
  - A monthly spike is detected and labelled "unusual", not "error".
  - AI explanations can't change any insight or any computed line of the report, and an explanation that tries to inject numbers is rejected.
- **No hidden SciPy dependency:** a test blocks SciPy imports and runs every correlation path.
- **What-If:**
  - Formula detection finds only real relationships.
  - A +5% price change gives exactly revenue × 1.05, and refunds stay negative.
  - A +10% cost change reduces profit by exactly 10% of costs.
  - Discounts are capped at 100%.
  - Exclusion scenarios match pandas per group.
  - Unrelated or invalid scenarios are rejected, percentage limits are enforced, and scenarios never modify the data.
- **Data Detective:**
  - Each investigation's focus selects exactly the finding's rows, and the segment-versus-rest counts and sums match pandas.
  - Every follow-up is allowlisted and runs.
  - The anomaly investigation isolates the planted records.
  - Record inspection reports correct percentiles and counts duplicates correctly even when values are missing.
- **Theme (frontend):**
  - Persistence works, and storage failures are handled.
  - System mode resolves from the OS preference.
  - The actual inline startup script in `index.html` is executed for every saved/OS combination and must agree with `src/theme.ts`.

Frontend checks:

```bash
cd frontend
npm run typecheck
npm run build
```

The project was also checked in a real browser (headless Chromium) before release:

- the full demo journey, with displayed numbers cross-checked against independent pandas calculations;
- investigations, What-If results, and theme behaviour (including no flash with the app bundle blocked);
- axe-core WCAG 2 A/AA checks with no violations on any screen, in both themes, at desktop and mobile widths.

These browser scripts aren't part of the repository.

## A two-minute demo script

**Before you present:**

- Run single-server mode (`npm run build`, then `uvicorn app.main:app --port 8000`) and open http://localhost:8000.
- Load the sample once beforehand so every screen is warm.
- Pick the theme you'll present in; Dark looks good on projectors.
- To show typed questions, check that the sidebar says **AI: <provider>**. Everything else works without a key.

**The demo:**

1. **Upload → Discover.** Click **Try the sample retail sales data**. The live dashboard appears: change the region or date range and every KPI and chart recomputes. **Top findings** appear without asking anything.
2. **Investigate.** Click *West: total revenue fell 38%*.
   - **Recompute from the data** confirms the numbers live.
   - Step 2 shows what's different about West in Q3: discounts were about double (+0.84 standardized).
   - In step 3, click the drill-down chip **Online**, then open a record.
3. **Follow up.** Click *Within West, which channel changed most from 2025-Q2 to 2025-Q3?* The answer arrives with its calculation receipt, no AI needed.
4. **Unusual ≠ wrong.** Back on Insights, open **4 unusual units values**: each bulk order shows why it was flagged, labelled "not a confirmed error".
5. **Ask.** Type "What is the average profit by region?" DataLens refuses, because there's no profit column. Without a key, click that suggested question instead.
6. **Simulate.** In **What-if**, click **Prices +5% → revenue**. The detected formula is shown and revenue rises exactly 5%, labelled hypothetical. Try adjusting `shipping_days` instead: it's refused, because no relationship exists.
7. Open **Benchmark**: 32/32 calculation cases pass against independently computed answers, and you can rerun any case. Then toggle **Light / Dark** and click **Download report**.

## Project structure

```
backend/
  app/            FastAPI app, ingest, profiling, operations, executor, llm, report
  tests/          pytest suite
  requirements*.txt, .env.example, pytest.ini
frontend/
  src/            React app (components/, api.ts, types.ts, format.ts)
sample-data/      retail_sales_2025.csv
scripts/          generate_sample_data.py (reproducible, fixed seed)
devpost/          planning docs for the Devpost Learn workflow
```

## Limits and known trade-offs

- Datasets live in memory: the 10 most recent are kept, and a restart clears them. Re-upload after restarting the backend.
- Only the first non-empty sheet of a workbook is read by default. The API accepts a `sheet` form field to choose a different one.
- Old `.xls` files aren't supported. Save them as `.xlsx` or CSV first.
- Unusual values are flagged with a statistical rule (robust modified z-score ≥ 3.5). They are not proven errors, and the app says so wherever they appear.
- The quality score is deliberately simple and is shown next to its formula.
- Insights look at one date column (the most complete one) and up to six category columns, so very wide datasets aren't exhaustively searched.
- Rule-based flags ("Worth a look") are prompts to investigate, not statistical proof.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| "Can't reach the DataLens server" | Start the backend on port 8000. The Vite dev server proxies `/api` to it. |
| "This dataset is no longer loaded" | The backend restarted. Upload the file again. |
| "The AI provider rejected the API key" | Check the key in `backend/.env`, then restart the backend. |
| AI provider error mentioning HTTP 400 or 404 | Set `LLM_MODEL` to a model your account has access to. |
| Excel file rejected | Make sure it's `.xlsx` and not password-protected. |
| `pip install` fails building pandas or pydantic | Upgrade pip (`python -m pip install -U pip`) and reinstall; the requirements use version ranges that have prebuilt wheels for Python 3.10–3.14. |
| Wrong sheet loaded from a workbook | Use the **Sheet** picker next to the file name. |
