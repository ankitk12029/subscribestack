{{
    config(materialized='view')
}}

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
    c.conversion_transaction_id is not null as converted,
    c.conversion_date,
    datediff('day', t.trial_start_date, c.conversion_date) as days_to_convert
from trial_starts t
left join conversions c on t.trial_transaction_id = c.trial_transaction_id
