"""
Streamlit dashboard reading directly from the dbt marts (never staging or
raw tables) -- the kind of "self-serve asset people trust without asking
you first" the job description asks for. Business users get tracked vs.
realized revenue and conversion metrics without needing to know any of the
gotchas baked into the underlying models; that knowledge already lives in
dbt, not in this file.
"""

import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
import plotly.express as px
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = REPO_ROOT / "target" / "warehouse.duckdb"
sys.path.insert(0, str(REPO_ROOT / "agent"))

st.set_page_config(page_title="SubscribeStack", layout="wide")

# ---------------------------------------------------------------------------
# Public "Ask AI" toggle. Off by default -- must be explicitly turned on via
# Streamlit Secrets (Settings -> Secrets in Streamlit Community Cloud), which
# takes effect within seconds and needs no redeploy. This is the switch to
# flip to pause public LLM access without touching code.
#
#   LLM_PUBLIC_ENABLED = true
#   OPENAI_API_KEY = "sk-..."
#   LLM_DAILY_LIMIT = 50        # optional, defaults below
#   LLM_SESSION_LIMIT = 5       # optional, defaults below
# ---------------------------------------------------------------------------
def _get_secret(key: str, default=None):
    """st.secrets raises StreamlitSecretNotFoundError if no secrets.toml
    exists at all (not just if the key is missing) -- e.g. on a fresh local
    checkout with no secrets configured yet. Treat "no secrets file" the
    same as "key not set" so the app runs fine locally with LLM features off.
    """
    try:
        return st.secrets.get(key, default)
    except st.errors.StreamlitSecretNotFoundError:
        return default


LLM_PUBLIC_ENABLED = str(_get_secret("LLM_PUBLIC_ENABLED", "false")).lower() == "true"
LLM_DAILY_LIMIT = int(_get_secret("LLM_DAILY_LIMIT", 50))
LLM_SESSION_LIMIT = int(_get_secret("LLM_SESSION_LIMIT", 5))
USAGE_LOG_PATH = REPO_ROOT / "target" / "llm_usage.json"

_openai_key = _get_secret("OPENAI_API_KEY")
if LLM_PUBLIC_ENABLED and _openai_key:
    os.environ["OPENAI_API_KEY"] = _openai_key


def _load_usage() -> dict:
    today = str(date.today())
    if USAGE_LOG_PATH.exists():
        try:
            data = json.loads(USAGE_LOG_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            data = {}
    else:
        data = {}
    if data.get("date") != today:
        data = {"date": today, "count": 0}
    return data


def _record_usage() -> int:
    data = _load_usage()
    data["count"] += 1
    USAGE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    USAGE_LOG_PATH.write_text(json.dumps(data))
    return data["count"]


def build_warehouse():
    """Generate synthetic data and run dbt if the warehouse doesn't exist yet.

    Lets a fresh checkout (e.g. Streamlit Community Cloud, which has no
    pre-built .duckdb file and no ~/.dbt/profiles.yml) become servable with
    no manual setup step and nothing but synthetic data baked into git.
    """
    env = {**os.environ, "DBT_PROFILES_DIR": str(REPO_ROOT)}
    with st.spinner("First run: generating synthetic data and building the warehouse..."):
        subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "generate_data.py")],
            cwd=REPO_ROOT,
            check=True,
        )
        subprocess.run(
            ["dbt", "seed"],
            cwd=REPO_ROOT,
            env=env,
            check=True,
        )
        subprocess.run(
            ["dbt", "build"],
            cwd=REPO_ROOT,
            env=env,
            check=True,
        )


@st.cache_data(ttl=300)
def load_data():
    if not DB_PATH.exists():
        build_warehouse()
    con = duckdb.connect(str(DB_PATH), read_only=True)
    revenue = con.execute("select * from main.fct_revenue_daily").fetchdf()
    funnel = con.execute("select * from main.fct_conversion_funnel").fetchdf()
    trials = con.execute("select * from main.fct_trials").fetchdf()
    con.close()
    return revenue, funnel, trials


revenue, funnel, trials = load_data()

st.title("SubscribeStack")
st.caption(
    "A subscription-analytics semantic layer + dashboards, built on synthetic data. "
    "Every number here reads from dbt marts that already encode the business-logic "
    "gotchas (same-day-cancel trials, refund timing, tracked vs. realized revenue) "
    "so nobody downstream has to remember them."
)

