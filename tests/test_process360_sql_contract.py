"""Optional real PostgreSQL tests using SELECT/VALUES only; never create tables.

Set PROCESS360_ACCEPTANCE_DSN explicitly to run. Business tables are not read.
"""

import os
import pytest

from bi_agent.process360.db import DatabaseConfig, PostgresDatabase
from bi_agent.process360.queries import SC05_AGGREGATE


@pytest.fixture
def database():
    dsn = os.environ.get("PROCESS360_ACCEPTANCE_DSN")
    if not dsn:
        pytest.skip("explicit read-only acceptance DSN required")
    return PostgresDatabase(DatabaseConfig(dsn=dsn))


def facts_sql():
    # Two shipment rows share the same grain. Compare their SUM once to one plan.
    fixture = """WITH
    test_plan AS (SELECT 'order-1'::text AS "AT0001321", 10 AS "AT0001325", 'p1'::text AS "AT0001323",
      DATE '2026-10-01' AS "AT0001305", %(flag)s::text AS "AT0001316", %(planned)s::numeric AS "AT0001313",
      'month-1'::text AS "AT0001320", 0 AS "AT0001329" FROM generate_series(1, %(versions)s)),
    test_month AS (SELECT 'month-1'::text AS "AT0001377", 0 AS "AT0001361", %(align)s::text AS "AT0001357", 'line-1'::text AS "AT0001358"),
    test_line AS (SELECT 'line-1'::text AS "AT0001122", 'order-1'::text AS "AT0001230", 10 AS "AT0001237", 'p1'::text AS "AT0001225"),
    test_shipment AS (SELECT 'order-1'::text AS "AT9200177", DATE '2026-10-01' AS "AT9200169", 'ship-1'::text AS "AT9200153", 0 AS "AT9200184"),
    test_item AS (SELECT '10'::text AS "AT9200215", 'p1'::text AS "AT9200213", qty AS "AT9200206",
      amount AS "AT9200218", 999999::numeric AS "AT9200214", 'ship-1'::text AS "AT9200201", 0 AS "AT9200225"
      FROM (VALUES (5::numeric, %(amount1)s::numeric), (7::numeric, 700::numeric)) AS v(qty, amount)),
    test_product AS (SELECT 'p1'::text AS "AT9200241", %(energy)s::numeric AS "AT9200243")
    ,"""
    return (
        fixture
        + SC05_AGGREGATE.format(
            plan="test_plan",
            month="test_month",
            line="test_line",
            shipment="test_shipment",
            item="test_item",
            product="test_product",
            filters="",
        ).lstrip()[5:]
    )


def run(database, **overrides):
    params = dict(
        flag="1",
        planned=10,
        versions=1,
        align=4,
        amount1=500,
        energy=1,
        start="2026-10-01",
        end="2026-10-27",
    )
    params.update(overrides)
    return database.run(facts_sql(), params).rows[0]


def test_excess_is_computed_after_actual_shipments_are_grouped(database):
    row = run(database)
    assert row["actual_rows"] == 1
    assert row["actual_qty"] == 12
    assert row["outside_power_gwh"] == pytest.approx(2 / 1e6)
    assert row["outside_amount_100m"] == pytest.approx(200 / 1e8)


def test_explicit_no_plan_counts_whole_actual_quantity(database):
    row = run(database, flag="0")
    assert row["outside_power_gwh"] == pytest.approx(12 / 1e6)
    assert row["outside_amount_100m"] == pytest.approx(1200 / 1e8)


@pytest.mark.parametrize(
    "overrides", [dict(flag=None), dict(align=1), dict(versions=0), dict(planned=None)]
)
def test_unknown_plan_state_is_not_classified_as_outside(database, overrides):
    row = run(database, **overrides)
    assert row["unknown_rows"] == 1
    assert row["outside_power_gwh"] is None
    assert row["outside_amount_100m"] is None


def test_duplicate_plans_do_not_duplicate_actuals_or_produce_valid_metrics(database):
    row = run(database, versions=2)
    assert row["actual_qty"] == 12 and row["ambiguous_rows"] == 1
    assert row["outside_power_gwh"] is None


def test_missing_tax_free_amount_is_not_replaced_by_taxed_amount(database):
    row = run(database, amount1=None)
    assert row["missing_amount_rows"] == 1
    assert row["outside_amount_100m"] < 0.001


def test_live_adapter_is_read_only_repeatable_read(database):
    row = database.run(
        "SELECT current_setting('transaction_read_only') AS ro, current_setting('transaction_isolation') AS isolation"
    ).rows[0]
    assert row == {"ro": "on", "isolation": "repeatable read"}
