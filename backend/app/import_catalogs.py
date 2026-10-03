"""Read-only extraction of hash-verified customer sources; never imports responses."""

import argparse
from pathlib import Path

from .import_catalogs_v3 import CUSTOMER_DIR_V3, ROOT, extract_v3
from .import_catalogs_v4 import CUSTOMER_DIR_V4, extract_v4


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", choices=("20260929", "20261002"), default="20261002")
    parser.add_argument("--customer-dir", type=Path, help="local source folder for the selected edition")
    parser.add_argument("--check", action="store_true", help="compare existing JSON without writing")
    args = parser.parse_args()
    extractor, default_dir = (extract_v4, CUSTOMER_DIR_V4) if args.spec == "20261002" else (extract_v3, CUSTOMER_DIR_V3)
    for name, content in extractor(args.customer_dir or default_dir).items():
        destination = ROOT / "resources" / name
        if args.check:
            if not destination.exists() or destination.read_text(encoding="utf-8") != content:
                raise ValueError(f"catalog is absent or differs from source: {name}")
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8", newline="\n")
        print(f"{name}: {'source verified' if args.check else 'extracted'}")
    if args.spec == "20261002":
        print("G01/G04 input workbook: not received; physical address/formula verification pending; Excel import disabled")


if __name__ == "__main__":
    main()
