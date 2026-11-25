"""The assistant: an LLM that can call two tools (validate_spl, web_search) in a loop.

Loop: ask the model -> if it requests tools, run them and send back the results -> repeat
until the model answers with plain text (or the step limit is reached).
"""

import json
import time
from dataclasses import dataclass, field

import httpx
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langchain_groq import ChatGroq
from langchain_ollama import ChatOllama

from splunk_agent.config import BASELINE_FIELDS, Settings
from splunk_agent.prompts import SYSTEM_PROMPT
from splunk_agent.tools import lint_spl, web_search


@dataclass
class AgentResult:
    answer: str
    tool_calls: list[dict] = field(default_factory=list)  # [{"name", "args", "result"}]
    latency_ms: int = 0
    tokens: int = 0
    model: str = ""  # the model that actually answered (shows when the fallback was used)
    error: str | None = None


def list_groq_models(api_key: str) -> list[str]:
    """Chat models Groq serves right now. Groq retires models, so ask the API instead of hard-coding."""
    try:
        response = httpx.get("https://api.groq.com/openai/v1/models",
                             headers={"Authorization": f"Bearer {api_key}"}, timeout=10)
        response.raise_for_status()
        models = response.json()["data"]
    except Exception:
        return []
    # Skip speech, audio and safety-classifier models, and models with a small context window.
    return sorted(
        m["id"] for m in models
        if m.get("active") and m.get("context_window", 0) >= 32000 and "guard" not in m["id"]
    )


def make_llm(settings: Settings, model_name: str | None = None, temperature: float | None = None) -> ChatGroq:
    return ChatGroq(
        model=model_name or settings.model_name,
        temperature=settings.temperature if temperature is None else temperature,
        max_tokens=settings.max_tokens,
        api_key=settings.groq_api_key,
        timeout=60,
        max_retries=6,  # the Groq client waits and retries on rate limits (free tier: 8k tokens/min)
    )


def make_ollama_llm(settings: Settings) -> ChatOllama:
    return ChatOllama(
        model=settings.ollama_model,
        base_url=settings.ollama_base_url,
        temperature=settings.temperature,
        num_ctx=8192,  # room for the prompt, tools and pasted logs, small enough for a 4 GB GPU
        reasoning=False,  # skip the "thinking" phase; much faster on a small GPU
    )


def ollama_is_running(settings: Settings) -> bool:
    try:
        return httpx.get(f"{settings.ollama_base_url}/api/version", timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


def make_tools(settings: Settings, web_enabled: bool) -> list[StructuredTool]:
    def validate_spl(query: str, check_baseline_fields: bool = False) -> dict:
        """Check an SPL query for syntax errors and performance problems.
        Set check_baseline_fields=true for SIEM detections to also check the mandatory fields."""
        return lint_spl(query, BASELINE_FIELDS if check_baseline_fields else None)

    def search(query: str) -> dict:
        """Search Splunk docs and community for command syntax, add-on field names,
        CIM data models or error messages. Use a short, generic query."""
        return web_search(query, settings.tavily_api_key)

    tools = [StructuredTool.from_function(validate_spl, name="validate_spl")]
    if web_enabled:
        tools.append(StructuredTool.from_function(search, name="web_search"))
    return tools


class SplunkAgent:
    def __init__(self, llm, settings: Settings, web_enabled: bool = True, fallback_llm=None, on_tool_call=None):
        """If `fallback_llm` is given, it answers whenever a call to `llm` fails.
        If `on_tool_call` is given, it is called with each tool call dict as soon as it finishes."""
        self.on_tool_call = on_tool_call
        self.max_steps = settings.max_agent_steps
        self.tools = {tool.name: tool for tool in make_tools(settings, web_enabled)}
        tools = list(self.tools.values())
        self.llm_with_tools = llm.bind_tools(tools)
        if fallback_llm is not None:
            self.llm_with_tools = self.llm_with_tools.with_fallbacks([fallback_llm.bind_tools(tools)])

    def run_tool(self, name: str, args: dict) -> dict:
        if name not in self.tools:
            return {"error": f"Unknown tool '{name}'."}
        try:
            return self.tools[name].invoke(args)
        except Exception as e:
            return {"error": str(e)}

    def run(self, question: str, history: list[BaseMessage] | None = None) -> AgentResult:
        start = time.time()
        result = AgentResult(answer="")
        messages = [SystemMessage(SYSTEM_PROMPT), *(history or [])[-20:], HumanMessage(question)]

        try:
            for _ in range(self.max_steps):
                reply = self.llm_with_tools.invoke(messages)
                result.tokens += (reply.usage_metadata or {}).get("total_tokens", 0)
                # Groq reports "model_name", Ollama reports "model".
                result.model = reply.response_metadata.get("model_name") or reply.response_metadata.get("model", "")
                messages.append(reply)

                if not reply.tool_calls:  # plain answer -> done
                    result.answer = reply.content
                    break

                for call in reply.tool_calls:
                    output = self.run_tool(call["name"], call["args"])
                    record = {"name": call["name"], "args": call["args"], "result": output}
                    result.tool_calls.append(record)
                    if self.on_tool_call:
                        self.on_tool_call(record)
                    messages.append(ToolMessage(content=json.dumps(output), tool_call_id=call["id"]))
            else:
                # Step limit reached: ask for a final answer and ignore any further tool requests.
                messages.append(HumanMessage("Stop using tools. Give your final answer now."))
                reply = self.llm_with_tools.invoke(messages)
                result.answer = reply.content or "⚠️ Ran out of steps before finishing. Try a smaller request."
        except Exception as e:
            result.error = str(e)
            result.answer = f"❌ Error: {e}"

        result.latency_ms = int((time.time() - start) * 1000)
        return result
