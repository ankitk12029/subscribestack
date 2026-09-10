"""
generate_data.py

Generates synthetic subscription-business event data for SubscribeStack.
This data intentionally encodes the exact "gotchas" a subscription-analytics
semantic layer needs to get right:

  1. Trial starts that cancel same-day (should NOT count as a "real" trial
     start in most reporting definitions, but naive `COUNT(*)` does count them).
  2. Store refunds that land days/weeks after the original transaction, and
     must be netted back against the ORIGINAL transaction's period for
     realized revenue -- not counted in the period the refund itself occurred.
  3. Tracked revenue (recognized at transaction time, before the store's
     cut/refunds/chargebacks are known) vs. realized revenue (what actually
     lands after refunds and store fees).
  4. Multiple stores (App Store, Play Store, Stripe) with different fee
     structures, which is exactly the kind of "why tracked and realized
     revenue are different" detail a domain expert has to know.

No real RevenueCat data is used or implied anywhere in this project --
everything below is synthetic and generated with a fixed random seed for
reproducibility.
"""

import random
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from faker import Faker

RANDOM_SEED = 42
random.seed(RANDOM_SEED)
np.random.seed(RANDOM_SEED)
fake = Faker()
Faker.seed(RANDOM_SEED)

OUT_DIR = Path(__file__).resolve().parents[1] / "seeds"
OUT_DIR.mkdir(parents=True, exist_ok=True)

START_DATE = date(2024, 1, 1)
END_DATE = date(2025, 12, 31)
N_USERS = 6000

STORES = ["app_store", "play_store", "stripe"]
STORE_FEE_PCT = {"app_store": 0.15, "play_store": 0.15, "stripe": 0.029}
COUNTRIES = ["US", "GB", "DE", "IN", "BR", "CA", "AU", "JP", "FR", "MX"]
PRODUCTS = [
    ("monthly_basic", 9.99, 30),
    ("monthly_pro", 19.99, 30),
    ("annual_basic", 89.99, 365),
    ("annual_pro", 179.99, 365),
]


def random_date(start: date, end: date) -> date:
    delta_days = (end - start).days
    return start + timedelta(days=random.randint(0, delta_days))


def make_users(n: int) -> pd.DataFrame:
    rows = []
    for i in range(n):
        signup = random_date(START_DATE, END_DATE - timedelta(days=14))
        rows.append(
            {
                "user_id": f"u_{i:06d}",
                "signup_date": signup,
                "country": random.choices(
                    COUNTRIES, weights=[30, 10, 8, 12, 8, 6, 6, 6, 8, 6]
                )[0],
                "store": random.choices(STORES, weights=[45, 35, 20])[0],
                "acquisition_channel": random.choice(
                    ["organic", "paid_social", "paid_search", "referral", "influencer"]
                ),
            }
        )
    return pd.DataFrame(rows)


