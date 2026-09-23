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

import duckdb
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MARTS_SCHEMA = PROJECT_ROOT / "models" / "marts" / "schema.yml"
DB_PATH = PROJECT_ROOT / "target" / "warehouse.duckdb"

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


def load_data_date_range() -> str:
    """Query the live warehouse for the actual min/max dates covered.

    Without this, the LLM has no way to know what period the data spans
    and will guess -- observed in practice guessing a date range that has
    nothing to do with the actual synthetic data, then confidently telling
    the user the data "only goes up to" a made-up cutoff. Querying the
    warehouse directly means this never drifts out of sync as more
    synthetic data is generated.
    """
    if not DB_PATH.exists():
        return "unknown -- warehouse not yet built"
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        min_date, max_date = con.execute(
            "select min(date), max(date) from main.fct_revenue_daily"
        ).fetchone()
    finally:
        con.close()
    if min_date is None:
        return "unknown -- no rows in fct_revenue_daily"
    return f"{min_date} to {max_date}"


SYSTEM_PROMPT_TEMPLATE = """You are a SQL analyst agent for a subscription business, running \
against a local DuckDB warehouse (dialect: DuckDB SQL, mostly Postgres-compatible).

The data in this warehouse covers: {data_date_range}. If a question asks about a date \
outside this range, do not guess or assume a different cutoff -- answer using the actual \
range above, e.g. "-- CANNOT_ANSWER: no data exists after <max_date>."

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
    return SYSTEM_PROMPT_TEMPLATE.format(
        semantic_context=load_semantic_context(),
        data_date_range=load_data_date_range(),
    )


if __name__ == "__main__":
    print(build_system_prompt())
