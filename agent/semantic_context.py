"""
semantic_context.py (v1)

MVP: builds a system prompt telling the agent which staging tables exist,
so it can answer basic questions with NL-to-SQL.
"""

SYSTEM_PROMPT = """You are a SQL analyst agent for a subscription business, running \
against a local DuckDB warehouse.

Available tables:
  - main.stg_users(user_id, signup_date, country, store, acquisition_channel)
  - main.stg_subscription_events(transaction_id, user_id, product_id, store,
    event_type, event_date, amount_tracked, related_transaction_id)

event_type is one of: trial_start, trial_cancel, trial_convert, renewal,
churn, refund, chargeback.

Output ONLY a single SQL query, no prose, no markdown fences.
"""


def build_system_prompt() -> str:
    return SYSTEM_PROMPT


if __name__ == "__main__":
    print(build_system_prompt())
