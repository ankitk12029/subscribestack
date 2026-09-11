select
    charge_date     as date,
    store,
    product_id,
    count(*)         as charge_count,
    sum(tracked_revenue) as tracked_revenue
from {{ ref('int_revenue') }}
group by 1, 2, 3
