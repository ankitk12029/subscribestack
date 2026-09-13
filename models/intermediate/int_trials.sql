{{
    config(materialized='view')
}}

-- GOTCHA #1, encoded here so nobody has to remember it in their head:
--   A raw COUNT(*) of trial_start events over-reports "real" trial starts,
--   because it includes trials that were cancelled the same day they began
--   (accidental starts, immediate refund-seekers, test accounts, etc).
--   This model is the single place that draws the line between a
--   "trial_start event" and a "trial we should actually count and report on."
--   Any dashboard or agent answer about trial volume should read FROM HERE,
--   not from stg_subscription_events directly.

with trial_starts as (
    select
        transaction_id  as trial_transaction_id,
        user_id,
        product_id,
        store,
        event_date      as trial_start_date
    from {{ ref('stg_subscription_events') }}
    where event_type = 'trial_start'
),

same_day_cancels as (
    select
        related_transaction_id as trial_transaction_id,
        event_date              as cancel_date
    from {{ ref('stg_subscription_events') }}
    where event_type = 'trial_cancel'
),

conversions as (
    select
        related_transaction_id as trial_transaction_id,
        transaction_id          as conversion_transaction_id,
        event_date               as conversion_date
    from {{ ref('stg_subscription_events') }}
    where event_type = 'trial_convert'
)

select
    t.trial_transaction_id,
    t.user_id,
    t.product_id,
    t.store,
    t.trial_start_date,
    sdc.cancel_date is not null
        and sdc.cancel_date = t.trial_start_date        as is_same_day_cancel,
    -- The metric a stakeholder actually means by "trial start" 95% of the
    -- time: excludes same-day accidental/instant cancels.
    not (sdc.cancel_date is not null
         and sdc.cancel_date = t.trial_start_date)        as is_countable_trial,
    c.conversion_transaction_id is not null                as converted,
    c.conversion_date,
    datediff('day', t.trial_start_date, c.conversion_date) as days_to_convert
from trial_starts t
left join same_day_cancels sdc on t.trial_transaction_id = sdc.trial_transaction_id
left join conversions c on t.trial_transaction_id = c.trial_transaction_id
