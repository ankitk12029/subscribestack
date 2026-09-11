-- The trustworthy trial-level fact table. This is what dashboards, the AI
-- agent, and anyone asking "how many trials did we start / how many
-- converted" should query -- never stg_subscription_events directly.
select * from {{ ref('int_trials') }}
