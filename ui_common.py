"""Shared UI helpers for the app pages: cached resources, agent setup, tool-call rendering."""

import streamlit as st

from splunk_agent.agent import SplunkAgent, list_groq_models, make_llm, make_ollama_llm, ollama_is_running
from splunk_agent.config import Settings
from splunk_agent.db import Store


@st.cache_resource
def get_store(url: str) -> Store:
    return Store(url)


@st.cache_data(ttl=3600)  # refresh the model list once an hour
def get_models(api_key: str) -> list[str]:
    return list_groq_models(api_key)


@st.cache_data(ttl=30)  # don't ping Ollama on every rerun
def ollama_ready(base_url: str) -> bool:
    return ollama_is_running(Settings(ollama_base_url=base_url))


def get_settings() -> Settings:
    """Settings chosen in the sidebar (set by streamlitSplunk.py on every run)."""
    return st.session_state.settings


def build_agent(settings: Settings, on_tool_call=None) -> SplunkAgent | None:
    """Groq with Ollama as fallback; Ollama alone if there is no Groq key; None if neither works."""
    local = make_ollama_llm(settings) if settings.ollama_fallback and ollama_ready(settings.ollama_base_url) else None
    if settings.groq_api_key:
        return SplunkAgent(make_llm(settings), settings, settings.web_search_enabled,
                           fallback_llm=local, on_tool_call=on_tool_call)
    if local:
        return SplunkAgent(local, settings, settings.web_search_enabled, on_tool_call=on_tool_call)
    return None


# ---------------------------------------------------------------- tool calls
def tool_label(call: dict) -> str:
    result = call["result"]
    if call["name"] == "web_search":
        return f"Searched the web: {result.get('query', '')}"
    if call["name"] == "validate_spl":
        errors = len(result.get("errors", []))
        return "Validated SPL: no errors" if result.get("valid") else f"Validated SPL: {errors} error(s)"
    return f"Called {call['name']}"


def tool_failed(call: dict) -> bool:
    result = call["result"]
    return bool(result.get("error")) or result.get("valid") is False


def tool_body(call: dict) -> None:
    result = call["result"]
    if call["name"] == "web_search":
        for r in result.get("results", []):
            st.markdown(f"- [{r['title']}]({r['url']})")
        if result.get("error"):
            st.caption(f":orange[{result['error']}]")
    elif call["name"] == "validate_spl":
        st.code(call["args"].get("query", ""), language="sql")
        for error in result.get("errors", []):
            st.caption(f":red[:material/close: {error}]")
        for warning in result.get("warnings", []):
            st.caption(f":orange[:material/warning: {warning}]")


def show_tool_steps(tool_calls: list[dict] | None, seconds: float) -> None:
    """Replay saved tool calls as a collapsed step timeline."""
    if not tool_calls:
        return
    with st.expander(f"Worked for {seconds:.0f}s · {len(tool_calls)} tool call(s)", type="compact"):
        for call in tool_calls:
            icon = ":material/error:" if tool_failed(call) else ":material/check_circle:"
            with st.expander(tool_label(call), type="step", icon=icon):
                tool_body(call)
