# Using Parfleche

Everything happens inside the `parfleche>` shell. Type `help` for the command
list, `help <command>` for full syntax plus examples, and `quit` (or Ctrl-D) to
leave. Arguments with spaces go in double quotes.

Cells are addressed as `<x> <y>`, zero-indexed, with `0 0` at the top-left corner.

## 1. Build a grid and paint it

```
parfleche> grid new 6 6
Created an empty 6x6 grid for project 'Untitled'. The cell grid is below; paint it with 'grid paint <x> <y> <pigment>'.
......
......
......
......
......
......
parfleche> pigments add ochre o "iron oxide, roasted to a red-brown"
Added pigment 'ochre' with symbol 'o'.
parfleche> grid paint 2 1 ochre
Painted 'ochre' at (2,1) as 'o'.
......
..o...
......
......
......
......
```

- `grid resize <w> <h>` keeps the overlapping cells in the top-left corner and
  clears anything that falls outside. It tells you how many painted cells it lost.
- `grid clear` empties every cell and reports how many it cleared.
- `grid erase <x> <y>` empties one cell ("was already empty" when nothing was there).
- `grid new <w> <h>` starts a fresh empty canvas **and keeps the pigment library**
  and project name, so you do not have to re-enter four recipes to change canvas size.

## 2. Mirror the motif

```
parfleche> grid paint 0 0 ochre
parfleche> mirror vertical
Mirrored vertically (left half onto the right): 1 cell changed.
o....o
......
......
......
......
......
```

- `mirror vertical` — left half reflected onto the right half.
- `mirror horizontal` — top half reflected onto the bottom half.
- `mirror both` — one quadrant reflected into all four quadrants.

Mirroring is destructive and in place, and always reports the number of cells it
changed (`0 cells changed` when the grid already matched). An odd width or height
keeps its middle row/column as the axis.

## 3. Keep the pigment library

```
parfleche> pigments add azurite a "azurite ground coarse, washed three times"
Added pigment 'azurite' with symbol 'a'.
parfleche> pigments list
o  ochre    iron oxide, roasted to a red-brown  [1 cell]
a  azurite  azurite ground coarse, washed three times  [0 cells]
parfleche> pigments remove azurite
Removed pigment 'azurite'.
```

A pigment is a unique name (duplicates are refused, case-insensitively), exactly
one non-space symbol (`.` is reserved for empty cells) and a free-text recipe.
A pigment that any cell uses cannot be removed: erase those cells first.

## 4. Export recipe cards

```
parfleche> export recipes ochre_cards.md
Wrote 1 recipe card to ochre_cards.md (project 'Untitled', 6x6).
```

The file is UTF-8 Markdown: an `# Parfleche Recipe Cards` heading carrying the
project name, grid size and export timestamp, then one `## <symbol> - <name>` card
per pigment that the grid actually uses, with its recipe. Unused pigments are left
out. An unusable path (missing directory, a directory, no permission, or a path that
resolves outside the directory Parfleche was started in) prints one line and
writes nothing.

## 5. Save and load a project

```
parfleche> project save blanket.json
Saved project 'Sixfold Chevron Blanket' to blanket.json (12x12, 4 pigments, 80 painted cells).
parfleche> project load blanket.json
Loaded project 'Sixfold Chevron Blanket' from blanket.json (12x12, 4 pigments).
```

Paths are always resolved inside the directory you started Parfleche from:
`blanket.json` and `field-notes/blanket.json` both work, `../elsewhere.json` and
`/tmp/elsewhere.json` are refused with `path is outside the working directory`.

The JSON holds `schema_version`, the project name, dimensions, `created_at`, the
pigment library and every cell, so the next session resumes exactly. Loading
validates before it touches memory: a missing file (`No such file: ...`), a broken
file (`JSON parse error ...`) or a newer schema (`unsupported schema_version ...`)
prints one line and leaves the loaded project exactly as it was.

## 6. Try the bundled example

```
parfleche> project load examples/parfleche-blanket.json
parfleche> grid show
....w.......
...w.a......
..w.aa......
.w.aao......
w.aaoo......
.aaook......
............
(...)
parfleche> mirror both
Mirrored on both axes (one quadrant into all four): 60 cells changed.
....w..w....
...w.aa.w...
..w.aaaa.w..
.w.aaooaa.w.
w.aaooooaa.w
.aaookkooaa.
.aaookkooaa.
w.aaooooaa.w
.w.aaooaa.w.
..w.aaaa.w..
...w.aa.w...
....w..w....
parfleche> export recipes blanket-cards.md
```

`bash demo.sh` runs that whole sequence non-interactively, including the export,
the save and a reload, and prints the generated Markdown.

## Errors

Every validation failure is one line, starts with `Error:`, and leaves the project
untouched — the shell never exits on a bad command:

```
parfleche> grid new 0 5
Error: grid dimensions must be between 1 and 64, got width 0
parfleche> grid paint 9 1 ochre
Error: (9,1) is outside the 6x6 grid; x runs 0-5 and y runs 0-5
parfleche> grid paint 1 1 blue
Error: unknown pigment 'blue'; known pigments: ochre
parfleche> bogus
Unknown command: bogus
Type 'help' for the command list.
parfleche> project save /tmp/blanket.json
Error: cannot save '/tmp/blanket.json': path is outside the working directory '/work'
```
