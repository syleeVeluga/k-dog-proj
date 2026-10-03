"""Read-only extraction of the 2026-09-29 customer source into versioned catalogs; never imports responses."""

import argparse
from pathlib import Path

from .import_catalogs_v3 import CUSTOMER_DIR_V3, ROOT, extract_v3


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--customer-dir", type=Path, help="source folder (defaults to docs/큐브전달_20260929)")
    parser.add_argument("--check", action="store_true", help="compare existing JSON without writing")
    args = parser.parse_args()
    for name, content in extract_v3(args.customer_dir or CUSTOMER_DIR_V3).items():
        destination = ROOT / "resources" / name
        if args.check:
            if not destination.exists() or destination.read_text(encoding="utf-8") != content:
                raise ValueError(f"catalog is absent or differs from source: {name}")
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8", newline="\n")
        print(f"{name}: {'source verified' if args.check else 'extracted'}")


if __name__ == "__main__":
    main()
