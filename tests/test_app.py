"""Smoke test: both pages of the Streamlit app render without errors."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

ENTRYPOINT = str(Path(__file__).parents[1] / "streamlitSplunk.py")


def test_pages_render(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # the default SQLite path is relative, so the test DB lands in tmp_path

    at = AppTest.from_file(ENTRYPOINT, default_timeout=30).run()
    assert not at.exception
    assert at.title[0].value == "SIEM assistant"

    at.switch_page("app_pages/evaluations.py").run()
    assert not at.exception
    assert at.title[0].value == "Evaluations"
