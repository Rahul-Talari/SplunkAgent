"""Tests for the agent loop, the database and the eval scoring. Uses a fake LLM (no network)."""

from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable

from evals.run_evals import check_rules, run_evals
from splunk_agent.agent import SplunkAgent
from splunk_agent.config import Settings
from splunk_agent.db import Store

GOOD_ANSWER = "Fixed:\n```spl\n| tstats count where index=network sourcetype=pan:traffic by src_ip\n```"


class FakeLLM(Runnable):
    """Returns the given replies in order."""

    def __init__(self, replies):
        self.replies = list(replies)

    def bind_tools(self, tools):
        self.tool_names = [t.name for t in tools]
        return self

    def invoke(self, messages, config=None, **kwargs):
        reply = self.replies.pop(0)
        reply.usage_metadata = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
        return reply


def tool_call(name, args, call_id="c1"):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


def make_settings(**overrides):
    settings = Settings(groq_api_key="test", database_url="sqlite:///:memory:")
    for key, value in overrides.items():
        setattr(settings, key, value)
    return settings


def test_agent_calls_tool_then_answers():
    llm = FakeLLM([tool_call("validate_spl", {"query": "index=net | tstats count by src"}), AIMessage(GOOD_ANSWER)])
    result = SplunkAgent(llm, make_settings(), web_enabled=False).run("fix my query")
    assert result.answer == GOOD_ANSWER
    assert result.tool_calls[0]["name"] == "validate_spl"
    assert result.tool_calls[0]["result"]["valid"] is False
    assert result.tokens == 30
    assert llm.tool_names == ["validate_spl"]


def test_agent_stops_after_step_limit():
    llm = FakeLLM([tool_call("validate_spl", {"query": "index=a"}), tool_call("validate_spl", {"query": "index=a"}),
                   AIMessage("final")])
    result = SplunkAgent(llm, make_settings(max_agent_steps=2), web_enabled=False).run("q")
    assert result.answer == "final"


class BrokenLLM(FakeLLM):
    """Always fails, like Groq when rate-limited or offline."""

    def invoke(self, messages, config=None, **kwargs):
        raise RuntimeError("429 rate limit")


def test_fallback_llm_answers_when_main_llm_fails():
    fallback = FakeLLM([AIMessage("local answer", response_metadata={"model": "qwen3.5:4b"})])
    result = SplunkAgent(BrokenLLM([]), make_settings(), web_enabled=False, fallback_llm=fallback).run("q")
    assert result.answer == "local answer"
    assert result.model == "qwen3.5:4b"
    assert result.error is None


def test_unknown_tool_returns_error():
    llm = FakeLLM([tool_call("nope", {}), AIMessage("ok")])
    result = SplunkAgent(llm, make_settings(), web_enabled=False).run("q")
    assert "Unknown tool" in result.tool_calls[0]["result"]["error"]


def test_store_chats_messages_and_ratings():
    store = Store("sqlite:///:memory:")
    chat = store.create_chat("test")
    store.add_message(chat.id, "user", "hello")
    answer = store.add_message(chat.id, "assistant", "hi", tool_calls=[{"name": "x"}], latency_ms=5)
    store.set_rating(answer.id, -1)
    store.set_rating(answer.id, 1)

    messages = store.get_messages(chat.id)
    assert [m.role for m in messages] == ["user", "assistant"]
    assert messages[1].rating == 1
    assert store.feedback_counts() == {"answers": 1, "thumbs_up": 1, "thumbs_down": 0}

    store.delete_chat(chat.id)
    assert store.list_chats() == []
    assert store.get_messages(chat.id) == []


CASE = {"id": "fix-tstats", "prompt": "fix it", "must_include": [r"^\s*\|\s*tstats"],
        "must_not_include": [r"pan:traffic\s*\|\s*tstats"], "needs_valid_spl": True}


def test_check_rules_uses_last_query():
    # The answer quotes the broken query first; only the last (fixed) query is checked.
    answer = "Broken:\n```spl\nindex=n sourcetype=pan:traffic | tstats count\n```\n" + GOOD_ANSWER
    assert check_rules(CASE, answer)["rules_passed"]
    assert not check_rules(CASE, "```spl\nindex=n sourcetype=pan:traffic | tstats count\n```")["rules_passed"]


def test_run_evals_saves_results():
    store = Store("sqlite:///:memory:")
    agent_llm = FakeLLM([tool_call("validate_spl", {"query": "| tstats count"}), AIMessage(GOOD_ANSWER)])
    judge_llm = FakeLLM([AIMessage('{"score": 5, "reason": "correct"}')])
    run = run_evals(make_settings(), store, [CASE], web_enabled=False, llm=agent_llm, judge_llm=judge_llm)

    assert run.summary["pass_rate"] == 1.0 and run.summary["judge_avg"] == 5.0
    saved = store.get_eval_results(store.list_eval_runs()[0].id)
    assert saved[0].passed and saved[0].scores["self_validated"]
