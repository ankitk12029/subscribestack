"""
agent.py (v1 - MVP)

Takes a natural-language question, asks an LLM to translate it to SQL
against the staging tables, runs it, and prints the result. No
verification yet -- that's the obvious next problem once you actually
start using this thing (see the next commit).

Usage:
    OPENAI_API_KEY=sk-... python3 agent/agent.py "How many trials did we start in March 2024?"
"""

import argparse
import os
import re

import duckdb

from semantic_context import build_system_prompt

DB_PATH = "/tmp/subscribestack/warehouse.duckdb"


def generate_sql_openai(question: str) -> str:
    from openai import OpenAI

    client = OpenAI()
    resp = client.chat.completions.create(
        model=os.environ.get("AGENT_MODEL", "gpt-4o-mini"),
        messages=[
            {"role": "system", "content": build_system_prompt()},
            {"role": "user", "content": question},
        ],
        temperature=0,
    )
    sql = resp.choices[0].message.content.strip()
    return re.sub(r"^```(sql)?|```$", "", sql, flags=re.MULTILINE).strip()


def run_sql(sql: str):
    con = duckdb.connect(DB_PATH, read_only=True)
    try:
        return con.execute(sql).fetchdf()
    finally:
        con.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("question", nargs="+")
    args = parser.parse_args()
    question = " ".join(args.question)

    sql = generate_sql_openai(question)
    print("SQL:", sql)
    print(run_sql(sql))
