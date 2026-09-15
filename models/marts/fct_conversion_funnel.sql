-- Trial -> paid conversion funnel by signup month and acquisition channel.
-- Uses fct_trials' is_countable_trial flag, so this automatically excludes
-- same-day-cancel noise without every consumer having to remember to filter.
with trials as (
    select * from {{ ref('fct_trials') }}
    where is_countable_trial
),

users as (
    select * from {{ ref('stg_users') }}
)

select
    date_trunc('month', t.trial_start_date) as trial_start_month,
    u.acquisition_channel,
    u.country,
    count(*)                                 as countable_trials,
    sum(case when t.converted then 1 else 0 end) as conversions,
    round(
        100.0 * sum(case when t.converted then 1 else 0 end) / nullif(count(*), 0),
        2
    )                                          as conversion_rate_pct,
    round(avg(t.days_to_convert), 1)          as avg_days_to_convert
from trials t
join users u on t.user_id = u.user_id
group by 1, 2, 3
