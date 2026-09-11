{#
    store_fee_pct: centralizes each store's take-rate so it's defined ONCE,
    not copy-pasted into every model that touches revenue. If Apple/Google
    change their cut, or we add a new store, this is the only place to edit.
#}
{% macro store_fee_pct(store_column) %}
    case {{ store_column }}
        when 'app_store'  then 0.15
        when 'play_store' then 0.15
        when 'stripe'     then 0.029
        else 0.15
    end
{% endmacro %}
