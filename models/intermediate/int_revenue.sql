{{
    config(materialized='view')
}}

-- GOTCHA #2: "tracked revenue" vs "realized revenue" are different numbers,
-- and they SHOULD be different -- that's not a bug to reconcile away.
--
--   tracked_revenue  = the amount recognized at the moment of the original
--                       charge (trial_convert / renewal), before we know
--                       whether it will be refunded or charged back.
--   realized_revenue = tracked_revenue, net of any refund/chargeback that
--                       references it, MINUS the store's fee.
--
-- GOTCHA #3: refunds and chargebacks land in our data on the date THEY
-- happen, which is often days or weeks after the original charge. If you
-- naively group refund amounts by the refund's own event_date, you'll see
-- "phantom" revenue drops in periods where nothing was actually sold. This
-- model nets every refund/chargeback back against the ORIGINAL transaction's
-- date, which is what "realized revenue for the period we sold it in" means.

with charges as (
    select
        transaction_id,
        user_id,
        product_id,
        store,
        event_date  as charge_date,
        event_type  as charge_type,
        amount_tracked as tracked_revenue
    from {{ ref('stg_subscription_events') }}
    where event_type in ('trial_convert', 'renewal')
),

reversals as (
    select
        related_transaction_id as transaction_id,
        sum(amount_tracked)     as reversal_amount,   -- already negative
        max(event_type)         as reversal_type
    from {{ ref('stg_subscription_events') }}
    where event_type in ('refund', 'chargeback')
    group by 1
)

select
    c.transaction_id,
    c.user_id,
    c.product_id,
    c.store,
    c.charge_date,
    c.charge_type,
    c.tracked_revenue,
    coalesce(r.reversal_amount, 0)                         as reversal_amount,
    r.reversal_type,
    c.tracked_revenue + coalesce(r.reversal_amount, 0)      as net_before_fees,
    (c.tracked_revenue + coalesce(r.reversal_amount, 0))
        * (1 - {{ store_fee_pct('c.store') }})              as realized_revenue
from charges c
left join reversals r on c.transaction_id = r.transaction_id
