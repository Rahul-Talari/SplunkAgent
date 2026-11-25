"""Logmon SIEM Developer Assistant -- app entry point.

Run:    uv run streamlit run streamlitSplunk.py
Pages:  app_pages/assistant.py, app_pages/evaluations.py
Theme:  .streamlit/config.toml (light and dark; switch in the ⋮ menu → Settings)
"""

import streamlit as st

from splunk_agent.config import Settings
from ui_common import get_models, ollama_ready

st.set_page_config(page_title="Logmon SIEM Assistant", page_icon=":material/shield:", layout="wide")
st.session_state.setdefault("chat_id", None)

page = st.navigation(
    [
        st.Page("app_pages/assistant.py", title="Assistant", icon=":material/forum:", default=True,
                help="Chat to write, fix and explain Splunk SPL. Answers are checked by an SPL validator."),
        st.Page("app_pages/evaluations.py", title="Evaluations", icon=":material/analytics:",
                help="User feedback and the offline test suite: run it and compare results across runs."),
    ],
    position="top",
)

# ---------------------------------------------------------------- sidebar: settings + status
settings = Settings()
with st.sidebar.expander("Settings", icon=":material/tune:"):
    settings.groq_api_key = st.text_input("Groq API key", value=settings.groq_api_key, type="password")
    models = get_models(settings.groq_api_key) or [settings.model_name]
    settings.model_name = st.selectbox(
        "Model", models, index=models.index(settings.model_name) if settings.model_name in models else 0,
        help="Live list from Groq, so retired models never show up.")
    settings.temperature = st.slider("Temperature", 0.0, 1.0, settings.temperature, 0.1)
    settings.web_search_enabled = st.toggle("Web search", value=settings.web_search_enabled)
    settings.ollama_fallback = st.toggle(f"Local fallback ({settings.ollama_model})", value=settings.ollama_fallback,
                                         help="Use local Ollama when Groq fails or no Groq key is set.")

groq_status = f":green[●] Groq · `{settings.model_name}`" if settings.groq_api_key else ":red[●] Groq · no API key"
if not settings.ollama_fallback:
    local_status = ":gray[●] Local fallback off"
elif ollama_ready(settings.ollama_base_url):
    local_status = f":green[●] Local · `{settings.ollama_model}`"
else:
    local_status = ":orange[●] Local · run `ollama serve`"
st.sidebar.caption(f"{groq_status}  \n{local_status}")

st.session_state.settings = settings  # pages read it via ui_common.get_settings()
page.run()
