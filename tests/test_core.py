"""Tests for the calculation engine (pricefloor.core)."""

import pytest
from decimal import Decimal, ROUND_HALF_UP

from pricefloor.core import (
    Config,
    Service,
    TIER_LIBRARY,
    CalcError,
    ceil_to,
    compare_flat_vs_hourly,
    compute_floor,
    fmt_money,
    fmt_number,
    fmt_pct,
    parse_overruns,
)

D = Decimal

# Reference case: $50/hr x 3 h, $40 materials, standard tier (12%),
# $2,400/yr fixed over 200 jobs, 10% profit, 25% tax, round to $5.
def reference_config(**overrides):
    values = dict(
        tax_pct=D("25"),
        tier="standard",
        overhead_pct=None,
        annual_expenses=D("2400"),
        jobs_per_year=200,
        round_to=D("5"),
    )
    values.update(overrides)
    return Config(**values)


def reference_service(**overrides):
    values = dict(
        name="Handyman Small Repair",
        rate=D("50"),
        hours=D("3"),
        materials=D("40"),
        profit_pct=D("10"),
    )
    values.update(overrides)
    return Service(**values)


# --- formatting helpers -----------------------------------------------------

def test_fmt_money_groups_thousands():
    assert fmt_money(D("1234.5")) == "$1,234.50"
    assert fmt_money(D("0")) == "$0.00"
    assert fmt_money(D("325")) == "$325.00"


def test_fmt_money_negative():
    assert fmt_money(D("-12.5")) == "-$12.50"


def test_fmt_number_trims_zeros():
    assert fmt_number(D("3")) == "3"
    assert fmt_number(D("3.50")) == "3.5"
    assert fmt_number(D("108.33")) == "108.33"
    assert fmt_number(D("20.00")) == "20"


def test_fmt_pct_rounds_lightly():
    assert fmt_pct(D("25")) == "25"
    assert fmt_pct(D("12.50")) == "12.5"
    assert fmt_pct(D("26.66666")) == "26.7"


def test_ceil_to_rounds_up():
    assert ceil_to(D("322.67"), D("5")) == D("325.00")
    assert ceil_to(D("325.00"), D("5")) == D("325.00")
    assert ceil_to(D("1.004"), D("0.01")) == D("1.01")


def test_ceil_to_zero_step_returns_cents():
    assert ceil_to(D("322.6666"), D("0")) == D("322.67")


# --- core floor math ---------------------------------------------------------

def test_reference_floor_full_breakdown():
    result = compute_floor(reference_service(), reference_config())
    assert result.labor == D("150.00")
    assert result.overhead_tier == D("18.00")
    assert result.overhead_fixed == D("12.00")
    assert result.materials == D("40.00")
    assert result.profit == D("22.00")
    assert result.subtotal == D("242.00")
    assert result.price_raw.quantize(D("0.01")) == D("322.67")
    assert result.price == D("325.00")
    assert result.tax_set_aside == D("81.25")
    assert result.net_after_tax == D("243.75")
    assert result.effective_hourly.quantize(D("0.01"), rounding=ROUND_HALF_UP) == D("108.33")


def test_tax_gross_up_keeps_subtotal():
    # floor with no round-up: price minus the tax set-aside ~= what you needed
    config = reference_config(round_to=D("0"))
    result = compute_floor(reference_service(), config)
    gross = result.price_raw.quantize(D("0.01"))
    assert abs((gross - gross * config.tax_pct / D("100")) - result.subtotal) <= D("0.01")


def test_rounding_up_never_undercovers():
    result = compute_floor(reference_service(), reference_config())
    assert result.net_after_tax >= result.subtotal


def test_no_tax_no_rounding_floors_to_subtotal():
    config = reference_config(tax_pct=D("0"), round_to=D("0"))
    result = compute_floor(reference_service(), config)
    assert result.price == D("242.00")
    assert result.tax_set_aside == D("0")


def test_tier_changes_overhead():
    micro = compute_floor(reference_service(), reference_config(tier="micro"))
    established = compute_floor(reference_service(), reference_config(tier="established"))
    assert micro.overhead_tier == D("150.00") * TIER_LIBRARY["micro"][0]
    assert established.overhead_tier == D("150.00") * TIER_LIBRARY["established"][0]
    assert established.price > micro.price


def test_custom_overhead_overrides_tier():
    config = reference_config(tier="micro", overhead_pct=D("15"))
    result = compute_floor(reference_service(), config)
    assert result.overhead_tier == D("150.00") * D("0.15")


