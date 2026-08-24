"""Group a flat 12-sublist batch folder into the published two-group layout.

`run_experiment.py run --use-sublists` writes its 12 sublist folders flat under
`results/<timestamp>_incoherent_sublists/`. The published run was afterwards
reorganized by hand into two design groups, and the group-level analysis
(`analyze_results.py plot`, which loads results recursively) is run per group:

  majority_incoherent/   01_coh-* .. 06_coh-*  (one boundary identity coherent)
  even_coherence_split/  07_coh-* .. 12_coh-*  (three coherent, three incoherent)

This script reproduces that step for a fresh batch run.

Usage:
  uv run python scripts/group_sublists.py results/<timestamp>_incoherent_sublists/
"""

import argparse
import re
import shutil
import sys
from pathlib import Path

GROUPS = {
    "majority_incoherent": range(1, 7),
    "even_coherence_split": range(7, 13),
}
SUBLIST_RE = re.compile(r"^(\d{2})_coh-")


def group_sublists(batch_dir: Path) -> None:
    sublist_dirs = {}
    for child in sorted(batch_dir.iterdir()):
        m = SUBLIST_RE.match(child.name)
        if child.is_dir() and m:
            sublist_dirs[int(m.group(1))] = child

    missing = sorted(set(range(1, 13)) - sublist_dirs.keys())
    if missing:
        sys.exit(
            f"{batch_dir} does not look like a flat 12-sublist batch folder "
            f"(missing sublists: {missing}). Already grouped?"
        )

    for group_name, indices in GROUPS.items():
        group_dir = batch_dir / group_name
        group_dir.mkdir(exist_ok=True)
        for i in indices:
            src = sublist_dirs[i]
            dest = group_dir / src.name
            if dest.exists():
                sys.exit(f"Refusing to overwrite existing {dest}")
            shutil.move(str(src), str(dest))
            print(f"  {src.name} -> {group_name}/")

    print(
        "\nDone. Group-level plots can now be generated per group, e.g.:\n"
        f"  uv run python scripts/analyze_results.py plot {batch_dir / 'majority_incoherent'} "
        "--type coherence-favourability"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("batch_dir", type=Path, help="Flat <timestamp>_incoherent_sublists folder")
    args = parser.parse_args()
    if not args.batch_dir.is_dir():
        sys.exit(f"Not a directory: {args.batch_dir}")
    group_sublists(args.batch_dir)


if __name__ == "__main__":
    main()
