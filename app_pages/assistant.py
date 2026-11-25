"""Chat page: generate, fix and explain SPL."""

import time

import streamlit as st
from langchain_core.messages import AIMessage, HumanMessage

from evals.run_evals import load_cases
from splunk_agent.config import BASELINE_FIELDS
from ui_common import build_agent, get_settings, get_store, show_tool_steps, tool_body, tool_failed, tool_label

# Suggestion pills on an empty chat: label -> eval case whose prompt is sent.
SUGGESTIONS = {
    ":blue[:material/shield:] Detect brute force (Windows 4625)": "gen-win-4625-bruteforce",
    ":orange[:material/build:] Fix a broken tstats query": "fix-tstats-position",
    ":green[:material/dashboard:] CyberArk dashboard KPIs": "dash-auth-kpis",
    ":violet[:material/school:] Explain a rex query": "explain-rex",
}

settings = get_settings()
store = get_store(settings.database_url)


# ---------------------------------------------------------------- sidebar: chat list
def start_new_chat() -> None:
    st.session_state.chat_id = None


st.sidebar.button("New chat", icon=":material/add:", width="stretch", on_click=start_new_chat)
chats = store.list_chats()
if chats:
    st.sidebar.caption("Recent")
# A compact, left-aligned list: one line per chat, the open chat in bold.
chat_list = st.sidebar.container(gap="xxsmall")
for chat in chats:
    active = chat.id == st.session_state.chat_id
    title = chat.title if len(chat.title) <= 26 else chat.title[:25].rstrip() + "…"
    if chat_list.button(f"**{title}**" if active else title, key=f"chat_{chat.id}", help=chat.title,
                        type="tertiary", wrap=False,
                        icon=":material/chat:" if active else ":material/chat_bubble_outline:"):
        st.session_state.chat_id = chat.id
        st.rerun()
if st.session_state.chat_id:
    if chat_list.button("Delete this chat", icon=":material/delete:", type="tertiary"):
        store.delete_chat(st.session_state.chat_id)
        st.session_state.chat_id = None
        st.rerun()


# ---------------------------------------------------------------- history
def save_rating(message_id: int, key: str) -> None:
    store.set_rating(message_id, 1 if st.session_state[key] == 1 else -1)


st.title("SIEM assistant", icon=":material/shield:")
st.caption(f"Write, fix and explain Splunk SPL. Baseline fields: {', '.join(BASELINE_FIELDS)}")

messages = store.get_messages(st.session_state.chat_id) if st.session_state.chat_id else []
for message in messages:
    with st.chat_message(message.role):
        if message.role == "assistant":
            show_tool_steps(message.tool_calls, (message.latency_ms or 0) / 1000)
        st.markdown(message.content)
        if message.role == "assistant":
            key = f"rating_{message.id}"
            if key not in st.session_state and message.rating is not None:
                st.session_state[key] = 1 if message.rating == 1 else 0
            with st.container(horizontal=True, vertical_alignment="center"):
                st.feedback("thumbs", key=key, on_change=save_rating, args=(message.id, key))
                st.caption(f"{message.model} · {(message.latency_ms or 0) / 1000:.1f}s · {message.tokens or 0:,} tokens")


# ---------------------------------------------------------------- new question
prompt = st.chat_input("Paste logs or a query, and describe what you need", key="prompt", submit_mode="disable")

if not messages:
    suggestions = st.empty()
    picked = suggestions.pills("Try one of these", list(SUGGESTIONS), key="suggestion", label_visibility="collapsed")
    if picked:
        prompt = {case["id"]: case["prompt"] for case in load_cases()}[SUGGESTIONS[picked]]
    if prompt:
        suggestions.empty()

if prompt:
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        work = st.status(":shimmer[Working]", type="compact")

        def on_tool_call(call: dict) -> None:
            # Add each tool call to the timeline as soon as it finishes.
            with work:
                with st.status(tool_label(call), type="step", state="error" if tool_failed(call) else "complete"):
                    tool_body(call)

        agent = build_agent(settings, on_tool_call)
        if agent is None:
            work.update(label="Not started", state="error")
            st.error("Add a Groq API key under Settings, or start Ollama with `ollama serve`.",
                     title="No model available", icon=":material/error:")
            st.stop()

        start = time.time()
        history = [HumanMessage(m.content) if m.role == "user" else AIMessage(m.content) for m in messages]
        result = agent.run(prompt, history)
        work.update(label=f"Worked for {time.time() - start:.0f}s", state="error" if result.error else "complete")

    chat_id = st.session_state.chat_id or store.create_chat(title=prompt.splitlines()[0][:60]).id
    st.session_state.chat_id = chat_id
    store.add_message(chat_id, "user", prompt)
    store.add_message(chat_id, "assistant", result.answer, model=result.model or settings.model_name,
                      tool_calls=result.tool_calls, latency_ms=result.latency_ms, tokens=result.tokens)
    st.rerun()  # redraw from the database so the answer gets its rating buttons
