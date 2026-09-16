with source as (
    select * from {{ ref('raw_users') }}
)

select
    user_id,
    cast(signup_date as date)      as signup_date,
    country,
    store,
    acquisition_channel
from source