col1, col2, col3, col4 = st.columns(4)
col1.metric("Tracked revenue", f"${revenue['tracked_revenue'].sum():,.0f}")
col2.metric("Realized revenue", f"${revenue['realized_revenue'].sum():,.0f}")
col3.metric("Countable trials", f"{trials['is_countable_trial'].sum():,}")
col4.metric(
    "Overall conversion rate",
    f"{100 * trials['converted'].sum() / max(trials['is_countable_trial'].sum(), 1):.1f}%",
)

st.divider()

left, right = st.columns(2)

with left:
    st.subheader("Tracked vs. realized revenue over time")
    monthly = revenue.copy()
    monthly["month"] = pd.to_datetime(monthly["date"]).dt.to_period("M").dt.to_timestamp()
    monthly = monthly.groupby("month")[["tracked_revenue", "realized_revenue"]].sum().reset_index()
    monthly_melted = monthly.melt(id_vars="month", var_name="metric", value_name="amount")
    fig = px.line(monthly_melted, x="month", y="amount", color="metric", markers=True)
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        "The gap between the two lines is refunds, chargebacks, and store fees. "
        "That gap is expected, not a data-quality bug."
    )

with right:
    st.subheader("Trial -> paid conversion rate by channel")
    funnel_agg = (
        funnel.groupby("acquisition_channel")
        .agg(countable_trials=("countable_trials", "sum"), conversions=("conversions", "sum"))
        .reset_index()
    )
    funnel_agg["conversion_rate_pct"] = round(
        100 * funnel_agg["conversions"] / funnel_agg["countable_trials"], 1
    )
    fig2 = px.bar(
        funnel_agg.sort_values("conversion_rate_pct", ascending=False),
        x="acquisition_channel",
        y="conversion_rate_pct",
        text="conversion_rate_pct",
    )
    st.plotly_chart(fig2, use_container_width=True)
    st.caption("Excludes same-day-cancel trials -- see fct_trials.is_countable_trial.")

st.divider()
st.subheader("Revenue by store")
by_store = revenue.groupby("store")[["tracked_revenue", "realized_revenue"]].sum().reset_index()
st.dataframe(by_store, use_container_width=True, hide_index=True)

st.divider()
st.subheader("Ask the warehouse (AI-generated SQL, independently verified)")

if not LLM_PUBLIC_ENABLED:
    st.info(
        "AI-generated answers are currently paused. The dashboard is still "
        "fully live above -- this section just isn't accepting free-form "
        "questions right now."
    )
else:
    usage = _load_usage()
    session_count = st.session_state.get("llm_session_count", 0)

    if usage["count"] >= LLM_DAILY_LIMIT:
        st.warning("Daily AI question limit reached. Please check back tomorrow.")
    elif session_count >= LLM_SESSION_LIMIT:
        st.warning(f"You've hit the per-session limit ({LLM_SESSION_LIMIT} questions). Refresh to reset.")
    else:
        st.caption(
            f"Questions today: {usage['count']}/{LLM_DAILY_LIMIT} · "
            f"Your session: {session_count}/{LLM_SESSION_LIMIT}. "
            "Every answer is cross-checked against a hand-written reference "
            "query before being shown -- see agent/reference_checks.py."
        )
        question = st.text_input("Ask a question about trials, conversion, or revenue:")
        if st.button("Ask") and question.strip():
            from agent import ask  # noqa: E402 - imported lazily, only when used

            with st.spinner("Generating and verifying SQL..."):
                result = ask(question.strip())
            st.session_state["llm_session_count"] = session_count + 1
            _record_usage()

            st.code(result.get("sql", "(none)"), language="sql")
            if result.get("error"):
                st.error(result["error"])
            st.write(f"**Answer:** {result.get('answer')}")

            v = result.get("verification")
            if v is None:
                st.caption("Verification: n/a (no SQL executed)")
            elif v.get("verified") is None:
                st.caption(f"Verification: unverified -- {v.get('note')}")
            elif v["verified"]:
                st.success(f"Verified against reference (diff={v['pct_diff']}%): {v['note']}")
            else:
                st.error(
                    f"FLAGGED -- agent={v.get('agent_value')}, "
                    f"reference={v.get('reference_value')}, diff={v.get('pct_diff', 'n/a')}%. "
                    f"{v['note']}"
                )