def test_fixed_expenses_amortize_per_job():
    config = reference_config(annual_expenses=D("1200"), jobs_per_year=100)
    result = compute_floor(reference_service(), config)
    assert result.overhead_fixed == D("12.00")


def test_zero_profit_and_materials_still_prices():
    service = reference_service(materials=D("0"), profit_pct=D("0"))
    account = compute_floor(service, reference_config())
    # labor 150 + tier 18 + fixed 12 = 180; grossed up 25% tax = 240
    assert account.subtotal == D("180.00")
    assert account.price == D("240.00")


def test_breakeven_equals_overhead_plus_profit_fraction():
    # (18 + 22) / 150 = 26.6667 percent overrun cushion for flat quoting
    result = compute_floor(reference_service(), reference_config())
    assert result.breakeven_overrun_pct == (D("18") + D("22")) / D("150") * D("100")


def test_breakeven_none_when_rate_zero():
    result = compute_floor(reference_service(rate=D("0")), reference_config())
    assert result.breakeven_overrun_pct is None


def test_explanation_steps_mention_the_story():
    result = compute_floor(reference_service(), reference_config())
    text = "\n".join(result.steps)
    assert "$150.00" in text
    assert "standard" in text
    assert "$12.00" in text  # fixed cost share
    assert "25" in text      # tax set-aside percent


# --- validation ---------------------------------------------------------------

@pytest.mark.parametrize(
    "bad_config",
    [
        dict(tax_pct=D("100")),
        dict(tax_pct=D("-5")),
        dict(annual_expenses=D("-1")),
        dict(round_to=D("-5")),
        dict(tier="deluxe"),
        dict(annual_expenses=D("2400"), jobs_per_year=0),
        dict(overhead_pct=D("-2")),
    ],
)
def test_config_validation_raises(bad_config):
    with pytest.raises(CalcError):
        compute_floor(reference_service(), reference_config(**bad_config))


@pytest.mark.parametrize(
    "bad_service",
    [
        dict(hours=D("0")),
        dict(hours=D("-1")),
        dict(rate=D("-5")),
        dict(materials=D("-1")),
        dict(profit_pct=D("-1")),
        dict(profit_pct=D("100000")),
    ],
)
def test_service_validation_raises(bad_service):
    with pytest.raises(CalcError):
        compute_floor(reference_service(**bad_service), reference_config())


# --- flat vs hourly comparison -------------------------------------------------

def test_compare_flat_price_constant_hourly_grows():
    comparison = compare_flat_vs_hourly(
        reference_service(), reference_config(), parse_overruns("0,25,50")
    )
    prices = {s.flat_price for s in comparison.scenarios}
    assert prices == {D("325.00")}
    hourly = [s.hourly_price for s in comparison.scenarios]
    assert hourly == sorted(hourly)
    assert len(comparison.scenarios) == 3


def test_compare_hourly_protects_long_jobs():
    comparison = compare_flat_vs_hourly(
        reference_service(), reference_config(), parse_overruns("-20,0,50,100")
    )
    flat_late = comparison.scenarios[-1]
    hourly_late = comparison.scenarios[-1]
    assert flat_late.flat_net_hourly < reference_service().rate
    assert hourly_late.hourly_net_hourly > flat_late.flat_net_hourly


def test_compare_on_schedule_flat_equals_hourly():
    comparison = compare_flat_vs_hourly(
        reference_service(), reference_config(), parse_overruns("0")
    )
    only = comparison.scenarios[0]
    assert only.flat_price == only.hourly_price


def test_compare_breakeven_carried_through():
    comparison = compare_flat_vs_hourly(
        reference_service(), reference_config(), parse_overruns("0,100")
    )
    assert comparison.breakeven_overrun_pct.quantize(D("0.01"), rounding=ROUND_HALF_UP) == D("26.67")


# --- overrun parsing -------------------------------------------------------------

def test_parse_overruns_accepts_percent_signs_and_negatives():
    assert parse_overruns("-20, 0%, 25") == [D("-20"), D("0"), D("25")]


def test_parse_overruns_rejects_garbage():
    with pytest.raises(CalcError):
        parse_overruns("0,twenty")


def test_parse_overruns_rejects_empty():
    with pytest.raises(CalcError):
        parse_overruns("  ")


# --- rate=0 sanity ----------------------------------------------------------------

def test_zero_rate_still_prices_materials():
    result = compute_floor(
        reference_service(rate=D("0"), profit_pct=D("0")), reference_config()
    )
    # materials 40 + fixed 12 only; grossed up 25% tax -> 69.333 -> $70 with round 5
    assert result.price == D("70.00")
