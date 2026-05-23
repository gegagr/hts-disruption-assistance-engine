"""CLI: generate the synthetic bookings dataset.

Usage::

    python -m src.cli.generate_data
"""
from __future__ import annotations

import sys

from src.config.loader import RegistryLoadError, load_registry
from src.data.generator import generate_dataset


def main() -> int:
    try:
        registry = load_registry()
    except RegistryLoadError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 3
    df = generate_dataset(registry)
    print(
        f"Generated {len(df):,} bookings across {df['partner_id'].nunique()} partners "
        f"({df['iso_week'].max() + 1} weeks)."
    )
    print(f"  Pre-split:  {(df['ab_arm'] == 'pre_split').sum():,}")
    print(f"  Control:    {(df['ab_arm'] == 'control').sum():,}")
    print(f"  Test:       {(df['ab_arm'] == 'test').sum():,}")
    print(f"  Ancillaries sold: {df['ancillary_purchased'].sum():,}")
    print(f"  Cancellations:    {df['cancelled'].sum():,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
