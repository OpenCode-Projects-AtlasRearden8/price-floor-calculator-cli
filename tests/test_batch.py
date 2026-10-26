"""Tests for CSV loading and rate card builders (pricefloor.batch)."""

import csv
import json
from decimal import Decimal

import pytest

from pricefloor.batch import (
    CSVError,
    compute_all,
    load_services,
    rate_card_csv,
    rate_card_dict,
    rate_card_json,
    rate_card_markdown,
)
from pricefloor.core import Config, Service, fmt_money

D = Decimal


def good_csv(tmp_path, text):
    path = tmp_path / "services.csv"
    path.write_text(text, encoding="utf-8")
    return path


SAMPLE = """service,rate,hours,materials,profit
Handyman Small Repair,55,2,35,10
Housecleaning Visit,40,3,15,5
Event Photography,75,4,0,10
Dog Walking (60 min),30,1,0,0
"""


def default_config(**overrides):
    values = dict(
        tax_pct=D("25"),
        tier="standard",
        overhead_pct=None,
        annual_expenses=D("0"),
        jobs_per_year=0,
        round_to=D("5"),
    )
    values.update(overrides)
    return Config(**values)


def test_load_sample_services(tmp_path):
    services = load_services(good_csv(tmp_path, SAMPLE))
    assert len(services) == 4
    assert services[0].name == "Handyman Small Repair"
    assert services[0].rate == D("55")
    assert services[0].hours == D("2")
    assert services[0].materials == D("35")
    assert services[0].profit_pct == D("10")
    assert services[3].materials == D("0")


def test_header_aliases_accepted(tmp_path):
    text = "name,hourly_rate,hours_per_job,supplies,margin\nJob A,45,1.5,10,0\n"
    services = load_services(good_csv(tmp_path, text))
    assert services[0].name == "Job A"
    assert services[0].rate == D("45")
    assert services[0].hours == D("1.5")


def test_dollars_and_commas_in_cells(tmp_path):
    text = 'service,rate,hours,materials\nBig Job,"$1,200",2,"$300"\n'
    services = load_services(good_csv(tmp_path, text))
    assert services[0].rate == D("1200")
    assert services[0].materials == D("300")


def test_missing_required_column_raises(tmp_path):
    text = "service,rate\nOnly Name,45\n"
    with pytest.raises(CSVError) as excinfo:
        load_services(good_csv(tmp_path, text))
    assert "hours" in str(excinfo.value)


def test_bad_number_reports_row_number(tmp_path):
    text = "service,rate,hours\nGood Job,45,1\nBad Job,abc,1\n"
    with pytest.raises(CSVError) as excinfo:
        load_services(good_csv(tmp_path, text))
    assert "row 3" in str(excinfo.value)
    assert "rate" in str(excinfo.value)


def test_missing_file_raises_friendly(tmp_path):
    with pytest.raises(CSVError) as excinfo:
        load_services(tmp_path / "nope.csv")
    assert "not found" in str(excinfo.value)


def test_blank_rows_tolerated(tmp_path):
    text = "service,rate,hours\n\nJob A,45,1\n\n"
    services = load_services(good_csv(tmp_path, text))
    assert len(services) == 1


def test_empty_file_raises(tmp_path):
    with pytest.raises(CSVError):
        load_services(good_csv(tmp_path, ""))


def test_header_only_raises(tmp_path):
    with pytest.raises(CSVError):
        load_services(good_csv(tmp_path, "service,rate,hours\n"))


def test_compute_all_runs_every_service(tmp_path):
    results = compute_all(load_services(good_csv(tmp_path, SAMPLE)), default_config())
    assert len(results) == 4
    assert all(r.price > 0 for r in results)


# --- rate card builders ---------------------------------------------------

def rows_and_config():
    services = [
        Service("Fence Repair", D("50"), D("3"), D("40"), D("10")),
    ]
    return compute_all(services, default_config())


def test_rate_card_csv_content():
    results = rows_and_config()
    text = rate_card_csv(results, default_config())
    lines = list(csv.reader(text.splitlines()))
    assert lines[0][0] == "service"
    headers = ["price_floor", "tax_set_aside", "effective_hourly"]
    for expected in headers:
        assert expected in lines[0]
    body = {row[0]: row for row in lines[1:]}
    assert "Fence Repair" in body
    fence = body["Fence Repair"]
    assert D(fence[lines[0].index("price_floor")]) == results[0].price


def test_rate_card_json_content():
    results = rows_and_config()
    data = json.loads(rate_card_json(results, default_config(), "My Card"))
    assert data["title"] == "My Card"
    assert data["services"][0]["service"] == "Fence Repair"
    assert data["config"]["tier"] == "standard"
    assert data["config"]["overhead_fraction"] == "0.12"
    assert "not tax advice" in data["disclaimer"]


def test_rate_card_markdown_is_readable(tmp_path):
    results = rows_and_config()
    text = rate_card_markdown(results, default_config(), "My Card")
    assert text.startswith("# Rate Card - My Card")
    assert "**$310.00**" in text and fmt_money(results[0].price) in text
    assert "Asdale Dynamics, LLC" in text
    assert "cashflow-simple-ledger" in text
    assert "| Service |" in text


def test_rate_card_dict_config_snapshot():
    results = rows_and_config()
    data = rate_card_dict(results, default_config(tax_pct=D("30")), "T")
    assert data["config"]["tax_pct"] == "30"
