{{
    config(materialized='view')
}}

select
    transaction_id,
    user_id,
    product_id,
    store,
    event_date       as charge_date,
    event_type       as charge_type,
    amount_tracked   as tracked_revenue
from {{ ref('stg_subscription_events') }}
where event_type in ('trial_convert', 'renewal')