def make_events(users: pd.DataFrame) -> pd.DataFrame:
    """
    Simulate each user's subscription lifecycle: trial -> (convert | cancel)
    -> renewals -> (churn | refund | chargeback), with realistic messiness.
    """
    events = []
    txn_counter = 0

    for _, u in users.iterrows():
        product_id, price, period_days = random.choice(PRODUCTS)
        trial_start = u["signup_date"] + timedelta(days=random.randint(0, 2))
        if trial_start > END_DATE:
            continue

        txn_counter += 1
        trial_txn_id = f"t_{txn_counter:07d}"

        # Trial start event -- always recorded, even for same-day cancels.
        events.append(
            {
                "transaction_id": trial_txn_id,
                "user_id": u["user_id"],
                "product_id": product_id,
                "store": u["store"],
                "event_type": "trial_start",
                "event_date": trial_start,
                "amount_tracked": 0.0,
                "related_transaction_id": None,
            }
        )

        # 12% of trials are cancelled the SAME day they start -- these are the
        # "instant cancels" that a naive trial-start count would over-report.
        same_day_cancel = random.random() < 0.12
        if same_day_cancel:
            events.append(
                {
                    "transaction_id": f"c_{txn_counter:07d}",
                    "user_id": u["user_id"],
                    "product_id": product_id,
                    "store": u["store"],
                    "event_type": "trial_cancel",
                    "event_date": trial_start,
                    "amount_tracked": 0.0,
                    "related_transaction_id": trial_txn_id,
                }
            )
            continue  # this user's journey ends here

        trial_length_days = 7
        decision_date = trial_start + timedelta(days=trial_length_days)
        converts = random.random() < 0.38  # realistic trial->paid conversion

        if not converts:
            events.append(
                {
                    "transaction_id": f"c_{txn_counter:07d}",
                    "user_id": u["user_id"],
                    "product_id": product_id,
                    "store": u["store"],
                    "event_type": "trial_cancel",
                    "event_date": decision_date,
                    "amount_tracked": 0.0,
                    "related_transaction_id": trial_txn_id,
                }
            )
            continue

        # Converted: first paid charge, then a run of renewals until churn.
        current_date = decision_date
        cycle = 0
        while current_date <= END_DATE:
            txn_counter += 1
            charge_txn_id = f"p_{txn_counter:07d}"
            event_type = "trial_convert" if cycle == 0 else "renewal"
            events.append(
                {
                    "transaction_id": charge_txn_id,
                    "user_id": u["user_id"],
                    "product_id": product_id,
                    "store": u["store"],
                    "event_type": event_type,
                    "event_date": current_date,
                    "amount_tracked": price,
                    "related_transaction_id": trial_txn_id if cycle == 0 else None,
                }
            )

            # Refunds: ~4% of paid charges get refunded, landing 3-21 days
            # later. This is the classic "how do store refunds land in our
            # data" gotcha -- the refund event's DATE is later, but it must
            # net against the ORIGINAL charge's period for realized revenue.
            if random.random() < 0.04:
                refund_lag = random.randint(3, 21)
                refund_date = current_date + timedelta(days=refund_lag)
                if refund_date <= END_DATE:
                    events.append(
                        {
                            "transaction_id": f"r_{txn_counter:07d}",
                            "user_id": u["user_id"],
                            "product_id": product_id,
                            "store": u["store"],
                            "event_type": "refund",
                            "event_date": refund_date,
                            "amount_tracked": -price,
                            "related_transaction_id": charge_txn_id,
                        }
                    )
                    # Refunded users churn immediately.
                    break

            # Chargebacks: rarer (~0.6%), also lag, also net against original.
            if random.random() < 0.006:
                cb_lag = random.randint(10, 45)
                cb_date = current_date + timedelta(days=cb_lag)
                if cb_date <= END_DATE:
                    events.append(
                        {
                            "transaction_id": f"cb_{txn_counter:07d}",
                            "user_id": u["user_id"],
                            "product_id": product_id,
                            "store": u["store"],
                            "event_type": "chargeback",
                            "event_date": cb_date,
                            "amount_tracked": -price,
                            "related_transaction_id": charge_txn_id,
                        }
                    )
                    break

            # Churn probability rises slightly each cycle (subscription fatigue).
            churn_prob = 0.06 + 0.01 * min(cycle, 6)
            if random.random() < churn_prob:
                events.append(
                    {
                        "transaction_id": f"ch_{txn_counter:07d}",
                        "user_id": u["user_id"],
                        "product_id": product_id,
                        "store": u["store"],
                        "event_type": "churn",
                        "event_date": current_date + timedelta(days=period_days - 1),
                        "amount_tracked": 0.0,
                        "related_transaction_id": charge_txn_id,
                    }
                )
                break

            current_date = current_date + timedelta(days=period_days)
            cycle += 1

    return pd.DataFrame(events)


def main():
    users = make_users(N_USERS)
    events = make_events(users)

    users_path = OUT_DIR / "raw_users.csv"
    events_path = OUT_DIR / "raw_subscription_events.csv"
    users.to_csv(users_path, index=False)
    events.to_csv(events_path, index=False)

    print(f"Wrote {len(users):,} users -> {users_path}")
    print(f"Wrote {len(events):,} events -> {events_path}")
    print(events["event_type"].value_counts())


if __name__ == "__main__":
    main()
