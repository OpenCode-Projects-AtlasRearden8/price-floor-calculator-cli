"""Command-line interface for the price floor calculator.

Pure stdlib argparse. Exits: 0 ok, 1 bad input/calculation, 2 file/other errors.
Copyright (c) 2026 Asdale Dynamics, LLC.
"""

import argparse
import sys
from decimal import Decimal
from pathlib import Path
from typing import List, Optional, TextIO, Tuple

from . import __version__
from .batch import (
    CSVError,
    compute_all,
    load_services,
    rate_card_csv,
    rate_card_json,
    rate_card_markdown,
)
from .core import (
    DEFAULT_TIER,
    CalcError,
    Config,
    Service,
    TIER_LIBRARY,
    compare_flat_vs_hourly,
    compute_floor,
    fmt_money,
    fmt_number,
    fmt_pct,
    parse_overruns,
)

SAMPLE_CSV = """service,rate,hours,materials,profit
Handyman Small Repair,55,2,35,10
Housecleaning Visit,40,3,15,5
Event Photography,75,4,0,10
Dog Walking (60 min),30,1,0,0
"""

DEFAULT_OVERRUNS = "-20,0,25,50,100"

NOT_TAX_ADVICE = "Planning estimate only - not tax advice. Confirm your real rate with an accountant."


# ---------------------------------------------------------------------------
# input parsing helpers

def read_amount(text: str, label: str) -> Decimal:
    cleaned = (text or "").strip().replace("$", "").replace(",", "").replace("%", "")
    if not cleaned:
        return Decimal("0")
    try:
        value = Decimal(cleaned)
    except Exception:
        raise CalcError(f"{label} {text!r} is not a number (try something like 45 or 45.50)")
    return value


def read_percent(text: str, label: str) -> Decimal:
    value = read_amount(text, label)
    if value < 0:
        raise CalcError(f"{label} cannot be negative")
    return value


def read_round_step(text: str) -> Decimal:
    value = read_amount(text, "--round-to")
    if value < 0:
        raise CalcError("--round-to cannot be negative")
    return value


def build_config(args) -> Config:
    overhead = None
    if getattr(args, "overhead", None) is not None:
        overhead = read_percent(args.overhead, "--overhead")
    return Config(
        tax_pct=read_percent(args.tax, "--tax"),
        tier=args.tier,
        overhead_pct=overhead,
        annual_expenses=read_amount(args.annual_expenses, "--annual-expenses"),
        jobs_per_year=args.jobs_per_year,
        round_to=read_round_step(args.round_to),
    )


def build_service(args) -> Service:
    return Service(
        name=(args.name or "").strip() or "Your Service",
        rate=read_amount(args.rate, "--rate"),
        hours=read_positive_hours(args.hours),
        materials=read_amount(args.materials, "--materials"),
        profit_pct=read_percent(args.profit, "--profit"),
    )


def read_positive_hours(text: str) -> Decimal:
    value = read_amount(text, "--hours")
    if value <= 0:
        raise CalcError("--hours must be greater than zero (hours per job)")
    return value


# ---------------------------------------------------------------------------
# shared argparse pieces

def _add_service_args(parser) -> None:
    group = parser.add_argument_group("service details")
    group.add_argument("--name", default="", help="service name used in output")
    group.add_argument("--rate", required=True, help="your hourly rate goal, e.g. 45")
    group.add_argument("--hours", required=True,
                       help="realistic hours per job (include drive time and admin)")
    group.add_argument("--materials", default="0", help="materials cost per job, e.g. 35")
    group.add_argument("--profit", default="0",
                       help="optional profit padding, percent of costs (10 = 10%%)")


def _add_business_args(parser) -> None:
    group = parser.add_argument_group("business settings")
    group.add_argument("--tax", default="0",
                       help="tax set-aside as percent of the price (25 = 25%%)")
    group.add_argument("--tier", default=DEFAULT_TIER,
                       choices=sorted(TIER_LIBRARY),
                       help="LLC expense tier (see the 'tiers' command)")
    group.add_argument("--overhead", default=None,
                       help="override the tier with explicit overhead percent (15 = 15%%)")
    group.add_argument("--annual-expenses", default="0",
                       help="fixed yearly LLC costs, e.g. insurance, software")
    group.add_argument("--jobs-per-year", type=int, default=0,
                       help="jobs per year the fixed costs spread across")
    group.add_argument("--round-to", default="5",
                       help="round quotes UP to this increment, e.g. 5 or 0.01 (0 = off)")


