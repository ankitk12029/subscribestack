with source as (
    select * from {{ ref('raw_subscription_events') }}
)

select
    transaction_id,
    user_id,
    product_id,
    store,
    event_type,
    cast(event_date as date)       as event_date,
    amount_tracked,
    related_transaction_id
from source
