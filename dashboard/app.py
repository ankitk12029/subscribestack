"""
Streamlit dashboard reading directly from the dbt marts (never staging or
raw tables) -- the kind of "self-serve asset people trust without asking
you first" the job description asks for. Business users get tracked vs.
realized revenue and conversion metrics without needing to know any of the
gotchas baked into the underlying models; that knowledge already lives in
dbt, not in this file.
"""

import os
import subprocess
import sys
from pathlib import Path

import duckdb
import pandas as pd
import plotly.express as px
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = REPO_ROOT / "target" / "warehouse.duckdb"

st.set_page_config(page_title="SubscribeStack", layout="wide")


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
