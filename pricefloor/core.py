"""Calculation engine: price floors, flat-vs-hourly comparison, tax gross-up.

Pure stdlib, exact Decimal math. Copyright (c) 2026 Asdale Dynamics, LLC.
"""

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
from typing import List, Optional, Tuple

CENTS = Decimal("0.01")
ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")


class CalcError(Exception):
    """Raised for invalid calculation inputs (friendly, printable messages)."""


# LLC expense tiers: overhead added on top of labor, chosen by how built-out
# the business is. Values are fractions (0.12 == 12 percent).
TIER_LIBRARY = {
    "micro": (
        Decimal("0.06"),
        "side-gig LLC: phone plan, basic insurance, a few tools",
    ),
    "standard": (
        Decimal("0.12"),
        "registered LLC: software subscriptions, business banking, some marketing",
    ),
    "established": (
        Decimal("0.20"),
        "growing LLC: office costs, bookkeeper, insurance, support tools",
    ),
}

DEFAULT_TIER = "standard"


def ceil_to(value: Decimal, step: Decimal) -> Decimal:
    """Round *value* up to a multiple of *step*. step <= 0 means no rounding."""
    if step is None or step <= ZERO:
        return value.quantize(CENTS, rounding=ROUND_HALF_UP)
    multiple = (value / step).to_integral_value(rounding=ROUND_CEILING)
    return (multiple * step).quantize(CENTS, rounding=ROUND_HALF_UP)


def fmt_money(value: Decimal) -> str:
    """Format a Decimal as $1,234.56 (manual grouping; no float involved)."""
    q = value.quantize(CENTS, rounding=ROUND_HALF_UP)
    s = f"{q:f}"
    negative = s.startswith("-")
    if negative:
        s = s[1:]
    if "." in s:
        int_part, frac = s.split(".", 1)
    else:
        int_part, frac = s, ""
    int_part = f"{int(int_part):,}"
    return ("-" if negative else "") + "$" + int_part + "." + frac


def fmt_number(value: Decimal) -> str:
    """Compact numeric display used inside explanation text (hours, rates)."""
    q = value.quantize(CENTS, rounding=ROUND_HALF_UP)
    s = f"{q:f}"
    if s.endswith("00") and "." in s:
        s = s.split(".")[0]
    else:
        s = s.rstrip("0").rstrip(".")
    if s in ("", "-"):
        s = "0"
    return s


def fmt_pct(value: Decimal, places: str = "0.1") -> str:
    """Percent display, lightly rounded (e.g. 26.7%)."""
    q = value.quantize(Decimal(places), rounding=ROUND_HALF_UP)
    return fmt_number(q)


@dataclass
class Service:
    """One thing you sell: a target hourly rate and the time/materials it takes."""

    name: str
    rate: Decimal  # target dollars per hour (your goal take-home-before-tax rate)
    hours: Decimal  # realistic hours per job (include drive, admin wrap-up)
    materials: Decimal = ZERO
    profit_pct: Decimal = ZERO  # optional padding, percent of costs


@dataclass
class Config:
    """Business-wide settings shared by every service you price."""

    tax_pct: Decimal = ZERO  # percent of revenue to set aside for taxes
    tier: str = DEFAULT_TIER  # micro | standard | established
    overhead_pct: Optional[Decimal] = None  # explicit override, fraction
    annual_expenses: Decimal = ZERO
    jobs_per_year: int = 0
    round_to: Decimal = Decimal("5")  # round quotes UP to this increment (0 = off)

    def resolved_overhead_pct(self) -> Decimal:
        if self.overhead_pct is not None:
            if self.overhead_pct < ZERO:
                raise CalcError("overhead percent cannot be negative")
            return self.overhead_pct / HUNDRED
        if self.tier is None:
            return ZERO
        if self.tier not in TIER_LIBRARY:
            known = ", ".join(sorted(TIER_LIBRARY))
            raise CalcError(
                f"unknown expense tier {self.tier!r}; choose one of: {known}"
            )
        return TIER_LIBRARY[self.tier][0]

    def validate(self) -> None:
        if self.tax_pct < ZERO:
            raise CalcError("tax set-aside cannot be negative")
        if self.tax_pct >= HUNDRED:
            raise CalcError("tax set-aside must be under 100% (you would keep nothing)")
        if self.annual_expenses < ZERO:
            raise CalcError("annual expenses cannot be negative")
        if self.annual_expenses > ZERO and self.jobs_per_year <= 0:
            raise CalcError(
                "--annual-expenses needs --jobs-per-year (how many jobs the year's"
                " fixed costs get spread across)"
            )
        if self.round_to < ZERO:
            raise CalcError("--round-to cannot be negative")


