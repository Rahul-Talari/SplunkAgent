# Logmon SIEM Developer Assistant

![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)
![Streamlit 1.67+](https://img.shields.io/badge/streamlit-1.67%2B-FF4B4B?logo=streamlit&logoColor=white)
![uv](https://img.shields.io/badge/packaged%20with-uv-DE5FE9)
![Groq](https://img.shields.io/badge/LLM-Groq%20%2B%20Ollama-F55036)

An AI assistant for Splunk engineers. Paste a log sample or an SPL query, say what you need, and it
**writes, fixes or explains SPL** for SIEM detections and traceability dashboards. Every query it
writes is checked by a built-in SPL validator before you see it.

- **Generate detections** from a log sample, mapped to the mandatory baseline fields
  `Time`, `Account`, `Device`, `Source_IP`, `SAFE_name`
- **Fix broken queries**: explains each defect, then gives the corrected SPL
- **Explain queries** step by step
- **Dashboard KPIs**: one panel query per KPI, with a suggested visualization
- **Web search** of Splunk docs and community when the model is unsure (identifiers in your logs are never sent)
- **Saved chats** with 👍/👎 feedback, stored in SQLite or Postgres
- **Evaluations**: a test suite scored by rules and an LLM judge, with history to compare runs
- **Local fallback**: a model on your own machine (Ollama) answers when Groq is unavailable
- **Light and dark themes**

![Assistant answering a query fix, with its validation steps expanded](docs/screenshots/assistant-chat-dark.png)

| Start screen (light) | Evaluations (dark) |
|---|---|
| ![Assistant start screen with suggestion chips](docs/screenshots/assistant-welcome-light.png) | ![Evaluations page, dark theme](docs/screenshots/evaluations-dark.png) |

## Contents

1. [Quick start](#quick-start)
2. [Configuration](#configuration)
3. [Using the app](#using-the-app)
4. [How it works](#how-it-works)
5. [Local fallback with Ollama](#local-fallback-with-ollama)
6. [Evaluations](#evaluations)
7. [Database](#database)
8. [Project structure](#project-structure)
9. [Development](#development)
10. [Troubleshooting](#troubleshooting)
11. [Security notes](#security-notes)

## Quick start

**You need:** Python 3.11+, [uv](https://docs.astral.sh/uv/), and a free [Groq API key](https://console.groq.com/keys).

```bash
git clone <this-repo> && cd SplunkAgent
uv sync                                  # creates .venv and installs everything
```

Create a file named `.env` in the project folder (it is git-ignored, so your keys stay private):

```ini
GROQ_API_KEY=gsk_your_key_here
```

Start the app and open http://localhost:8501:

```bash
uv run streamlit run streamlitSplunk.py
```

That's all you need. Everything below is optional.

## Configuration

All settings live in `.env`. Only `GROQ_API_KEY` is required (or a running Ollama, see below).

| Setting | Default | What it does |
|---|---|---|
| `GROQ_API_KEY` | – | Your Groq key. Can also be typed in the app's **Settings** panel. |
| `MODEL_NAME` | `openai/gpt-oss-120b` | Groq model used for answers. The app lists only models Groq currently serves. |
| `JUDGE_MODEL_NAME` | `qwen/qwen3.8-27b` | Model that grades eval answers. Use a different model than `MODEL_NAME`. |
| `TEMPERATURE` | `0.2` | Lower is more consistent SPL. |
| `MAX_TOKENS` | `2048` | Maximum length of one model reply. |
| `MAX_AGENT_STEPS` | `10` | Maximum tool-call rounds per answer. |
| `WEB_SEARCH_ENABLED` | `true` | Let the model search Splunk docs and community. |
| `TAVILY_API_KEY` | – | Optional. Better, Splunk-only search results. Without it, DuckDuckGo is used. |
| `DATABASE_URL` | `sqlite:///data/splunk_agent.db` | Where chats and eval results are stored. |
| `OLLAMA_FALLBACK` | `true` | Use the local model when Groq fails. |
| `OLLAMA_MODEL` | `qwen3.5:4b` | Local model name. |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Where Ollama runs. |

### Postgres instead of SQLite

```bash
uv sync --extra postgres
```

Then in `.env`:

```ini
DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/splunk_agent
```

Tables are created automatically on first start.

> [!NOTE]
> **Groq retires models from time to time** (for example `llama-3.3-70b-versatile` was shut down in
> August 2026). The model dropdown reads Groq's live model list, so retired models disappear on their own.
> If `MODEL_NAME` in `.env` points to a retired model, change it to one from the dropdown.
> See [Groq deprecations](https://console.groq.com/docs/deprecations).

## Using the app

### Assistant page

- Type in the chat box, or click a suggestion chip on an empty chat.
- Give the model what it needs: the **log sample**, the **log type / sourcetype / index**, and the **requirement**.
  For example:
  ```text
  Log type: Linux /var/log/secure (sourcetype=linux_secure), index=os_linux
  Sample: Nov 20 08:15:11 bastion01 sshd[22871]: Failed password for invalid user admin from 203.0.113.50 port 51234 ssh2
  Requirement: SIEM query for failed SSH logins, mapped to the baseline fields.
  ```
- While it works you see a **Working** timeline. Afterwards it collapses to
  *"Worked for 9s · 4 tool call(s)"*. Open it to see each validation and web search.
- Rate answers with 👍/👎. Ratings show up on the Evaluations page.
- The sidebar lists recent chats. Click one to reopen it. Chats are saved automatically.
- The sidebar status shows whether Groq and the local fallback are ready.

### Evaluations page

See [Evaluations](#evaluations).

### Light and dark theme

Open the top-right **⋮ menu → Settings → Theme** (Light, Dark, or follow your system).
Colors are set in [.streamlit/config.toml](.streamlit/config.toml).

> [!WARNING]
> **Review before you deploy.** The validator catches syntax errors, but not every logic error
> (for example comparing an hour as text instead of a number). Test generated queries in Splunk
> before using them in production searches.

## How it works

```mermaid
flowchart LR
    U["You: logs + request"] --> A[Agent loop]
    A -->|asks| M["LLM: Groq"]
    M -.->|fails| O["Local LLM: Ollama"]
    M -->|tool call| V["validate_spl<br/>local SPL checker"]
    M -->|tool call| W["web_search<br/>Splunk docs + community"]
    V --> A
    W --> A
    A -->|final answer| UI["Streamlit app"]
    UI --> DB[("Database<br/>chats, ratings, evals")]
```

The model can call two tools, in a loop, before it answers:

| Tool | What it does |
|---|---|
| `validate_spl` | Checks SPL without a Splunk server: unbalanced quotes and brackets, empty pipes, unknown commands, generating commands like `tstats` in the wrong place, `stats … by` with no field, `eval` without `=`, slow `transaction` / `join`, missing `index=`. Can also check the baseline fields. The model must validate every query it writes and fix any errors. |
| `web_search` | Searches Splunk docs, Lantern, community and research sites for command syntax, add-on field names, CIM data models or error messages. **IPs, emails, `DOMAIN\user` names and hashes are removed from the query before it is sent.** |

The system prompt (in [splunk_agent/prompts.py](splunk_agent/prompts.py)) holds your team's conventions:
the baseline fields, using a specific `index`/`sourcetype`, preferring `stats`/`tstats` over
`transaction`/`join`, and citing sources when web search was used.

## Local fallback with Ollama

If Groq fails (rate limit, network down, or no API key), the chat switches to a model on your own
machine. The caption under each answer shows which model replied.

```bash
# Install Ollama: https://ollama.com/download
ollama pull qwen3.5:4b      # once (3.3 GB, supports tool calling)
ollama serve                # keep it running while you use the app
```

- The sidebar shows **● Local · qwen3.5:4b** in green when Ollama is reachable.
- Turn the fallback off in **Settings** or with `OLLAMA_FALLBACK=false`.
- Evaluations always use Groq, so scores are never mixed between models.

> [!NOTE]
> **Hardware:** on a laptop GPU with 4 GB of memory, the 4B model runs partly on the CPU. Expect
> 1–4 minutes per answer and lower accuracy than Groq. Treat it as a backup, not the main model.

## Evaluations

The evaluation suite measures answer quality, so you can see whether a change to the prompt, the
model or the tools made answers better or worse.

![Evaluations page, light theme](docs/screenshots/evaluations-light.png)

### Run it

From the **Evaluations** page, or from the terminal:

```bash
uv run python -m evals.run_evals                         # all cases, with the LLM judge
uv run python -m evals.run_evals --no-judge              # rule checks only (faster)
uv run python -m evals.run_evals --no-web                # without web search
uv run python -m evals.run_evals --case fix-tstats-position
```

A full run takes about 5 minutes on Groq's free tier (8,000 tokens per minute). Rate limits are retried automatically.

### What is measured

| Metric | Meaning |
|---|---|
| Pass rate | Cases that pass every rule check and (if on) get a judge score of 4/5 or more |
| Rules pass | Cases that pass the rule checks only |
| Judge | Average score from the judge model, 1–5 |
| Errors | Cases that failed for technical reasons (for example rate limits), not because of a bad answer |
| User feedback | 👍/👎 ratings from real chats |

### Test cases

Cases live in [evals/cases.jsonl](evals/cases.jsonl), one JSON object per line. There are 10 cases:
Windows brute force, Linux SSH failures, CyberArk safe access, CIM password spraying, three query fixes,
a `transaction` optimization, a dashboard and an explanation.

```json
{"id": "my-case", "category": "generate", "prompt": "Log type: ... Sample: ... Requirement: ...",
 "must_include": ["regex that must appear in the answer"],
 "must_not_include": ["regex that must NOT appear in the final query"],
 "needs_valid_spl": true,
 "reference": "the ideal answer, used by the judge"}
```

A case **passes** when:
1. every `must_include` regex is found in the answer,
2. no `must_not_include` regex is found in the final query (the last `spl` code block),
3. the final query has no validator errors (if `needs_valid_spl` is true),
4. the judge gives 4/5 or more (if the judge is on).

> [!TIP]
> Adjust the index names in the cases (`wineventlog`, `pam`, `os_linux`, …) to match your environment.

## Database

Everything the app stores, shown here with sample rows (long values shortened):

| Table | One row per |
|---|---|
| [`chats`](#chats) | conversation in the sidebar |
| [`messages`](#messages) | question or answer, with tool calls, model, latency, tokens and rating |
| [`eval_runs`](#eval_runs) | evaluation run, with summary scores |
| [`eval_results`](#eval_results) | test case in a run, with pass/fail, scores and the answer |

### chats

![chats table](docs/screenshots/database-chats.png)

### messages

![messages table](docs/screenshots/database-messages.png)

### eval_runs

![eval_runs table](docs/screenshots/database-eval_runs.png)

### eval_results

![eval_results table](docs/screenshots/database-eval_results.png)

Models and queries are in [splunk_agent/db.py](splunk_agent/db.py).

## Project structure

```text
streamlitSplunk.py            app entry point: navigation, settings sidebar, status
app_pages/
  assistant.py                chat page
  evaluations.py              evaluations page
ui_common.py                  helpers shared by the pages (cached DB, agent setup, tool timeline)
.streamlit/config.toml        light and dark theme

splunk_agent/
  config.py                   settings from .env
  prompts.py                  system prompt and judge prompt
  agent.py                    tool-calling loop, Groq + Ollama models
  db.py                       database tables and queries
  tools/spl_lint.py           SPL validator
  tools/web_search.py         Tavily / DuckDuckGo search with identifier scrubbing

evals/
  cases.jsonl                 test cases
  run_evals.py                runs and scores the cases

tests/                        unit tests and an app smoke test
scripts/                      screenshot tools for this README
docs/screenshots/             images used in this README
```

## Development

### Tests

```bash
uv run pytest                  # 17 tests: validator, agent loop, database, eval scoring, app pages
```

The tests use a fake model, so they need no API key and no network.

### Retake the README screenshots

Uses your installed Google Chrome and shows the data in your database:

```bash
uv run streamlit run streamlitSplunk.py --server.headless=true --server.port=8766 &
uv run python scripts/take_screenshots.py http://localhost:8766
uv run python scripts/screenshot_database.py sqlite:///data/splunk_agent.db
```

### Working with an AI coding agent

Run `uv run streamlit skills` once to install Streamlit's official
agent skills into `.claude/skills/`. They are local links into your `.venv`, so they are git-ignored.

## Troubleshooting

| Problem | Fix |
|---|---|
| `uv: command not found` | Install uv ([guide](https://docs.astral.sh/uv/getting-started/installation/)) and make sure its folder is on your `PATH`. Or run without uv: `source .venv/bin/activate && streamlit run streamlitSplunk.py` |
| `streamlit: command not found` | The virtual environment is not active. Use `uv run streamlit …` or `source .venv/bin/activate` first. |
| "No model available" | Add `GROQ_API_KEY` to `.env` (or in **Settings**), or start Ollama with `ollama serve`. |
| Sidebar shows **● Local · run `ollama serve`** | Ollama is not running. Start it, or turn off the local fallback in **Settings**. |
| `Error code: 429 … Rate limit reached` | Groq free-tier limit. The app retries and then uses the local fallback. For evals, wait a minute or run fewer cases. |
| `model … has been decommissioned` | Groq retired the model. Pick another in the **Model** dropdown and update `MODEL_NAME` in `.env`. |
| Theme or layout didn't change | Restart the app. The theme file is only read at startup. |
| Web search returns nothing | DuckDuckGo sometimes blocks automated searches. Add a `TAVILY_API_KEY`, or turn web search off. |

## Security notes

- Keys live only in `.env`, which is git-ignored. Never commit it.
- Log samples you paste are sent to Groq (or stay on your machine with Ollama). Don't paste data your policy doesn't allow to leave your network.
- Web search queries are written by the model and scrubbed of IPs, emails, `DOMAIN\user` names and hashes before they are sent.
- The assistant gives read-only guidance. It never runs queries or changes anything in Splunk.
