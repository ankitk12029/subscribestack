"""
agent.py

The "ask the warehouse" agent. Takes a natural-language business question,
generates SQL grounded in the dbt semantic layer (see semantic_context.py),
runs it against the DuckDB warehouse, and -- this is the point of the whole
exercise -- independently verifies the numeric answer against a
hand-written reference query where one exists, rather than just trusting
whatever the LLM produced.

Usage:
    OPENAI_API_KEY=sk-... python3 agent/agent.py "How many trials did we start in March 2024?"

Without an OPENAI_API_KEY set, the agent runs in OFFLINE DEMO MODE using a
small canned SQL library, so the verification harness (the actually novel
part of this project) can be demonstrated without needing API access. This
is announced loudly in the output -- it is never silently substituted.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import duckdb

from reference_checks import verify
from semantic_context import build_system_prompt

DB_PATH = str(Path(__file__).resolve().parents[1] / "target" / "warehouse.duckdb")

# ---------------------------------------------------------------------------
# Offline demo library: canned (question_substring -> SQL) pairs used only
# when no OPENAI_API_KEY is present. Includes one DELIBERATELY WRONG query
# (querying the raw table instead of the documented fct_trials filter) to
# demonstrate the verifier actually catching a bad answer, not just
# rubber-stamping good ones.
# ---------------------------------------------------------------------------
OFFLINE_DEMO_LIBRARY = [
    (
        "correct trial count",
        r"how many trials.*start.*march 2024",
        """
        select count(*) from main.fct_trials
        where is_countable_trial
          and extract(year from trial_start_date) = 2024
          and extract(month from trial_start_date) = 3
        """,
    ),
    (
        "naive (WRONG) trial count -- for demo purposes",
        r"naive.*trials.*march 2024",
        """
        select count(*) from main.raw_subscription_events
        where event_type = 'trial_start'
          and extract(year from event_date) = 2024
          and extract(month from event_date) = 3
        """,
    ),
    (
        "conversion rate",
        r"conversion rate.*march 2024",
        """
        select
            round(100.0 * sum(case when converted then 1 else 0 end)
                  / nullif(sum(case when is_countable_trial then 1 else 0 end), 0), 2)
        from main.fct_trials
        where extract(year from trial_start_date) = 2024
          and extract(month from trial_start_date) = 3
        """,
    ),
    (
        "realized revenue",
        r"realized revenue.*march 2024",
        """
        select round(sum(realized_revenue), 2) from main.fct_revenue_daily
        where extract(year from date) = 2024 and extract(month from date) = 3
        """,
    ),
]


def generate_sql_offline(question: str) -> tuple[str, str]:
    q = question.lower()
    for label, pattern, sql in OFFLINE_DEMO_LIBRARY:
        if re.search(pattern, q):
            return sql.strip(), label
    return (
        "-- CANNOT_ANSWER: no offline-demo SQL matches this question. "
        "Set OPENAI_API_KEY to generate SQL for arbitrary questions.",
        "no_match",
    )


def generate_sql_openai(question: str) -> tuple[str, str]:
    from openai import OpenAI

    client = OpenAI()
    system_prompt = build_system_prompt()
    resp = client.chat.completions.create(
        model=os.environ.get("AGENT_MODEL", "gpt-4o-mini"),
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question},
        ],
        temperature=0,
    )
    sql = resp.choices[0].message.content.strip()
    sql = re.sub(r"^```(sql)?|```$", "", sql, flags=re.MULTILINE).strip()
    return sql, "llm_generated"


def run_sql(sql: str):
    con = duckdb.connect(DB_PATH, read_only=True)
    try:
        df = con.execute(sql).fetchdf()
    finally:
        con.close()
    return df


def extract_scalar(df) -> float | None:
    if df.shape == (1, 1):
        val = df.iloc[0, 0]
        try:
            return float(val)
        except (TypeError, ValueError):
            return None
    return None


def ask(question: str) -> dict:
    offline = "OPENAI_API_KEY" not in os.environ or not os.environ["OPENAI_API_KEY"]

    if offline:
        sql, source = generate_sql_offline(question)
    else:
        try:
            sql, source = generate_sql_openai(question)
        except Exception as e:  # noqa: BLE001 - surface any API error plainly
            return {
                "question": question,
                "error": f"OpenAI call failed ({e}); falling back to offline demo mode.",
                **_ask_offline(question),
            }

    if sql.strip().startswith("-- CANNOT_ANSWER"):
        return {"question": question, "sql": sql, "answer": None, "verification": None, "mode": source}

    try:
        df = run_sql(sql)
    except Exception as e:  # noqa: BLE001
        return {
            "question": question,
            "sql": sql,
            "error": f"SQL execution failed: {e}",
            "mode": source,
        }

    scalar = extract_scalar(df)
    verification = verify(question, scalar)

    return {
        "question": question,
        "sql": sql,
        "mode": source,
        "answer": scalar if scalar is not None else df.to_dict(orient="records"),
        "verification": verification,
    }


def _ask_offline(question: str) -> dict:
    sql, source = generate_sql_offline(question)
    df = run_sql(sql)
    scalar = extract_scalar(df)
    verification = verify(question, scalar)
    return {"sql": sql, "mode": source, "answer": scalar, "verification": verification}


def print_result(result: dict):
    print("=" * 78)
    print(f"Q: {result['question']}")
    print(f"[mode: {result.get('mode', 'unknown')}]")
    print("-" * 78)
    print("SQL generated:")
    print(result.get("sql", "(none)"))
    print("-" * 78)
    if result.get("error"):
        print(f"ERROR: {result['error']}")
    print(f"Answer: {result.get('answer')}")
    v = result.get("verification")
    if v is None:
        print("Verification: n/a (no SQL executed)")
    elif v["verified"] is None:
        print(f"Verification: UNVERIFIED -- {v['note']}")
    elif v["verified"]:
        print(
            f"Verification: PASSED (reference={v['reference_value']}, "
            f"diff={v['pct_diff']}%) -- {v['note']}"
        )
    else:
        print(
            f"Verification: *** FLAGGED *** (agent={v.get('agent_value')}, "
            f"reference={v.get('reference_value')}, diff={v.get('pct_diff', 'n/a')}%)"
        )
        print(f"  -> {v['note']}")
    print("=" * 78)
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ask the SubscribeStack warehouse a question.")
    parser.add_argument("question", nargs="*", help="Natural-language question.")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run the built-in demo set (including a deliberately wrong query) "
        "showing the verifier catching a bad answer.",
    )
    args = parser.parse_args()

    if args.demo or not args.question:
        demo_questions = [
            "How many trials did we start in March 2024?",
            "What's our naive count of trials in March 2024?",
            "What's the conversion rate in March 2024?",
            "What's our realized revenue in March 2024?",
        ]
        for q in demo_questions:
            print_result(ask(q))
    else:
        print_result(ask(" ".join(args.question)))
