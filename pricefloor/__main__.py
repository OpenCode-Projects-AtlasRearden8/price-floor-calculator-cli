#!/usr/bin/env python3
"""Module entry point: python -m pricefloor."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
