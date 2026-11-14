"""Write or verify FREEZE_MANIFEST.txt (SHA-256 of the plan, config,
prompts and code) — the freeze that precedes the main runs.

Usage:
  python scripts/freeze.py           # write the manifest
  python scripts/freeze.py --verify  # check the tree against it
"""

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

INCLUDE = ["PLAN.md", "config.yaml"]
INCLUDE_GLOBS = ["prompts/*.md", "src/linesim/*.py", "docs/engine.js",
                 "tests/*.py", "scripts/make_fixtures.py",
                 "tests/fixtures/agreement.json"]


def files() -> list[Path]:
    out = [ROOT / p for p in INCLUDE]
    for g in INCLUDE_GLOBS:
        out.extend(sorted(ROOT.glob(g)))
    return [p for p in out if p.exists()]


def digest(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> None:
    manifest = ROOT / "FREEZE_MANIFEST.txt"
    if "--verify" in sys.argv:
        recorded = {}
        for line in manifest.read_text().splitlines():
            if line.strip() and not line.startswith("#"):
                h, rel = line.split(None, 1)
                recorded[rel.strip()] = h
        bad = []
        for p in files():
            rel = str(p.relative_to(ROOT))
            if recorded.get(rel) != digest(p):
                bad.append(rel)
        if bad:
            print("MISMATCH:", *bad, sep="\n  ")
            sys.exit(1)
        print(f"freeze verified: {len(recorded)} files")
        return
    lines = ["# SHA-256 manifest, frozen before the main runs "
             "(see PLAN.md)."]
    for p in files():
        lines.append(f"{digest(p)}  {p.relative_to(ROOT)}")
    manifest.write_text("\n".join(lines) + "\n")
    print(f"wrote {manifest} ({len(lines) - 1} files)")


if __name__ == "__main__":
    main()
