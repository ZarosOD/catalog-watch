#!/usr/bin/env python3
"""Entry point. See `watch.py --help`, or the README."""

import sys

from catalog_watch.cli import main

if __name__ == "__main__":
    sys.exit(main())
