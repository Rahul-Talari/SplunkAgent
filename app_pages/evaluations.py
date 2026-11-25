"""Evaluations page: user feedback and the offline test suite."""

import streamlit as st

from evals.run_evals import load_cases, run_evals
from ui_common import get_settings, get_store, show_tool_steps

settings = get_settings()
store = get_store(settings.database_url)

st.title("Evaluations", icon=":material/analytics:")
st.caption("User feedback from the chat, and an offline test suite scored by rules and an LLM judge.")

# ---------------------------------------------------------------- summary cards
counts = store.feedback_counts()
rated = counts["thumbs_up"] + counts["thumbs_down"]
runs = store.list_eval_runs()
latest = runs[0].summary if runs else {}

with st.container(horizontal=True):
    st.metric("Answers given", counts["answers"], border=True, height="stretch")
    st.metric("Satisfaction", f"{counts['thumbs_up'] / rated:.0%}" if rated else "–", border=True, height="stretch",
              help=f"{counts['thumbs_up']} thumbs up, {counts['thumbs_down']} thumbs down")
    st.metric("Latest pass rate", f"{latest['pass_rate']:.0%}" if latest else "–", border=True, height="stretch")
    st.metric("Latest judge score", f"{latest['judge_avg']} / 5" if latest.get("judge_avg") else "–",
              border=True, height="stretch")

# ---------------------------------------------------------------- run the suite
st.subheader("Run the test suite", icon=":material/play_circle:")
cases = load_cases()
with st.form("run_evals"):
    selected = st.multiselect("Cases", [c["id"] for c in cases], placeholder="All cases")
    with st.container(horizontal=True, vertical_alignment="bottom"):
        use_judge = st.toggle("LLM judge", value=True, help=f"Judge model: {settings.judge_model_name}")
        use_web = st.toggle("Web search", value=settings.web_search_enabled)
    start = st.form_submit_button("Run evaluation", icon=":material/play_arrow:", type="primary")

if start:
    if not settings.groq_api_key:
        st.error("Evals run on Groq only. Add a Groq API key under Settings.", title="No API key",
                 icon=":material/error:")
        st.stop()
    to_run = [c for c in cases if not selected or c["id"] in selected]
    progress = st.progress(0.0)
    run = run_evals(settings, store, to_run, use_judge, use_web,
                    on_progress=lambda i, n, case_id: progress.progress(i / n, text=f"Running {case_id}"))
    progress.empty()
    st.toast(f"Run #{run.id} finished: {run.summary['pass_rate']:.0%} passed", icon=":material/check_circle:")
    runs = store.list_eval_runs()

if not runs:
    st.caption("No runs yet.")
    st.stop()

# ---------------------------------------------------------------- history
st.subheader("History", icon=":material/history:")
st.dataframe(
    [{"Run": r.id, "Date": r.created_at, "Model": r.model, "Web": r.web_search,
      "Cases": r.summary.get("cases"), "Pass rate": r.summary.get("pass_rate"),
      "Rules pass": r.summary.get("rules_pass_rate"), "Judge": r.summary.get("judge_avg"),
      "Errors": r.summary.get("errors", 0), "Avg time (s)": r.summary.get("avg_latency_s")} for r in runs],
    hide_index=True,
    alt="Past evaluation runs with pass rates and judge scores",
    column_config={
        "Date": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm"),
        "Pass rate": st.column_config.ProgressColumn(min_value=0, max_value=1, format="percent"),
        "Rules pass": st.column_config.ProgressColumn(min_value=0, max_value=1, format="percent"),
        "Judge": st.column_config.NumberColumn(format="%.1f / 5"),
    },
)

run_id = st.selectbox("Inspect run", [r.id for r in runs], format_func=lambda i: f"Run #{i}")
for result in store.get_eval_results(run_id):
    scores = result.scores
    icon = ":material/check_circle:" if result.passed else ":material/cancel:"
    with st.expander(result.case_id, icon=icon):
        badges = [":green-badge[rules pass]" if scores["rules_passed"] else ":red-badge[rules fail]"]
        if "judge" in scores:
            badges.append(f":blue-badge[judge {scores['judge']['score']:.0f}/5]")
        badges.append(f":gray-badge[{result.latency_ms / 1000:.1f}s]")
        st.markdown(" ".join(badges))
        if scores.get("judge", {}).get("reason"):
            st.caption(scores["judge"]["reason"])
        for key in ("error", "missing_patterns", "forbidden_patterns", "lint_errors"):
            if scores.get(key):
                st.caption(f":red[{key.replace('_', ' ').capitalize()}: {scores[key]}]")
        show_tool_steps(result.tool_calls, result.latency_ms / 1000)
        st.markdown(result.answer)
