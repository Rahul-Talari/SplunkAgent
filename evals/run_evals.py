"""Run the eval cases against the assistant, score them, and save the results to the DB.

    uv run python -m evals.run_evals              # all cases, with LLM judge
    uv run python -m evals.run_evals --no-judge   # rule checks only (faster, cheaper)
    uv run python -m evals.run_evals --case fix-tstats-position

Each case in cases.jsonl:
    id, category, prompt, reference (ideal answer for the judge),
    must_include      regexes that must appear somewhere in the answer
    must_not_include  regexes that must NOT appear in the final query
    needs_valid_spl   the final query (last ```spl block) must pass the linter

A case passes when all rule checks pass and (if the judge is on) judge score >= 4.
"""

import argparse
import json
import re
from pathlib import Path

from langchain_core.messages import HumanMessage

from splunk_agent.agent import SplunkAgent, make_llm
from splunk_agent.config import Settings
from splunk_agent.db import EvalResult, EvalRun, Store
from splunk_agent.prompts import JUDGE_PROMPT
from splunk_agent.tools import extract_spl_blocks, lint_spl

CASES_FILE = Path(__file__).parent / "cases.jsonl"
JUDGE_PASS_SCORE = 4


def load_cases() -> list[dict]:
    return [json.loads(line) for line in CASES_FILE.read_text().splitlines() if line.strip()]


def check_rules(case: dict, answer: str) -> dict:
    """Rule-based checks. The 'final query' is the last ```spl block in the answer."""
    blocks = extract_spl_blocks(answer)
    final_query = blocks[-1] if blocks else ""
    flags = re.IGNORECASE | re.MULTILINE

    missing = [p for p in case.get("must_include", []) if not re.search(p, answer, flags)]
    forbidden = [p for p in case.get("must_not_include", []) if re.search(p, final_query, flags)]
    lint_errors = lint_spl(final_query)["errors"] if case.get("needs_valid_spl", True) else []

    return {
        "missing_patterns": missing,
        "forbidden_patterns": forbidden,
        "lint_errors": lint_errors,
        "rules_passed": not missing and not forbidden and not lint_errors,
    }


def judge_answer(judge_llm, case: dict, answer: str) -> dict:
    """Ask a model to grade the answer. Returns {"score": 1-5, "reason": str}."""
    prompt = JUDGE_PROMPT.format(request=case["prompt"], reference=case.get("reference", ""), answer=answer)
    reply = judge_llm.invoke([HumanMessage(prompt)]).content
    try:
        data = json.loads(re.search(r"\{.*\}", reply, re.S).group(0))
        return {"score": float(data["score"]), "reason": data.get("reason", "")}
    except (AttributeError, KeyError, ValueError):
        return {"score": 0, "reason": f"Could not read judge output: {reply[:200]}"}


def run_evals(settings: Settings, store: Store, cases: list[dict], use_judge: bool = True,
              web_enabled: bool = True, llm=None, judge_llm=None, on_progress=None) -> EvalRun:
    agent = SplunkAgent(llm or make_llm(settings), settings, web_enabled)
    if use_judge:
        judge_llm = judge_llm or make_llm(settings, settings.judge_model_name, temperature=0)

    run = EvalRun(model=settings.model_name, web_search=web_enabled)
    for i, case in enumerate(cases):
        if on_progress:
            on_progress(i, len(cases), case["id"])

        result = agent.run(case["prompt"])
        scores = check_rules(case, result.answer)
        scores["web_searches"] = sum(1 for t in result.tool_calls if t["name"] == "web_search")
        scores["self_validated"] = any(t["name"] == "validate_spl" for t in result.tool_calls)
        scores["error"] = result.error  # e.g. rate limit; not the model's fault
        passed = scores["rules_passed"] and not result.error
        if use_judge and not result.error:
            scores["judge"] = judge_answer(judge_llm, case, result.answer)
            passed = passed and scores["judge"]["score"] >= JUDGE_PASS_SCORE

        run.results.append(EvalResult(case_id=case["id"], passed=passed, scores=scores, answer=result.answer,
                                      tool_calls=result.tool_calls, latency_ms=result.latency_ms))

    results = run.results
    judge_scores = [r.scores["judge"]["score"] for r in results if "judge" in r.scores]
    run.summary = {
        "cases": len(results),
        "errors": sum(1 for r in results if r.scores["error"]),
        "pass_rate": round(sum(r.passed for r in results) / len(results), 2),
        "rules_pass_rate": round(sum(r.scores["rules_passed"] for r in results) / len(results), 2),
        "judge_avg": round(sum(judge_scores) / len(judge_scores), 2) if judge_scores else None,
        "avg_latency_s": round(sum(r.latency_ms for r in results) / len(results) / 1000, 1),
    }
    return store.save_eval_run(run)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Splunk assistant eval suite.")
    parser.add_argument("--case", action="append", help="only run this case id (can repeat)")
    parser.add_argument("--no-judge", action="store_true", help="skip the LLM judge")
    parser.add_argument("--no-web", action="store_true", help="disable web search")
    args = parser.parse_args()

    settings = Settings()
    if not settings.groq_api_key:
        parser.error("GROQ_API_KEY is not set in .env")
    cases = load_cases()
    if args.case:
        cases = [c for c in cases if c["id"] in args.case]

    run = run_evals(settings, Store(settings.database_url), cases, use_judge=not args.no_judge,
                    web_enabled=not args.no_web, on_progress=lambda i, n, case_id: print(f"[{i + 1}/{n}] {case_id}"))

    print(f"\nEval run #{run.id} ({run.model})")
    for r in run.results:
        judge = r.scores.get("judge", {})
        print(f"{'PASS' if r.passed else 'FAIL'}  {r.case_id:30}  judge={judge.get('score', '-')}  {r.latency_ms / 1000:.1f}s")
        for key in ("error", "missing_patterns", "forbidden_patterns", "lint_errors"):
            if r.scores[key]:
                print(f"      {key}: {r.scores[key]}")
        if not r.passed and judge.get("reason"):
            print(f"      judge: {judge['reason']}")
    print("\nSummary:", json.dumps(run.summary, indent=2))


if __name__ == "__main__":
    main()