# ---------------------------------------------------------------------------
# commands

def cmd_floor(args, out, err) -> int:
    config = build_config(args)
    service = build_service(args)
    result = compute_floor(service, config)

    out.write(f"PRICE FLOOR - {result.service.name}\n")
    out.write("=" * 40 + "\n")
    out.write(f"Charge at least {fmt_money(result.price)} per job.\n\n")
    out.write("How this floor was built:\n")
    for i, step in enumerate(result.steps, 1):
        out.write(f"  {i}. {step}\n")
    out.write("\nAt a glance:\n")
    out.write(
        f"  - Quote {fmt_money(result.price)} per job ->"
        f" {fmt_money(result.effective_hourly)}/hr billed.\n"
    )
    out.write(
        f"  - After the {fmt_pct(config.tax_pct)}% tax set-aside you keep"
        f" {fmt_money(result.net_after_tax)} ({fmt_money(result.net_hourly)}/hr).\n"
    )
    if result.breakeven_overrun_pct is not None:
        cushion = result.breakeven_overrun_pct
        if cushion > 0:
            out.write(
                f"  - Flat-quote cushion: the job may run about"
                f" {fmt_pct(cushion)}% over before you fall below"
                f" {fmt_money(service.rate)}/hr (rounding adds a little safety).\n"
            )
        else:
            out.write(
                "  - Flat-quote cushion: none - add overhead or profit so overruns"
                " don't eat your rate.\n"
            )
    out.write(f"\n{NOT_TAX_ADVICE}\n")
    return 0


def _scenario_label(overrun: Decimal) -> str:
    if overrun < 0:
        return f"finishes {fmt_number(-overrun)}% early"
    if overrun == 0:
        return "on schedule"
    return f"runs {fmt_number(overrun)}% over"


def _table(rows: List[Tuple[str, ...]]) -> str:
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    lines = []
    for index, row in enumerate(rows):
        padded = [cell.ljust(widths[i]) for i, cell in enumerate(row)]
        lines.append("  ".join(padded).rstrip())
        if index == 0:
            lines.append("  ".join("-" * w for w in widths))
    return "\n".join(lines)


def cmd_compare(args, out, err) -> int:
    config = build_config(args)
    service = build_service(args)
    overruns = parse_overruns(args.overruns)
    comparison = compare_flat_vs_hourly(service, config, overruns)

    out.write(f"FLAT VS HOURLY - {service.name}\n")
    out.write("=" * 40 + "\n")
    out.write(
        f"Flat quote: {fmt_money(comparison.flat_result.price)} per job"
        " (no matter how long it takes).\n"
    )
    out.write(f"Hourly quote: {fmt_money(service.rate)}/hr billed as worked.\n\n")
    out.write("What you keep per hour after the tax set-aside:\n\n")

    rows = [(
        "how the job goes", "flat $/job", "flat net/hr", "hourly $/job", "hourly net/hr"
    )]
    for scenario in comparison.scenarios:
        rows.append((
            _scenario_label(scenario.overrun_pct),
            fmt_money(scenario.flat_price),
            fmt_money(scenario.flat_net_hourly),
            fmt_money(scenario.hourly_price),
            fmt_money(scenario.hourly_net_hourly),
        ))
    out.write(_table(rows) + "\n\n")

    flat_early, hourly_early = comparison.scenarios[0], comparison.scenarios[-1]
    if flat_early.flat_net_hourly > hourly_early.hourly_net_hourly:
        out.write(
            "Flat quoting pays more when jobs finish early or on schedule, because\n"
            "the same quote takes less time to earn. Hourly quoting pays more when\n"
            "jobs drag on, because extra hours still bill at your rate.\n"
        )
    else:
        out.write(
            "These scenarios favor hourly quoting; check your overrun ladder again.\n"
        )
    breakeven = comparison.breakeven_overrun_pct
    if breakeven is not None and breakeven > 0:
        out.write(
            f"Plain English: a flat quote stays above your goal until jobs run about\n"
            f"{fmt_pct(breakeven)}% over - roughly your overhead percent plus profit"
            f" padding. Hourly\nquoting just needs honest hour estimates, never a"
            f" price gamble.\n"
        )
    out.write(f"\n{NOT_TAX_ADVICE}\n")
    return 0


