# STATUS

Project: **pricefloor** - small-business price floor calculator CLI
(c) 2026 Asdale Dynamics, LLC - MIT licensed. Pure stdlib Python, offline.

## What was built

A command-line tool that tells a small business owner what they *must* charge:

- `floor` - per-service price floor from hourly rate goal, hours, materials,
  optional profit padding, and a tax gross-up so the set-aside money is covered.
- `compare` - flat-fee vs hourly quoting simulated across an overrun ladder
  (-20% early to +100% over), including the flat-quote cushion (breakeven
  overrun percent) in plain English.
- `batch` - price a whole CSV of services with shared business settings,
  optional `--export-md` / `--export-csv` rate cards.
- `ratecard` - client-ready rate card in markdown, CSV, or JSON; print or save
  to a file.
- `sample` - prints/writes a starter CSV so the first run is friction-free.
- `tiers` - the three LLC expense tiers (`micro` 6%, `standard` 12%,
  `established` 20%) with worked examples, plus `--overhead` to override.

Implementation: `pricefloor/core.py` (exact Decimal math engine),
`pricefloor/batch.py` (CSV loading with row-numbered error messages, rate card
builders), `pricefloor/cli.py` (argparse commands). No third-party
dependencies; nothing leaves the machine.

## How to run it

```bash
python3 -m pricefloor tiers
python3 -m pricefloor floor --rate 50 --hours 3 --materials 40 \
  --tax 25 --tier standard --annual-expenses 2400 --jobs-per-year 200
python3 -m pricefloor sample --out services.csv
python3 -m pricefloor batch --file services.csv --tax 25 --export-md ratecard.md
python3 -m pricefloor compare --rate 50 --hours 3 --tax 25
python3 -m pricefloor ratecard --file services.csv --format json --out ratecard.json
python3 -m pricefloor --help
```

Exit codes: 0 ok, 1 bad input (friendly message on stderr), 2 file/other errors.

## Verification results

- `python3 -m pytest -q` -> **72 passed** (engine math, validation, CSV loader,
  rate card builders, and CLI end-to-end via `main()`).
- `python3 -m py_compile pricefloor/*.py` -> compiles clean on Python 3.13.5.
- Smoke-ran every command against `sample_services.csv`; spot-checked the math
  by hand: labor 150 + tier 18 + fixed 12 + materials 40 + profit 22 = 242,
  grossed up /0.75 = 322.67, rounded to $5 -> $325.00, tax jar 81.25, net 243.75.
- Verified the tax gross-up invariant (net after set-aside >= subtotal) and that
  rounding only ever rounds *up*.
- Ran with no network access; no secrets, keys, or personal data in any file.

## Known gaps / honest limits

- Income tax reality is messier than one percent: self-employment tax,
  deductions, and brackets are all folded into your own `--tax` number. This is
  a planning floor, not a filing tool. (Not tax advice.)
- Materials are passed through at cost - add `--profit` if you want a margin on
  parts; there is no separate markup split yet.
- One currency only (whatever symbol format you type); no multi-currency.
- The tier library is fixed in code; custom percentages come via `--overhead`
  but there is no saved config file yet.
- Rate card has no PDF/HTML export; HTML could be added on top of the markdown.
- No `pyproject.toml`/pip packaging by design: it runs anywhere Python runs via
  `python3 -m pricefloor`. Add packaging if installation ergonomics matter.
