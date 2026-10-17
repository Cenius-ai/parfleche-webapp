#!/usr/bin/env bash
# Parfleche end-to-end demo: no prompts, no network, exits when it is done.
# It loads the bundled example project, mirrors the motif, exports recipe cards,
# saves the result and re-loads it, all through the real interactive shell.
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
    echo "demo: python3 is required (see INSTALL.md)" >&2
    exit 1
fi

# Artifacts stay inside the working directory (Parfleche never reads or writes
# outside the directory it was started in) and are removed when the demo ends.
out="demo-out"
rm -rf "$out"
mkdir -p "$out"
trap 'rm -rf "$out"' EXIT

echo "Parfleche demo - artifacts are written to $out"
echo

python3 parfleche.py <<EOF
help project
project load examples/parfleche-blanket.json
status
grid show
pigments list
mirror both
export recipes $out/recipe-cards.md
project save $out/blanket-session.json
grid new 4 3
grid paint 1 1 ochre
mirror vertical
grid erase 0 0
grid clear
pigments remove ochre
pigments add lapis l "azurite ground with hide glue"
pigments list
bogus
help mirror
quit
EOF

echo
echo "--- $out/recipe-cards.md ---"
cat "$out/recipe-cards.md"
echo
echo "--- saved project (first 24 lines of $out/blanket-session.json) ---"
head -n 24 "$out/blanket-session.json"
echo
echo "Demo complete."
