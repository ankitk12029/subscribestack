"""
semantic_context.py

Builds the grounding context the agent sends to the LLM, PULLED DIRECTLY
from the dbt project's schema.yml descriptions -- not duplicated by hand.
This is the "curating the semantic context" and "pushing definitions back
into dbt" loop from the job description: if someone fixes a definition in
dbt, the agent's grounding updates automatically the next time it runs,
with no separate prompt file to remember to edit.
"""

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MARTS_SCHEMA = PROJECT_ROOT / "models" / "marts" / "schema.yml"

# Only these models are considered "safe to query" -- the agent is
# instructed to never query stg_ or raw_ tables directly, because those
# are exactly where the gotchas (same-day cancels, un-netted refunds)
# live unfiltered.
ALLOWED_MODELS = {"fct_trials", "fct_revenue_daily", "fct_conversion_funnel"}


def load_semantic_context() -> str:
    with open(MARTS_SCHEMA) as f:
        schema = yaml.safe_load(f)

    blocks = []
    for model in schema.get("models", []):
        name = model["name"]
        if name not in ALLOWED_MODELS:
            continue
        lines = [f"TABLE: main.{name}", f"  {model.get('description', '').strip()}"]
        for col in model.get("columns", []):
            col_desc = col.get("description", "").strip()
            if col_desc:
                lines.append(f"  - {col['name']}: {col_desc}")
        blocks.append("\n".join(lines))

    return "\n\n".join(blocks)


SYSTEM_PROMPT_TEMPLATE = """You are a SQL analyst agent for a subscription business, running \
against a local DuckDB warehouse (dialect: DuckDB SQL, mostly Postgres-compatible).

You may ONLY query these tables, using ONLY the columns and definitions given below. \
These definitions encode business logic that is NOT visible from the column names alone \
(e.g. which rows to exclude, how refunds should be attributed). Do not query stg_ or raw_ \
tables directly -- they contain unfiltered data that will produce a wrong answer if you \
count or sum them naively.

{semantic_context}

Rules:
1. Output ONLY a single SQL query, no prose, no markdown fences.
2. Use only the tables/columns documented above.
3. If a question cannot be answered from these tables, output exactly:
   -- CANNOT_ANSWER: <one sentence reason>
"""


def build_system_prompt() -> str:
    return SYSTEM_PROMPT_TEMPLATE.format(semantic_context=load_semantic_context())


if __name__ == "__main__":
    print(build_system_prompt())