def cmd_batch(args, out, err) -> int:
    config = build_config(args)
    services = load_services(args.file)
    results = compute_all(services, config)

    out.write(f"BATCH PRICING - {Path(args.file).name} ({len(results)} services)\n")
    out.write("=" * 40 + "\n")
    tier_note = (
        f"tier {config.tier}"
        if config.overhead_pct is None
        else f"custom overhead {fmt_pct(config.overhead_pct)}%"
    )
    out.write(
        f"Config: {tier_note}, tax set-aside {fmt_pct(config.tax_pct)}%,"
        f" round up to {fmt_money(config.round_to)}\n\n"
    )

    rows = [("#", "service", "rate", "hours", "materials", "price floor",
             "tax jar", "net/hr")]
    for i, r in enumerate(results, 1):
        rows.append((
            str(i),
            r.service.name,
            fmt_money(r.service.rate),
            fmt_number(r.service.hours),
            fmt_money(r.service.materials),
            fmt_money(r.price),
            fmt_money(r.tax_set_aside),
            fmt_money(r.net_hourly),
        ))
    out.write(_table(rows) + "\n\n")

    rates = [r.effective_hourly for r in results]
    prices = [r.price for r in results]
    out.write(
        f"Average billed rate: {fmt_money(sum(rates, Decimal()) / len(rates))}/hr."
        f" Lowest floor {fmt_money(min(prices))}, highest {fmt_money(max(prices))}.\n"
    )
    out.write("Sort by hours and materials to find which services pad your"
              " margins the most.\n\n")

    if args.export_md:
        path = _write_text(args.export_md, rate_card_markdown(results, config, args.title))
        out.write(f"Wrote markdown rate card -> {path}\n")
    if args.export_csv:
        path = _write_text(args.export_csv, rate_card_csv(results, config))
        out.write(f"Wrote CSV rate card -> {path}\n")
    out.write(f"\n{NOT_TAX_ADVICE}\n")
    return 0


def cmd_ratecard(args, out, err) -> int:
    config = build_config(args)
    services = load_services(args.file)
    results = compute_all(services, config)

    if args.format == "md":
        content = rate_card_markdown(results, config, args.title)
    elif args.format == "csv":
        content = rate_card_csv(results, config)
    else:
        content = rate_card_json(results, config, args.title)

    if args.out:
        path = _write_text(args.out, content)
        out.write(f"Rate card ({args.format}) written to {path}\n")
        return 0
    out.write(content)
    return 0


def cmd_tiers(args, out, err) -> int:
    out.write("LLC EXPENSE TIERS\n")
    out.write("=" * 40 + "\n")
    out.write("Tiers add overhead on top of labor, sized to how built-out the LLC is.\n\n")

    sample_config = Config(
        tax_pct=Decimal("25"),
        annual_expenses=Decimal("2400"),
        jobs_per_year=200,
        round_to=Decimal("0"),
    )
    rows = [("tier", "overhead", "covers", "example floor")]
    sample_service = Service("example", Decimal("50"), Decimal("3"),
                             materials=Decimal("40"), profit_pct=Decimal("0"))
    for name, (overhead, description) in sorted(TIER_LIBRARY.items()):
        sample_config.tier = name
        example = compute_floor(sample_service, sample_config)
        rows.append((name, fmt_pct(overhead * 100) + "%", description,
                     fmt_money(example.price) + " / job"))
    out.write(_table(rows) + "\n\n")
    out.write(
        "The example uses a $50/hr goal, a 3-hour job, $40 of materials, $2,400/yr\n"
        "fixed costs over 200 jobs, and a 25% tax set-aside. No tier fits? Pass\n"
        "--overhead with your own percent instead.\n\n" + NOT_TAX_ADVICE + "\n"
    )
    return 0


