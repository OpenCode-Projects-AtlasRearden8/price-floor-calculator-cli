"""End-to-end CLI tests (argparse wiring, exit codes, output text)."""

import io
import json
from decimal import Decimal

import pytest

from pricefloor.cli import SAMPLE_CSV, main

D = Decimal


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    code = main(argv, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


# --- floor -------------------------------------------------------------

FLOOR_ARGS = [
    "floor",
    "--name", "Handyman Small Repair",
    "--rate", "50",
    "--hours", "3",
    "--materials", "40",
    "--profit", "10",
    "--tax", "25",
    "--tier", "standard",
    "--annual-expenses", "2400",
    "--jobs-per-year", "200",
]


def test_floor_full_run_shows_price_and_story():
    code, out, err = run(FLOOR_ARGS)
    assert code == 0
    assert err == ""
    assert "Charge at least $325.00 per job." in out
    assert "$150.00" in out          # labor
    assert "Flat-quote cushion" in out
    assert "not tax advice" in out


def test_floor_invalid_tax_exits_1():
    code, out, err = run(FLOOR_ARGS + ["--tax", "100"])
    assert code == 1
    assert "under 100%" in err


def test_floor_nonnumeric_rate_exits_1():
    code, out, err = run(["floor", "--rate", "lots", "--hours", "2"])
    assert code == 1
    assert "not a number" in err


def test_floor_missing_required_flag_is_usage_error():
    with pytest.raises(SystemExit) as excinfo:
        run(["floor", "--rate", "50"])
    assert excinfo.value.code == 2


def test_floor_missing_jobs_per_year_hint():
    code, out, err = run(
        ["floor", "--rate", "50", "--hours", "3", "--annual-expenses", "2400"]
    )
    assert code == 1
    assert "--jobs-per-year" in err


def test_floor_zero_materials_defaults():
    code, out, err = run(["floor", "--rate", "35", "--hours", "1"])
    assert code == 0
    # 35 labor + 4.20 standard-tier overhead -> 39.20 -> rounded up to $40
    assert "Charge at least $40.00 per job." in out


# --- compare -----------------------------------------------------------

def test_compare_shows_scenarios_and_breakeven():
    code, out, err = run([
        "compare", "--rate", "50", "--hours", "3", "--materials", "40",
        "--profit", "10", "--tax", "25",
    ])
    assert code == 0
    assert "finishes 20% early" in out
    assert "on schedule" in out
    assert "runs 100% over" in out
    assert "Plain English" in out
    assert "25.9%" in out          # (12% tier overhead + 10% profit) cushion


def test_compare_custom_overruns():
    code, out, err = run([
        "compare", "--rate", "40", "--hours", "2", "--overruns", "0,10",
    ])
    assert code == 0
    assert "runs 10% over" in out
    assert "runs 50% over" not in out


def test_compare_bad_overrun_exits_1():
    code, out, err = run([
        "compare", "--rate", "40", "--hours", "2", "--overruns", "banana",
    ])
    assert code == 1
    assert "banana" in err


# --- batch -------------------------------------------------------------

def test_batch_from_csv_and_exports(tmp_path):
    services_csv = tmp_path / "services.csv"
    services_csv.write_text(SAMPLE_CSV, encoding="utf-8")
    md_path = tmp_path / "card.md"
    csv_path = tmp_path / "card.csv"

    code, out, err = run([
        "batch",
        "--file", str(services_csv),
        "--tax", "25",
        "--export-md", str(md_path),
        "--export-csv", str(csv_path),
    ])
    assert code == 0
    assert "Batch Pricing" in out or "BATCH PRICING" in out
    assert "Handyman Small Repair" in out
    assert "Average billed rate" in out
    assert md_path.is_file()
    assert "# Rate Card" in md_path.read_text()
    assert "price_floor" in csv_path.read_text()
    assert "Handyman Small Repair" in csv_path.read_text()


def test_batch_missing_file_exits_2():
    code, out, err = run(["batch", "--file", "does-not-exist.csv"])
    assert code == 2
    assert "not found" in err


def test_batch_bad_row_reports_and_exits_2(tmp_path):
    services_csv = tmp_path / "bad.csv"
    services_csv.write_text(
        "service,rate,hours\nGood,45,1\nBad,oops,1\n", encoding="utf-8"
    )
    code, out, err = run(["batch", "--file", str(services_csv)])
    assert code == 2
    assert "row 3" in err


# --- ratecard -----------------------------------------------------------

def test_ratecard_json_to_stdout(tmp_path):
    services_csv = tmp_path / "s.csv"
    services_csv.write_text(SAMPLE_CSV, encoding="utf-8")
    code, out, err = run([
        "ratecard", "--file", str(services_csv), "--format", "json",
    ])
    assert code == 0
    data = json.loads(out)
    assert data["title"] == "Rate Card"
    assert len(data["services"]) == 4


def test_ratecard_csv_stdout(tmp_path):
    services_csv = tmp_path / "s.csv"
    services_csv.write_text(SAMPLE_CSV, encoding="utf-8")
    code, out, err = run([
        "ratecard", "--file", str(services_csv), "--format", "csv",
    ])
    assert code == 0
    assert "service,rate_goal,hours,materials,price_floor" in out


def test_ratecard_md_written_to_file(tmp_path):
    services_csv = tmp_path / "s.csv"
    services_csv.write_text(SAMPLE_CSV, encoding="utf-8")
    out_path = tmp_path / "ratecard.md"
    code, out, err = run([
        "ratecard", "--file", str(services_csv), "--format", "md",
        "--title", "Dylan's Services", "--out", str(out_path),
    ])
    assert code == 0
    text = out_path.read_text()
    assert "Dylan's Services" in text
    assert "Asdale Dynamics, LLC" in text


# --- sample / tiers / version -------------------------------------------

def test_sample_prints_csv():
    code, out, err = run(["sample"])
    assert code == 0
    assert out.startswith("service,rate,hours,materials,profit")
    assert "Handyman Small Repair" in out


def test_sample_writes_file(tmp_path):
    target = tmp_path / "services.csv"
    code, out, err = run(["sample", "--out", str(target)])
    assert code == 0
    assert target.is_file()
    assert target.read_text().startswith("service,rate,hours,materials,profit")


def test_tiers_lists_all_tiers():
    code, out, err = run(["tiers"])
    assert code == 0
    for tier in ("micro", "standard", "established"):
        assert tier in out


def test_version_flag():
    out, err = io.StringIO(), io.StringIO()
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"], out=out, err=err)
    assert excinfo.value.code == 0


def test_help_shows_examples(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    assert excinfo.value.code == 0
    text = capsys.readouterr().out
    assert "batch" in text
    assert "ratecard" in text
