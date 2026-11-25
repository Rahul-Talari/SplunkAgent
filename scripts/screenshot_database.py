"""Screenshot the database tables (structure + sample rows) for the README.

    uv run python scripts/screenshot_database.py sqlite:///data/splunk_agent.db

Renders each table as an HTML page and screenshots it with the installed Google Chrome.
Saves docs/screenshots/database-<table>.png. Long text is shortened so rows stay readable.
"""

import html
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright
from sqlalchemy import create_engine, inspect, text

OUT = Path(__file__).parents[1] / "docs" / "screenshots"
MAX_ROWS = 6
MAX_CELL = 60

STYLE = """
body { font: 14px Inter, system-ui, sans-serif; background: #0B0F17; color: #E6E9EF; margin: 0; padding: 24px; }
h2 { font-size: 18px; margin: 0 0 4px; } h2 code { color: #7AA8FF; }
p { color: #8A94A6; margin: 0 0 14px; }
table { border-collapse: collapse; margin-bottom: 18px; }
th, td { border: 1px solid #232B38; padding: 6px 10px; text-align: left; white-space: nowrap; }
th { background: #141A24; font-weight: 600; }
td { font: 12.5px 'JetBrains Mono', monospace; }
.type { color: #8A94A6; font-weight: 400; display: block; font-size: 11px; }
.null { color: #4B5566; }
"""

DESCRIPTIONS = {
    "chats": "One row per conversation in the sidebar.",
    "messages": "Every user question and assistant answer, with tool calls, model, latency, tokens and 👍/👎 rating.",
    "eval_runs": "One row per evaluation run, with its summary scores.",
    "eval_results": "One row per test case in a run: pass/fail, scores and the answer.",
}


def short(value) -> str:
    if value is None or value == "null":  # SQL NULL or an empty JSON column
        return '<span class="null">NULL</span>'
    if isinstance(value, (dict, list)) or (isinstance(value, str) and value[:1] in "[{"):
        value = json.dumps(json.loads(value) if isinstance(value, str) else value)
    value = " ".join(str(value).split())
    return html.escape(value if len(value) <= MAX_CELL else value[: MAX_CELL - 1] + "…")


def table_html(engine, name: str) -> str:
    columns = inspect(engine).get_columns(name)
    with engine.connect() as conn:
        count = conn.execute(text(f'SELECT COUNT(*) FROM "{name}"')).scalar()
        rows = conn.execute(text(f'SELECT * FROM "{name}" ORDER BY 1 LIMIT {MAX_ROWS}')).fetchall()
    head = "".join(f"<th>{c['name']}<span class='type'>{c['type']}</span></th>" for c in columns)
    body = "".join("<tr>" + "".join(f"<td>{short(v)}</td>" for v in row) + "</tr>" for row in rows)
    shown = f"showing {len(rows)} of {count} rows" if count > len(rows) else f"{count} rows"
    return (f"<h2>Table <code>{name}</code></h2><p>{DESCRIPTIONS.get(name, '')} ({shown})</p>"
            f"<table><tr>{head}</tr>{body}</table>")


def main(database_url: str) -> None:
    engine = create_engine(database_url)
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(viewport={"width": 1400, "height": 400}, device_scale_factor=1.5)
        for name in inspect(engine).get_table_names():
            page.set_content(f"<style>{STYLE}</style><div id='t' style='display:inline-block'>"
                             f"{table_html(engine, name)}</div>")
            page.locator("#t").screenshot(path=OUT / f"database-{name}.png")
            print("saved", f"database-{name}.png")
        browser.close()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "sqlite:///data/splunk_agent.db")
