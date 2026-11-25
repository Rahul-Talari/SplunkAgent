"""Take README screenshots of a running app with headless Chrome.

    uv run streamlit run streamlitSplunk.py --server.headless=true --server.port=8766 &
    uv run python scripts/take_screenshots.py http://localhost:8766

Saves PNGs to docs/screenshots/. Uses the installed Google Chrome (no browser download).
The screenshots show whatever chats and eval runs are in the app's database.
"""

import sys
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

OUT = Path(__file__).parents[1] / "docs" / "screenshots"


def wait_until_idle(page: Page) -> None:
    """Wait for Streamlit to finish running the script and for fonts to load."""
    page.wait_for_selector("h1", timeout=60_000)  # every page starts with st.title
    page.wait_for_function("document.fonts.ready.then(() => true)")
    page.wait_for_selector('[data-testid="stStatusWidget"]', state="detached", timeout=60_000)
    page.wait_for_timeout(1500)


def open_page(browser, url: str, scheme: str) -> Page:
    # The app follows the OS light/dark setting by default, so emulate it.
    page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1.5, color_scheme=scheme)
    page.goto(url)
    wait_until_idle(page)
    return page


def main(base_url: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")

        # 1. Welcome screen with suggestion chips (light)
        page = open_page(browser, base_url, "light")
        page.screenshot(path=OUT / "assistant-welcome-light.png")

        # 2. A conversation with the tool-call timeline expanded (dark)
        page = open_page(browser, base_url, "dark")
        page.locator('[class*="st-key-chat_"] button').first.click()  # most recent chat (buttons keyed chat_<id>)
        wait_until_idle(page)
        page.get_by_text("Worked for").first.click()
        page.wait_for_timeout(800)
        page.screenshot(path=OUT / "assistant-chat-dark.png")

        # 3. Evaluations page (dark and light)
        for scheme in ("dark", "light"):
            page = open_page(browser, f"{base_url}/evaluations", scheme)
            page.screenshot(path=OUT / f"evaluations-{scheme}.png")

        browser.close()
    print(f"Saved to {OUT}:", *sorted(f.name for f in OUT.glob("*.png")), sep="\n  ")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8501")
