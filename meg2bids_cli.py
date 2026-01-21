#!/usr/bin/env python3
"""Command-line entry point for meg2bids."""

import sys
from meg2bids.meg2bids import main

if __name__ == "__main__":
    sys.exit(main())