def cmd_sample(args, out, err) -> int:
    if args.out:
        path = _write_text(args.out, SAMPLE_CSV)
        out.write(f"Sample CSV written to {path}\n")
        out.write("Next: python -m pricefloor batch --file " + str(path) + "\n")
        return 0
    out.write(SAMPLE_CSV)
    out.write("# use: python -m pricefloor batch --file services.csv\n")
    return 0


def _write_text(path_text: str, content: str) -> Path:
    path = Path(path_text)
    parent = path.parent if str(path.parent) else Path(".")
    parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise CalcError(f"could not write {path}: {exc.strerror or exc}")
    return path


# ---------------------------------------------------------------------------
# parser wiring

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pricefloor",
        description=(
            "Small-business price floor calculator: what you must actually charge."
            " Computes a per-job floor from your hourly goal, LLC expense tier,"
            " tax set-aside, materials, and hours. Pure stdlib, offline, not tax advice."
        ),
        epilog=(
            "examples:\n"
            "  python -m pricefloor floor --rate 50 --hours 3 --materials 40"
            " --tax 25 --tier standard --annual-expenses 2400 --jobs-per-year 200\n"
            "  python -m pricefloor compare --rate 50 --hours 3 --tax 25 --overruns 0,25,50\n"
            "  python -m pricefloor sample --out services.csv\n"
            "  python -m pricefloor batch --file services.csv --export-md ratecard.md\n"
            "  python -m pricefloor ratecard --file services.csv --format json\n"
            "  python -m pricefloor tiers\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version",
                        version=f"pricefloor {__version__}")

    sub = parser.add_subparsers(dest="command", required=True)

    floor = sub.add_parser("floor", help="price floor for one service, explained plainly")
    _add_service_args(floor)
    _add_business_args(floor)
    floor.set_defaults(func=cmd_floor)

    compare = sub.add_parser("compare", help="flat-fee vs hourly quoting, side by side")
    _add_service_args(compare)
    _add_business_args(compare)
    compare.add_argument("--overruns", default=DEFAULT_OVERRUNS,
                         help="comma list of overrun percents, e.g. 0,25,50 (-20 = early)")
    compare.set_defaults(func=cmd_compare)

    batch = sub.add_parser("batch", help="price many services from a CSV file")
    batch.add_argument("--file", required=True, help="CSV of services (see 'sample')")
    _add_business_args(batch)
    batch.add_argument("--export-md", default=None,
                       help="write markdown rate card to this path")
    batch.add_argument("--export-csv", default=None,
                       help="write CSV rate card to this path")
    batch.add_argument("--title", default="Rate Card", help="title for exported cards")
    batch.set_defaults(func=cmd_batch)

    ratecard = sub.add_parser("ratecard", help="export a client-ready rate card")
    ratecard.add_argument("--file", required=True, help="CSV of services (see 'sample')")
    ratecard.add_argument("--format", default="md", choices=["md", "csv", "json"],
                          help="rate card format (default: md)")
    ratecard.add_argument("--out", default=None, help="write to file (default: print)")
    _add_business_args(ratecard)
    ratecard.add_argument("--title", default="Rate Card", help="card title")
    ratecard.set_defaults(func=cmd_ratecard)

    sample = sub.add_parser("sample", help="print or write the sample CSV")
    sample.add_argument("--out", default=None, help="write to file (default: print)")
    sample.set_defaults(func=cmd_sample)

    tiers = sub.add_parser("tiers", help="show LLC expense tiers")
    tiers.set_defaults(func=cmd_tiers)
    return parser


def main(argv=None, out: Optional[TextIO] = None, err: Optional[TextIO] = None) -> int:
    out = out if out is not None else sys.stdout
    err = err if err is not None else sys.stderr
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        return args.func(args, out, err)
    except CalcError as exc:
        print(f"error: {exc}", file=err)
        return 1
    except (OSError, CSVError) as exc:
        print(f"error: {exc}", file=err)
        return 2
