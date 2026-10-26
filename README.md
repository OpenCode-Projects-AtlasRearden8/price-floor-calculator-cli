# pricefloor - what you must actually charge

A small-business CLI that answers the scariest question in freelance and LLC life:
**"What's the real price floor for this job?"**

You feed it your hourly rate goal, your LLC expense tier, a tax set-aside percent,
materials, and realistic hours per job. It hands back a price floor per service,
explains the math in plain English (like a friend would), compares flat vs hourly
quoting, prices a whole CSV of services at once, and exports a rate card.

Pure standard-library Python. Fully offline. No accounts, no network, no secrets.

Built by [Asdale Dynamics, LLC](https://dylanasdale.github.io) - Dylan Asdale's
project making AI and small-business tools understandable, step by step.
Pairs well with the companion ledger app **cashflow-simple-ledger**, which tracks
the money these jobs actually earn.

- License: MIT (see `LICENSE`)
- Status: planning-estimate tool. **Not tax advice.** Confirm your real rates and
  tax percentages with an accountant.

## Quick start

```bash
python3 -m pricefloor tiers

python3 -m pricefloor floor \
  --name "Handyman Small Repair" \
  --rate 50 --hours 3 --materials 40 \
  --tax 25 --tier standard \
  --annual-expenses 2400 --jobs-per-year 200

python3 -m pricefloor sample --out services.csv
python3 -m pricefloor batch --file services.csv --tax 25 --export-md ratecard.md
python3 -m pricefloor compare --rate 50 --hours 3 --tax 25
python3 -m pricefloor ratecard --file services.csv --format json --out ratecard.json
```

## How the floor is computed

```
labor            = hourly rate goal  x  hours per job
tier overhead    = labor x tier percent (see below)
fixed overhead   = annual fixed LLC costs / jobs per year   (optional)
profit padding   = (labor + overheads + materials) x profit percent   (optional)
subtotal         = labor + overheads + materials + profit          <- what you keep
price floor      = subtotal / (1 - tax set-aside)                  <- gross up for tax
quote            = price floor rounded UP to your --round-to step
```

The tax gross-up is exact: if you set aside 25% for taxes, the tool does not just
add 25% on top - it divides by 0.75, so that after the tax jar takes its share,
the subtotal is still yours. Rounding then *only ever rounds up*, so the quoted
price can never fall below the floor.

### LLC expense tiers

Tiers add overhead on top of labor, sized to how built-out the LLC is. Run
`python3 -m pricefloor tiers` to see live examples.

| Tier | Overhead | Covers |
|---|---|---|
| `micro` | 6% | side-gig LLC: phone plan, basic insurance, a few tools |
| `standard` | 12% | registered LLC: software, business banking, some marketing |
| `established` | 20% | growing LLC: office costs, bookkeeper, insurance, support tools |

No tier fits? Override it: `--overhead 15` (15% of labor).

## Commands

| Command | What it does |
|---|---|
| `floor` | Price floor for one service, with a numbered plain-English breakdown |
| `compare` | Flat-fee vs hourly quoting across an overrun ladder (`--overruns 0,25,50`) |
| `batch` | Price many services from CSV; optional `--export-md` / `--export-csv` |
| `ratecard` | Export a rate card: `--format md` (default), `csv`, or `json`; `--out FILE` |
| `sample` | Print (or `--out services.csv`) the sample CSV to start from |
| `tiers` | Show the LLC expense tiers with worked examples |

Every percentage flag (`--tax`, `--profit`, `--overhead`, and the `profit` CSV
column) is a plain percent: `25` means 25%, not 0.25.

### Service CSV format

Header row is required; common aliases are accepted (`name`, `hourly_rate`,
`hours_per_job`, `supplies`, `margin`, and so on).

```csv
service,rate,hours,materials,profit
Handyman Small Repair,55,2,35,10
Housecleaning Visit,40,3,15,5
```

Numbers can include `$` and `,` if you quote them: `"$1,200"`. Run the batch
with `--tax 25 --tier standard` etc. to apply business settings to every row.

## Flat vs hourly, in plain English

- **Flat quoting** rewards speed: finish early and you earned more per hour.
  But jobs that run over eat your margin. The safe cushion is roughly your
  overhead percent plus profit padding - `floor` and `compare` print your exact
  breakeven overrun so you know when to say no.
- **Hourly quoting** protects you when jobs drag on (extra hours still bill),
  but pays no bonus for working fast.

`compare` shows both side by side across a ladder of overruns: finish 20% early,
on schedule, then 25%, 50%, and 100% over. Use it to decide which quoting style
fits each kind of job.

## Development

```bash
python3 -m pytest -q          # run the test suite (72+ tests, pure stdlib)
python3 -m pricefloor --help  # full CLI reference
```

Repository layout:

```
pricefloor/core.py    # calculation engine (Decimal math, zero dependencies)
pricefloor/batch.py   # CSV loading + rate card builders (md/csv/json)
pricefloor/cli.py     # argparse commands and friendly output
tests/                # pytest suite: engine, CSV, and CLI end-to-end
sample_services.csv   # example input for `batch` / `ratecard`
```

## Credits

Made with plain-English intent by **Asdale Dynamics, LLC**
(Dylan Asdale - [dylanasdale.github.io](https://dylanasdale.github.io),
author of *The Massive AI Manual*).

Copyright (c) 2026 Asdale Dynamics, LLC. MIT licensed - see `LICENSE`.
