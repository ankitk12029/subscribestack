-- Daily revenue rollup, split explicitly into tracked vs. realized so
-- nobody has to guess which number a dashboard is showing.
select
    charge_date                        as date,
    store,
    product_id,
    count(*)                            as charge_count,
    sum(tracked_revenue)                as tracked_revenue,
    sum(realized_revenue)               as realized_revenue,
    sum(case when reversal_type is not null then 1 else 0 end) as reversed_charge_count
from {{ ref('int_revenue') }}
group by 1, 2, 3