@dataclass
class FloorResult:
    """Everything needed to explain one price floor in plain English."""

    service: Service
    config: Config
    labor: Decimal
    overhead_tier: Decimal  # tier/override overhead, as dollars
    overhead_fixed: Decimal  # annual expenses amortized to this job
    materials: Decimal
    profit: Decimal  # profit padding, as dollars
    subtotal: Decimal  # what you need to net after the tax set-aside
    price_raw: Decimal  # subtotal grossed up for tax
    price: Decimal  # after round-up; the number you quote
    tax_set_aside: Decimal
    net_after_tax: Decimal
    effective_hourly: Decimal  # price / hours (gross billed per hour)
    net_hourly: Decimal  # what's left per hour after the tax set-aside
    breakeven_overrun_pct: Optional[Decimal]  # flat-quote cushion vs scope creep
    steps: List[str] = field(default_factory=list)


def _validate_service(service: Service) -> None:
    if service.hours <= ZERO:
        raise CalcError("hours per job must be greater than zero")
    if service.rate < ZERO:
        raise CalcError("hourly rate goal cannot be negative")
    if service.materials < ZERO:
        raise CalcError("materials cost cannot be negative")
    if service.profit_pct < ZERO:
        raise CalcError("profit padding cannot be negative")
    if service.profit_pct >= HUNDRED * HUNDRED:
        raise CalcError("profit padding is a percent (0-100 style), that value is too big")


def compute_floor(service: Service, config: Config) -> FloorResult:
    """Compute the minimum price per job, plus the plain-English story."""
    _validate_service(service)
    config.validate()
    overhead_pct = config.resolved_overhead_pct()

    labor = service.rate * service.hours
    overhead_tier = labor * overhead_pct
    overhead_fixed = (
        config.annual_expenses / Decimal(config.jobs_per_year)
        if config.annual_expenses > ZERO
        else ZERO
    )
    base = labor + overhead_tier + overhead_fixed + service.materials
    profit = base * (service.profit_pct / HUNDRED)
    subtotal = base + profit

    tax_rate = config.tax_pct / HUNDRED
    price_raw = subtotal / (ONE - tax_rate)
    price = ceil_to(price_raw, config.round_to)
    tax_set_aside = price * tax_rate
    net_after_tax = price - tax_set_aside

    effective_hourly = price / service.hours
    net_hourly = net_after_tax / service.hours

    breakeven = None
    if labor > ZERO:
        breakeven = ((overhead_tier + profit) / labor) * HUNDRED

    steps = _explain_steps(
        service=service,
        config=config,
        overhead_pct=overhead_pct,
        labor=labor,
        overhead_tier=overhead_tier,
        overhead_fixed=overhead_fixed,
        base=base,
        profit=profit,
        subtotal=subtotal,
        price_raw=price_raw,
        price=price,
        tax_set_aside=tax_set_aside,
        net_after_tax=net_after_tax,
    )

    return FloorResult(
        service=service,
        config=config,
        labor=labor,
        overhead_tier=overhead_tier,
        overhead_fixed=overhead_fixed,
        materials=service.materials,
        profit=profit,
        subtotal=subtotal,
        price_raw=price_raw,
        price=price,
        tax_set_aside=tax_set_aside,
        net_after_tax=net_after_tax,
        effective_hourly=effective_hourly,
        net_hourly=net_hourly,
        breakeven_overrun_pct=breakeven,
        steps=steps,
    )


