"""CSV batch loading and rate card export (markdown, CSV, JSON).

Pure stdlib. Copyright (c) 2026 Asdale Dynamics, LLC.
"""

import csv
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional

from .core import (
    Config,
    FloorResult,
    Service,
    compute_floor,
    fmt_money,
    fmt_number,
    fmt_pct,
)

REQUIRED_FIELDS = ("service", "rate", "hours")

HEADER_ALIASES: Dict[str, tuple] = {
    "service": ("service", "name", "title", "job", "service_name", "service name"),
    "rate": ("rate", "hourly", "hourly_rate", "rate_goal", "hourly rate",
             "rate goal", "target_rate", "target rate"),
    "hours": ("hours", "hours_per_job", "job_hours", "hours per job"),
    "materials": ("materials", "material", "materials_cost", "supplies",
                  "materials cost"),
    "profit": ("profit", "profit_pct", "margin", "profit_margin", "profit_percent",
               "profit %"),
}


class CSVError(Exception):
    """Friendly error for CSV problems, with row numbers where useful."""


def _canonical_header(raw: str) -> Optional[str]:
    cleaned = raw.strip().lower().replace(" ", "_").replace("-", "_")
    for canonical, aliases in HEADER_ALIASES.items():
        if cleaned in aliases:
            return canonical
    return None


def _cmap(mapping: Dict[str, str], canonical: str) -> str:
    for raw_header, canon in mapping.items():
        if canon == canonical:
            return raw_header
    raise KeyError(canonical)


def _row_lookup(row: dict, mapping: Dict[str, str], canonical: str):
    header = _cmap(mapping, canonical) if canonical in mapping.values() else None
    if header is None:
        return None
    return row.get(header)


def parse_number(raw, field_name: str, row_no: int, default: Decimal = Decimal("0")) -> Decimal:
    text = (str(raw) if raw is not None else "").strip().replace("$", "").replace(",", "").replace("%", "")
    if not text:
        return default
    try:
        return Decimal(text)
    except Exception:
        raise CSVError(
            f"row {row_no}: the {field_name} value {text!r} is not a number"
        )


def load_services(path) -> List[Service]:
    """Load services from a CSV file. Collects every row problem before failing."""
    path = Path(path)
    if not path.is_file():
        raise CSVError(f"CSV file not found: {path}")

    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise CSVError(f"{path.name}: the file is empty (needs a header row)")

        mapping: Dict[str, str] = {}
        for raw_header in reader.fieldnames:
            canonical = _canonical_header(raw_header)
            if canonical and canonical not in mapping.values():
                mapping[raw_header] = canonical

        missing = [f for f in REQUIRED_FIELDS if f not in mapping.values()]
        if missing:
            raise CSVError(
                f"{path.name}: missing required column(s): " + ", ".join(missing)
                + " (optional columns: materials, profit)"
            )

        services: List[Service] = []
        problems: List[str] = []
        for row_no, row in enumerate(reader, start=2):
            if not any((value or "").strip() for value in row.values()):
                continue  # tolerate blank spacer rows
            try:
                service = Service(
                    name=(row[_cmap(mapping, "service")] or "").strip()
                    or f"service-row-{row_no}",
                    rate=parse_number(row[_cmap(mapping, "rate")], "rate", row_no),
                    hours=parse_number(row[_cmap(mapping, "hours")], "hours", row_no),
                    materials=parse_number(
                        _row_lookup(row, mapping, "materials"), "materials", row_no
                    ),
                    profit_pct=parse_number(
                        _row_lookup(row, mapping, "profit"), "profit", row_no
                    ),
                )
            except CSVError as exc:
                problems.append(str(exc))
                continue
            services.append(service)

        if problems:
            raise CSVError(f"{path.name} has problems:\n" + "\n".join(problems))
        if not services:
            raise CSVError(f"{path.name}: no service rows found under the header")
        return services


def compute_all(services: List[Service], config: Config) -> List[FloorResult]:
    """Run the floor calculation for every service (same taxonomy behavior)."""
    results = []
    for service in services:
        results.append(compute_floor(service, config))
    return results


# ---------------------------------------------------------------------------
# Rate card builders
# ---------------------------------------------------------------------------

_RATE_CARD_HEADERS = (
    "service", "rate_goal", "hours", "materials", "price_floor",
    "tax_set_aside", "net_after_tax", "effective_hourly",
)


def _card_rows(results: List[FloorResult]) -> List[Dict[str, str]]:
    rows = []
    for r in results:
        rows.append(
            {
                "service": r.service.name,
                "rate_goal": str(r.service.rate),
                "hours": str(r.service.hours),
                "materials": str(r.service.materials),
                "price_floor": f"{r.price:f}",
                "tax_set_aside": f"{r.tax_set_aside:f}",
                "net_after_tax": f"{r.net_after_tax:f}",
                "effective_hourly": f"{r.effective_hourly:f}",
            }
        )
    return rows


def rate_card_dict(results: List[FloorResult], config: Config, title: str) -> dict:
    return {
        "title": title,
        "generated": date.today().isoformat(),
        "disclaimer": "Price floors are minimums to cover costs, not offers; not tax advice.",
        "config": {
            "tier": config.tier,
            "overhead_fraction": str(config.resolved_overhead_pct()),
            "tax_pct": str(config.tax_pct),
            "annual_expenses": str(config.annual_expenses),
            "jobs_per_year": config.jobs_per_year,
            "round_to": str(config.round_to),
        },
        "services": _card_rows(results),
    }


def rate_card_markdown(results: List[FloorResult], config: Config, title: str) -> str:
    lines = [
        f"# Rate Card - {title}",
        "",
        f"_Generated {date.today().isoformat()} by pricefloor (Asdale Dynamics, LLC)."
        " Prices are floors (minimums), not offers. Not tax advice._",
        "",
        "| Service | Rate goal | Hours | Materials | Price floor |"
        " Set aside for tax | Net after tax | Billed $/hr |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in results:
        lines.append(
            f"| {r.service.name} | {fmt_money(r.service.rate)} |"
            f" {fmt_number(r.service.hours)} | {fmt_money(r.service.materials)} |"
            f" **{fmt_money(r.price)}** | {fmt_money(r.tax_set_aside)} |"
            f" {fmt_money(r.net_after_tax)} | {fmt_money(r.effective_hourly)} |"
        )
    lines += [
        "",
        "How floors were built:",
        f"- Hourly rate goal x hours, plus an expense tier"
        f" overhead of {fmt_pct(config.resolved_overhead_pct() * 100)}%.",
    ]
    if config.annual_expenses > 0:
        lines.append(
            f"- {fmt_money(config.annual_expenses)}/yr fixed LLC costs spread"
            f" over {config.jobs_per_year:,} jobs."
        )
    lines += [
        f"- Tax set-aside: {fmt_pct(config.tax_pct)}% of the quote (use your own real %).",
        f"- Quotes rounded up to the nearest {fmt_money(config.round_to)} (0 = exact cents).",
        "",
        "Companion tool: cashflow-simple-ledger for tracking the money these jobs earn.",
    ]
    return "\n".join(lines) + "\n"


def rate_card_csv(results: List[FloorResult], config: Config) -> str:
    import io

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(_RATE_CARD_HEADERS))
    writer.writeheader()
    for row in _card_rows(results):
        writer.writerow(row)
    return buffer.getvalue()


def rate_card_json(results: List[FloorResult], config: Config, title: str) -> str:
    return json.dumps(rate_card_dict(results, config, title), indent=2) + "\n"