def _explain_steps(service, config, *, overhead_pct, labor, overhead_tier,
                   overhead_fixed, base, profit, subtotal, price_raw, price,
                   tax_set_aside, net_after_tax) -> List[str]:
    tax_rate = config.tax_pct / HUNDRED
    overhead_desc = "your custom overhead percent"
    if config.overhead_pct is None and config.tier in TIER_LIBRARY:
        overhead_desc = f"tier '{config.tier}' ({TIER_LIBRARY[config.tier][1]})"

    steps: List[str] = []
    steps.append(
        f"Your goal: {fmt_money(service.rate)}/hr for {fmt_number(service.hours)} hours"
        f" -> labor {fmt_money(labor)}."
    )
    if overhead_tier > ZERO:
        steps.append(
            f"Small-business overhead ({fmt_pct(overhead_pct * HUNDRED)}% from"
            f" {overhead_desc}) -> +{fmt_money(overhead_tier)}."
        )
    if overhead_fixed > ZERO:
        steps.append(
            f"{fmt_money(config.annual_expenses)}/yr of fixed LLC costs spread over"
            f" {config.jobs_per_year:,} jobs -> +{fmt_money(overhead_fixed)} per job."
        )
    if service.materials > ZERO:
        steps.append(f"Materials you buy for this job -> +{fmt_money(service.materials)}.")
    if profit > ZERO:
        steps.append(
            f"Profit padding of {fmt_pct(service.profit_pct)}% -> +{fmt_money(profit)}."
        )
    steps.append(f"Amount you need to walk away with: {fmt_money(subtotal)}.")
    if config.tax_pct > ZERO:
        steps.append(
            f"Set aside {fmt_pct(config.tax_pct)}% for taxes: charge"
            f" {fmt_money(price_raw)} so that {fmt_money(price_raw * tax_rate)}"
            f" goes to the tax jar and {fmt_money(subtotal)} stays yours."
        )
    else:
        steps.append("No tax set-aside configured, so the floor is the subtotal.")
    if price != price_raw.quantize(CENTS, rounding=ROUND_HALF_UP):
        steps.append(
            f"Rounded up to the nearest {fmt_money(config.round_to)} ->"
            f" quote {fmt_money(price)}."
        )
    return steps


@dataclass
class OverrunScenario:
    overrun_pct: Decimal
    hours_actual: Decimal
    flat_price: Decimal
    flat_net_hourly: Decimal
    hourly_price: Decimal
    hourly_net_hourly: Decimal


@dataclass
class ComparisonResult:
    service: Service
    config: Config
    flat_result: FloorResult
    scenarios: List[OverrunScenario]
    breakeven_overrun_pct: Optional[Decimal]


DEFAULT_OVERRUN_LADDER = ("-20", "0", "25", "50", "100")


def parse_overruns(text: str) -> List[Decimal]:
    values: List[Decimal] = []
    for chunk in text.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if chunk.endswith("%"):
            chunk = chunk[:-1]
        try:
            value = Decimal(chunk)
        except Exception:
            raise CalcError(f"could not read overrun percent {chunk!r}")
        if value < Decimal("-99") * HUNDRED or value > HUNDRED * HUNDRED:
            raise CalcError(f"overrun percent {chunk!r} is out of range")
        values.append(value)
    if not values:
        raise CalcError("no overrun percents given")
    return values


def compare_flat_vs_hourly(
    service: Service,
    config: Config,
    overruns: List[Decimal],
) -> ComparisonResult:
    """Simulate flat-fee vs hourly quoting as jobs run over (or finish early).

    Flat: one price quoted from the on-schedule floor; you keep extra margin
    when work goes fast but fall below floor when it drags.
    Hourly: your rate billed per actual hour (floor recomputed at real hours),
    so overrun time still pays but speed is not rewarded.
    """
    _validate_service(service)
    config.validate()
    flat_result = compute_floor(service, config)
    overhead_fixed = flat_result.overhead_fixed
    materials = service.materials

    scenarios: List[OverrunScenario] = []
    for overrun in overruns:
        hours_actual = service.hours * (ONE + overrun / HUNDRED)
        if hours_actual <= ZERO:
            raise CalcError("overrun ladder cannot take actual hours to zero")
        flat_net_hourly = (
            (flat_result.net_after_tax - materials - overhead_fixed) / hours_actual
        )
        hourly_service = Service(
            name=service.name,
            rate=service.rate,
            hours=hours_actual,
            materials=materials,
            profit_pct=service.profit_pct,
        )
        hourly_at_overrun = compute_floor(hourly_service, config)
        hourly_net_hourly = (
            (hourly_at_overrun.net_after_tax - materials - overhead_fixed)
            / hours_actual
        )
        scenarios.append(
            OverrunScenario(
                overrun_pct=overrun,
                hours_actual=hours_actual,
                flat_price=flat_result.price,
                flat_net_hourly=flat_net_hourly,
                hourly_price=hourly_at_overrun.price,
                hourly_net_hourly=hourly_net_hourly,
            )
        )

    return ComparisonResult(
        service=service,
        config=config,
        flat_result=flat_result,
        scenarios=scenarios,
        breakeven_overrun_pct=flat_result.breakeven_overrun_pct,
    )
