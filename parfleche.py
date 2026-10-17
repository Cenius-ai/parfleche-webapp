#!/usr/bin/env python3
"""Parfleche - rawhide pattern grid builder with symmetric motif mirroring.

Parfleche is a single-file, standard-library-only command line tool.  Run it
with ``python3 parfleche.py`` to enter the ``parfleche>`` shell; ``--help``
prints the accepted arguments and ``--version`` the release.
"""

from __future__ import annotations

import argparse
import cmd
import json
import os
import shlex
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence

__version__ = "1.0.0"

SCHEMA_VERSION = 1
MIN_DIMENSION = 1
MAX_DIMENSION = 64
MAX_RECIPE_PREVIEW = 44
EMPTY_CELL = "."
UNTITLED = "Untitled"
PROMPT = "parfleche> "
RULE = "\u2500" * 62
MIRROR_AXES = ("vertical", "horizontal", "both")


class ParflecheError(Exception):
    """A user-facing validation or IO failure; the project stays untouched."""


# --------------------------------------------------------------------------
# Small shared helpers
# --------------------------------------------------------------------------
def utc_now_iso() -> str:
    """Current UTC timestamp, second precision, ISO-8601."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_int(raw: str, label: str) -> int:
    """Parse a whole number or raise a one-line ParflecheError."""
    try:
        return int(str(raw).strip(), 10)
    except (TypeError, ValueError):
        raise ParflecheError("{} must be a whole number, got '{}'".format(label, raw))


def parse_dimension(raw: str, label: str) -> int:
    """Parse a grid dimension, enforcing the 1-64 range."""
    value = parse_int(raw, label)
    if not MIN_DIMENSION <= value <= MAX_DIMENSION:
        raise ParflecheError(
            "grid dimensions must be between {} and {}, got {} {}".format(
                MIN_DIMENSION, MAX_DIMENSION, label, value
            )
        )
    return value


def validate_symbol(raw: object) -> str:
    """A pigment symbol is exactly one non-space character and not '.'."""
    if not isinstance(raw, str):
        raise ParflecheError("pigment symbol must be text, got {}".format(type(raw).__name__))
    if len(raw) != 1:
        raise ParflecheError(
            "pigment symbol must be exactly one character, got '{}' ({} characters)".format(
                raw, len(raw)
            )
        )
    if raw.isspace():
        raise ParflecheError("pigment symbol must not be a space")
    if raw == EMPTY_CELL:
        raise ParflecheError("pigment symbol '.' is reserved for empty cells")
    return raw


def validate_pigment_name(raw: object) -> str:
    """A pigment name is non-empty and free of whitespace-only content."""
    if not isinstance(raw, str):
        raise ParflecheError("pigment name must be text, got {}".format(type(raw).__name__))
    name = raw.strip()
    if not name:
        raise ParflecheError("pigment name must not be empty")
    if any(character.isspace() for character in name):
        return " ".join(name.split())
    return name


# --------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------
@dataclass
class Pigment:
    """One pigment in the library: a name, a one-character symbol, a recipe."""

    name: str
    symbol: str
    recipe: str = ""

    def to_dict(self) -> Dict[str, str]:
        return {"name": self.name, "symbol": self.symbol, "recipe": self.recipe}

    @classmethod
    def from_dict(cls, data: object) -> "Pigment":
        if not isinstance(data, dict):
            raise ParflecheError("each pigment in the project file must be a JSON object")
        if "name" not in data or "symbol" not in data:
            raise ParflecheError("each pigment in the project file needs 'name' and 'symbol'")
        name = validate_pigment_name(data["name"])
        symbol = validate_symbol(data["symbol"])
        recipe = data.get("recipe", "")
        if not isinstance(recipe, str):
            raise ParflecheError("recipe for pigment '{}' must be text".format(name))
        return cls(name=name, symbol=symbol, recipe=recipe)


@dataclass
class Project:
    """A parfleche project: the grid, the pigment library and the metadata."""

    name: str = UNTITLED
    width: int = 0
    height: int = 0
    cells: List[List[Optional[str]]] = field(default_factory=list)
    pigments: List[Pigment] = field(default_factory=list)
    schema_version: int = SCHEMA_VERSION
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.cells:
            self.cells = [[None] * self.width for _ in range(self.height)]
        else:
            # Own the rows: mirror/resize must never write through a caller's list.
            self.cells = [list(row) for row in self.cells]
        if not self.created_at:
            self.created_at = utc_now_iso()

    # -- pigments ---------------------------------------------------------
    def pigment(self, name: str) -> Pigment:
        """Look a pigment up by name; exact match first, then case-insensitive."""
        wanted = str(name).strip()
        for item in self.pigments:
            if item.name == wanted:
                return item
        folded = wanted.casefold()
        for item in self.pigments:
            if item.name.casefold() == folded:
                return item
        known = ", ".join(sorted(item.name for item in self.pigments)) or "none yet"
        raise ParflecheError("unknown pigment '{}'; known pigments: {}".format(name, known))

    def add_pigment(self, name: str, symbol: str, recipe: str) -> Pigment:
        clean_name = validate_pigment_name(name)
        clean_symbol = validate_symbol(symbol)
        folded = clean_name.casefold()
        for item in self.pigments:
            if item.name.casefold() == folded:
                raise ParflecheError(
                    "pigment '{}' already exists; remove it first or pick another name".format(
                        item.name
                    )
                )
        pigment = Pigment(name=clean_name, symbol=clean_symbol, recipe=str(recipe).strip())
        self.pigments.append(pigment)
        return pigment

    def remove_pigment(self, name: str) -> Pigment:
        pigment = self.pigment(name)
        used = self.usage_counts().get(pigment.name, 0)
        if used:
            raise ParflecheError(
                "pigment '{}' is used by {} cell{}; erase those cells before removing it".format(
                    pigment.name, used, "" if used == 1 else "s"
                )
            )
        self.pigments = [item for item in self.pigments if item is not pigment]
        return pigment

    def symbols(self) -> Dict[str, str]:
        return {item.name: item.symbol for item in self.pigments}

    def usage_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for row in self.cells:
            for cell in row:
                if cell is not None:
                    counts[cell] = counts.get(cell, 0) + 1
        return counts

    def painted_count(self) -> int:
        return sum(1 for row in self.cells for cell in row if cell is not None)

    def pigments_in_use(self) -> List[Pigment]:
        """Pigments that appear in the grid, in reading order of first use."""
        seen: List[str] = []
        for row in self.cells:
            for cell in row:
                if cell is not None and cell not in seen:
                    seen.append(cell)
        by_name = {item.name: item for item in self.pigments}
        return [by_name[name] for name in seen if name in by_name]

    # -- grid -------------------------------------------------------------
    def check_bounds(self, x: int, y: int) -> None:
        if not 0 <= x < self.width or not 0 <= y < self.height:
            raise ParflecheError(
                "({},{}) is outside the {}x{} grid; x runs 0-{} and y runs 0-{}".format(
                    x, y, self.width, self.height, self.width - 1, self.height - 1
                )
            )

    def paint(self, x: int, y: int, pigment_name: str) -> str:
        self.check_bounds(x, y)
        pigment = self.pigment(pigment_name)
        self.cells[y][x] = pigment.name
        return pigment.name

    def erase(self, x: int, y: int) -> Optional[str]:
        self.check_bounds(x, y)
        previous = self.cells[y][x]
        self.cells[y][x] = None
        return previous

    def clear(self) -> int:
        cleared = self.painted_count()
        self.cells = [[None] * self.width for _ in range(self.height)]
        return cleared

    def resize(self, width: int, height: int) -> None:
        if not MIN_DIMENSION <= width <= MAX_DIMENSION:
            raise ParflecheError(
                "grid dimensions must be between {} and {}, got width {}".format(
                    MIN_DIMENSION, MAX_DIMENSION, width
                )
            )
        if not MIN_DIMENSION <= height <= MAX_DIMENSION:
            raise ParflecheError(
                "grid dimensions must be between {} and {}, got height {}".format(
                    MIN_DIMENSION, MAX_DIMENSION, height
                )
            )
        resized: List[List[Optional[str]]] = [[None] * width for _ in range(height)]
        for y in range(min(height, self.height)):
            for x in range(min(width, self.width)):
                resized[y][x] = self.cells[y][x]
        self.cells = resized
        self.width = width
        self.height = height

    def mirror(self, axis: str) -> int:
        """Reflect the motif across one or both axes in place; return cells changed."""
        if axis not in MIRROR_AXES:
            raise ParflecheError(
                "unknown mirror axis '{}'; choose vertical, horizontal, or both".format(axis)
            )
        source = [list(row) for row in self.cells]
        mirror_x = axis in ("vertical", "both")
        mirror_y = axis in ("horizontal", "both")
        changed = 0
        for y in range(self.height):
            if mirror_y:
                source_y = y if y < self.height // 2 else self.height - 1 - y
            else:
                source_y = y
            for x in range(self.width):
                if mirror_x:
                    source_x = x if x < self.width // 2 else self.width - 1 - x
                else:
                    source_x = x
                value = source[source_y][source_x]
                if self.cells[y][x] != value:
                    self.cells[y][x] = value
                    changed += 1
        return changed

    def render(self) -> List[str]:
        """Plain ASCII rows: one symbol per pigment, '.' for empty cells."""
        symbols = self.symbols()
        rows = []
        for row in self.cells:
            rows.append(
                "".join(symbols.get(cell, "?") if cell is not None else EMPTY_CELL for cell in row)
            )
        return rows


# --------------------------------------------------------------------------
# JSON codec
# --------------------------------------------------------------------------
def _load_dimension(data: Dict[str, object], key: str) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ParflecheError("project file needs an integer '{}'".format(key))
    if not MIN_DIMENSION <= value <= MAX_DIMENSION:
        raise ParflecheError(
            "project file '{}' must be between {} and {}, got {}".format(
                key, MIN_DIMENSION, MAX_DIMENSION, value
            )
        )
    return value


def project_to_dict(project: Project) -> Dict[str, object]:
    return {
        "schema_version": project.schema_version,
        "name": project.name,
        "width": project.width,
        "height": project.height,
        "created_at": project.created_at,
        "pigments": [pigment.to_dict() for pigment in project.pigments],
        "cells": [list(row) for row in project.cells],
    }


def project_from_dict(data: object) -> Project:
    """Validate a decoded JSON document into a Project, or raise ParflecheError."""
    if not isinstance(data, dict):
        raise ParflecheError("project file must contain a JSON object")
    schema_version = data.get("schema_version")
    if isinstance(schema_version, bool) or not isinstance(schema_version, int):
        raise ParflecheError("project file is missing an integer 'schema_version'")
    if schema_version != SCHEMA_VERSION:
        raise ParflecheError(
            "unsupported schema_version {}; this build reads version {}".format(
                schema_version, SCHEMA_VERSION
            )
        )
    name = data.get("name", UNTITLED)
    if not isinstance(name, str) or not name.strip():
        raise ParflecheError("project file has an invalid 'name'")
    width = _load_dimension(data, "width")
    height = _load_dimension(data, "height")

    pigments_raw = data.get("pigments", [])
    if not isinstance(pigments_raw, list):
        raise ParflecheError("project file 'pigments' must be a list")
    pigments = [Pigment.from_dict(entry) for entry in pigments_raw]
    seen = set()
    for pigment in pigments:
        folded = pigment.name.casefold()
        if folded in seen:
            raise ParflecheError("project file lists pigment '{}' twice".format(pigment.name))
        seen.add(folded)

    cells_raw = data.get("cells")
    if not isinstance(cells_raw, list):
        raise ParflecheError("project file needs a 'cells' list")
    if len(cells_raw) != height:
        raise ParflecheError(
            "project file 'cells' has {} rows but height is {}".format(len(cells_raw), height)
        )
    known = {pigment.name for pigment in pigments}
    cells: List[List[Optional[str]]] = []
    for row_index, row in enumerate(cells_raw):
        if not isinstance(row, list):
            raise ParflecheError("project file row {} must be a list".format(row_index))
        if len(row) != width:
            raise ParflecheError(
                "project file row {} has {} cells but width is {}".format(
                    row_index, len(row), width
                )
            )
        clean_row: List[Optional[str]] = []
        for column_index, cell in enumerate(row):
            if cell is None:
                clean_row.append(None)
                continue
            if not isinstance(cell, str):
                raise ParflecheError(
                    "cell ({},{}) must be a pigment name or null".format(column_index, row_index)
                )
            if cell not in known:
                raise ParflecheError(
                    "cell ({},{}) references unknown pigment '{}'".format(
                        column_index, row_index, cell
                    )
                )
            clean_row.append(cell)
        cells.append(clean_row)

    created_at = data.get("created_at", "")
    if not isinstance(created_at, str):
        raise ParflecheError("project file 'created_at' must be text")

    project = Project(
        name=name,
        width=width,
        height=height,
        cells=cells,
        pigments=pigments,
        schema_version=schema_version,
        created_at=created_at or utc_now_iso(),
    )
    return project


# --------------------------------------------------------------------------
# File IO
#
# Every path a user types is untrusted text.  It is resolved once, against the
# single fixed base directory (the workspace Parfleche was started in), and any
# resolved form that escapes that base - ``../../etc/passwd``, an absolute path
# elsewhere, or a symlink pointing out of the tree - is refused before a single
# filesystem call happens.  The sinks re-check the same rule, so no user string
# can steer a read or a write outside the workspace.
# --------------------------------------------------------------------------
def workspace_root() -> Path:
    """The one directory Parfleche reads and writes inside: where it was started."""
    return Path.cwd().resolve()


def _inside_workspace(candidate: Path, root: Path) -> bool:
    """True when candidate is root itself or sits underneath it (no symlink escapes)."""
    return candidate == root or root in candidate.parents


def confine_path(raw_path: str, action: str) -> Path:
    """Resolve a user-supplied path inside the workspace, or raise ParflecheError."""
    cleaned = str(raw_path).strip()
    if not cleaned:
        raise ParflecheError("a file path is required")
    if "\x00" in cleaned:
        raise ParflecheError("cannot {} '{}': the path contains a null byte".format(action, cleaned))
    root = workspace_root()
    try:
        candidate = (root / Path(cleaned).expanduser()).resolve()
    except OSError as exc:
        raise ParflecheError("cannot {} '{}': {}".format(action, cleaned, exc.strerror or exc))
    if not _inside_workspace(candidate, root):
        raise ParflecheError(
            "cannot {} '{}': path is outside the working directory '{}'".format(
                action, cleaned, root
            )
        )
    return candidate


def resolve_write_path(raw_path: str, action: str) -> Path:
    """Return a confined, writable path, or raise a one-line ParflecheError."""
    cleaned = str(raw_path).strip()
    path = confine_path(cleaned, action)
    parent = path.parent
    if not parent.exists():
        raise ParflecheError(
            "cannot {} '{}': directory '{}' does not exist".format(action, cleaned, parent)
        )
    if not parent.is_dir():
        raise ParflecheError(
            "cannot {} '{}': '{}' is not a directory".format(action, cleaned, parent)
        )
    if path.is_dir():
        raise ParflecheError("cannot {} '{}': it is a directory".format(action, cleaned))
    return path


def resolve_read_path(raw_path: str, action: str) -> Path:
    """Return a confined, existing, readable path, or raise a one-line ParflecheError."""
    cleaned = str(raw_path).strip()
    path = confine_path(cleaned, action)
    if not path.exists():
        raise ParflecheError("No such file: {}".format(cleaned))
    if path.is_dir():
        raise ParflecheError("cannot {} '{}': it is a directory".format(action, cleaned))
    return path


def write_text(path: Path, text: str, raw_path: str, action: str) -> None:
    root = workspace_root()
    if not _inside_workspace(path.resolve(), root):
        raise ParflecheError(
            "cannot {} '{}': path is outside the working directory '{}'".format(
                action, raw_path, root
            )
        )
    try:
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    except OSError as exc:
        reason = exc.strerror or str(exc)
        raise ParflecheError("cannot {} '{}': {}".format(action, raw_path, reason))


def read_text(path: Path, raw_path: str, action: str) -> str:
    root = workspace_root()
    if not _inside_workspace(path.resolve(), root):
        raise ParflecheError(
            "cannot {} '{}': path is outside the working directory '{}'".format(
                action, raw_path, root
            )
        )
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise ParflecheError(
            "cannot {} '{}': the file is not valid UTF-8 text".format(action, raw_path)
        )
    except OSError as exc:
        reason = exc.strerror or str(exc)
        raise ParflecheError("cannot {} '{}': {}".format(action, raw_path, reason))


def save_project(project: Project, raw_path: str) -> Path:
    path = resolve_write_path(raw_path, "save")
    payload = json.dumps(project_to_dict(project), indent=2, ensure_ascii=False) + "\n"
    write_text(path, payload, raw_path, "save")
    return path


def load_project(raw_path: str) -> Project:
    path = resolve_read_path(raw_path, "load")
    text = read_text(path, raw_path, "load")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ParflecheError(
            "JSON parse error in '{}' at line {} column {}: {}".format(
                raw_path, exc.lineno, exc.colno, exc.msg
            )
        )
    return project_from_dict(data)


def render_recipe_cards(project: Project, timestamp: Optional[str] = None) -> str:
    """Markdown recipe cards for the pigments the grid actually uses."""
    used = project.pigments_in_use()
    if not used:
        raise ParflecheError(
            "nothing to export: no pigment is painted on the grid yet; "
            "use 'grid paint <x> <y> <pigment>' first"
        )
    usage = project.usage_counts()
    lines = [
        "# Parfleche Recipe Cards",
        "",
        "- **Project:** {}".format(project.name),
        "- **Grid:** {}x{}".format(project.width, project.height),
        "- **Exported:** {}".format(timestamp or utc_now_iso()),
        "- **Pigments used:** {}".format(len(used)),
        "",
    ]
    for pigment in used:
        cell_count = usage.get(pigment.name, 0)
        lines.extend(
            [
                "---",
                "",
                "## {} - {}".format(pigment.symbol, pigment.name),
                "",
                "- **Symbol:** `{}`".format(pigment.symbol),
                "- **Cells painted:** {}".format(cell_count),
                "",
                "### Recipe",
                "",
                pigment.recipe.strip() or "_No recipe recorded._",
                "",
            ]
        )
    return "\n".join(lines).rstrip("\n") + "\n"


def export_recipe_cards(project: Project, raw_path: str) -> tuple:
    path = resolve_write_path(raw_path, "export")
    markdown = render_recipe_cards(project)
    write_text(path, markdown, raw_path, "export")
    return path, len(project.pigments_in_use())


# --------------------------------------------------------------------------
# Help text
# --------------------------------------------------------------------------
HELP_TOPICS: Dict[str, str] = {
    "grid": """Grid - build and edit the rawhide pattern grid
  Cells are addressed as <x> <y> with 0 0 at the top-left corner.
  '.' is an empty cell; every pigment shows as its one-character symbol.

  grid new <width> <height>      start an empty grid, 1-64 on each side
  grid show                      draw the grid as plain ASCII
  grid resize <width> <height>   resize, keeping overlapping cells top-left
  grid clear                     empty every cell
  grid paint <x> <y> <pigment>   paint one cell with a library pigment
  grid erase <x> <y>             erase one cell

Examples
  grid new 6 6
  grid paint 0 0 ochre
  grid erase 5 5
  grid resize 8 8
  grid clear""",
    "pigments": """Pigments - the pigment library behind the grid
  A pigment has a unique name, a one-character symbol and a recipe note.

  pigments add <name> <symbol> <recipe>   add a pigment (quote the recipe)
  pigments list                           symbol, name and recipe preview
  pigments remove <name>                  remove an unused pigment

Examples
  pigments add ochre o "iron oxide, roasted to a red earth"
  pigments add lapis l "azurite ground with hide glue"
  pigments list
  pigments remove lapis""",
    "mirror": """Mirror - reflect the motif across the grid axes
  Destructive and in place: the grid is rewritten, then the number of
  changed cells is reported.

  axis        effect                                          example
  vertical    left half reflected onto the right half          mirror vertical
  horizontal  top half reflected onto the bottom half          mirror horizontal
  both        one quadrant reflected into all four quadrants   mirror both

Examples
  mirror vertical
  mirror horizontal
  mirror both""",
    "export": """Export - write Markdown pigment recipe cards
  One H2 card per pigment the grid actually uses, with a heading carrying
  the project name, the grid size and the export timestamp.

  export recipes <path.md>

Examples
  export recipes ochre_cards.md
  export recipes field-notes/blanket-2024.md""",
    "project": """Project - save and load the whole project as JSON
  The file holds the schema version, project name, dimensions, pigment
  library and every cell, so a session resumes exactly where it stopped.

  project save <path.json>
  project load <path.json>

Examples
  project save blanket.json
  project load examples/parfleche-blanket.json""",
    "status": """Status - one glance at the current project
  Shows the project name, the grid dimensions, the pigment count and how
  many cells are painted. With no project loaded it says so and points at
  'grid new <width> <height>' or 'project load <path>'.

Examples
  status""",
    "help": """Help - the command list, or one command in detail
  help               list every command
  help <command>     full syntax and examples for one command

Examples
  help
  help grid""",
    "quit": """Quit - leave the shell cleanly
  Prints 'Goodbye.' and exits with status 0. Ctrl-D at the prompt does the
  same thing.

Examples
  quit""",
}

COMPONENT_ALIASES = {
    "grids": "grid",
    "pigment": "pigments",
    "mirrors": "mirror",
    "exports": "export",
    "projects": "project",
    "status": "status",
}

COMMAND_SUMMARY = [
    ("grid", "create, show, resize, clear, paint and erase cells"),
    ("pigments", "add, list and remove pigments"),
    ("mirror", "mirror the motif vertical, horizontal or both"),
    ("export", "write Markdown recipe cards for the pigments in use"),
    ("project", "save or load the whole project as JSON"),
    ("status", "project name, grid dimensions and pigment count"),
    ("help", "command list, or 'help <command>' for details"),
    ("quit", "leave the shell (Ctrl-D works too)"),
]

BANNER = "\n".join(
    [
        "Parfleche {} - rawhide pattern grids, motif mirroring, recipe cards".format(__version__),
        RULE,
        "Type 'help' for the command list, or 'help grid' for grid syntax.",
    ]
)


# --------------------------------------------------------------------------
# Interactive shell
# --------------------------------------------------------------------------
class ParflecheShell(cmd.Cmd):
    """Line-oriented shell: every command validates before it mutates state."""

    intro = BANNER

    def __init__(self, stdin=None, stdout=None) -> None:
        super().__init__(stdin=stdin, stdout=stdout)
        self.project: Optional[Project] = None
        interactive = False
        try:
            interactive = bool(self.stdin.isatty())
        except (AttributeError, ValueError):
            interactive = False
        self.use_rawinput = interactive and self.stdin is sys.stdin
        self.prompt = PROMPT if self.use_rawinput else ""
        self._echo_commands = not self.use_rawinput

    # -- plumbing ---------------------------------------------------------
    def say(self, text: str = "") -> None:
        self.stdout.write(text + "\n")

    def onecmd(self, line: str) -> bool:
        stripped = line.strip()
        if self._echo_commands and stripped:
            self.say("{}{}".format(PROMPT, stripped))
        if not stripped:
            return False
        try:
            argv = shlex.split(stripped)
        except ValueError as exc:
            self.say(
                "Error: cannot parse the command line ({}); wrap arguments "
                "containing spaces in double quotes".format(exc)
            )
            return False
        verb, arguments = argv[0].lower(), argv[1:]
        if verb == "eof":
            self.say("Goodbye.")
            return True
        handler = {
            "help": self._cmd_help,
            "status": self._cmd_status,
            "quit": self._cmd_quit,
            "exit": self._cmd_quit,
            "grid": self._cmd_grid,
            "pigments": self._cmd_pigments,
            "mirror": self._cmd_mirror,
            "export": self._cmd_export,
            "project": self._cmd_project,
        }.get(verb)
        if handler is None:
            self.say("Unknown command: {}".format(argv[0]))
            self.say("Type 'help' for the command list.")
            return False
        try:
            return bool(handler(arguments))
        except ParflecheError as exc:
            self.say("Error: {}".format(exc))
            return False

    def emptyline(self) -> bool:
        return False

    # -- helpers ----------------------------------------------------------
    def require_project(self) -> Project:
        if self.project is None:
            raise ParflecheError(
                "no project loaded; start with 'grid new <width> <height>' "
                "or 'project load <path>'"
            )
        return self.project

    def show_grid(self) -> None:
        project = self.require_project()
        for row in project.render():
            self.say(row)

    def usage_error(self, usage: str) -> None:
        self.say("Error: missing or extra arguments; usage: {}".format(usage))

    # -- commands ---------------------------------------------------------
    def _cmd_help(self, arguments: Sequence[str]) -> bool:
        if not arguments:
            self.say(RULE)
            self.say("Parfleche {} - commands".format(__version__))
            self.say(RULE)
            width = max(len(name) for name, _ in COMMAND_SUMMARY)
            for name, summary in COMMAND_SUMMARY:
                self.say("  {:<{}}  {}".format(name, width, summary))
            self.say("")
            self.say("Examples")
            self.say("  grid new 6 6")
            self.say('  pigments add ochre o "iron oxide, roasted"')
            self.say("  grid paint 0 0 ochre")
            self.say("  mirror both")
            self.say("  export recipes ochre_cards.md")
            self.say("")
            self.say("Type 'help <command>' for the full syntax of one command.")
            return False
        topic = arguments[0].lower().rstrip(".")
        topic = COMPONENT_ALIASES.get(topic, topic)
        text = HELP_TOPICS.get(topic)
        if text is None:
            self.say("No help for '{}'. Type 'help' for the command list.".format(arguments[0]))
            return False
        self.say(RULE)
        self.say(text)
        return False

    def _cmd_status(self, arguments: Sequence[str]) -> bool:
        if arguments:
            self.usage_error("status")
            return False
        if self.project is None:
            self.say("No project loaded. Start with 'grid new <width> <height>' "
                     "or 'project load <path>'.")
            return False
        project = self.project
        pigments = len(project.pigments)
        used = len(project.pigments_in_use())
        self.say("Project:  {}".format(project.name))
        self.say("Grid:     {}x{} ({} cells)".format(project.width, project.height,
                                                    project.width * project.height))
        self.say("Pigments: {} ({} in use)".format(pigments, used))
        self.say("Painted:  {} of {} cells".format(project.painted_count(),
                                                   project.width * project.height))
        return False

    def _cmd_quit(self, arguments: Sequence[str]) -> bool:
        if arguments:
            self.usage_error("quit")
            return False
        self.say("Goodbye.")
        return True

    def _cmd_grid(self, arguments: Sequence[str]) -> bool:
        usage = ("grid new <width> <height> | grid show | grid resize <width> <height> | "
                 "grid clear | grid paint <x> <y> <pigment> | grid erase <x> <y>")
        if not arguments:
            self.usage_error(usage)
            return False
        action = arguments[0].lower()
        rest = list(arguments[1:])
        if action in ("new", "create"):
            return self._grid_new(rest, usage)
        if action in ("show", "draw", "render"):
            if rest:
                self.usage_error("grid show")
                return False
            self.show_grid()
            return False
        if action == "resize":
            return self._grid_resize(rest, usage)
        if action == "clear":
            return self._grid_clear(rest)
        if action == "paint":
            return self._grid_paint(rest, usage)
        if action == "erase":
            return self._grid_erase(rest, usage)
        self.say("Unknown command: grid {}".format(arguments[0]))
        self.say("Usage: {}".format(usage))
        return False

    def _grid_new(self, arguments: List[str], usage: str) -> bool:
        if len(arguments) != 2:
            self.usage_error(usage)
            return False
        width = parse_dimension(arguments[0], "width")
        height = parse_dimension(arguments[1], "height")
        if self.project is None:
            self.project = Project(name=UNTITLED, width=width, height=height)
        else:
            # Keep the pigment library and the project name: only the canvas resets.
            self.project.cells = [[None] * width for _ in range(height)]
            self.project.width = width
            self.project.height = height
        self.say("Created an empty {}x{} grid for project '{}'. The cell grid is below; "
                 "paint it with 'grid paint <x> <y> <pigment>'.".format(
                     width, height, self.project.name))
        self.show_grid()
        return False

    def _grid_resize(self, arguments: List[str], usage: str) -> bool:
        if len(arguments) != 2:
            self.usage_error(usage)
            return False
        width = parse_dimension(arguments[0], "width")
        height = parse_dimension(arguments[1], "height")
        project = self.require_project()
        before = project.painted_count()
        project.resize(width, height)
        self.say("Resized the grid to {}x{}; {} painted cell{} kept in the top-left.".format(
            width, height, project.painted_count(), "" if project.painted_count() == 1 else "s"))
        if project.painted_count() < before:
            self.say("{} painted cell{} fell outside the new grid and {} cleared.".format(
                before - project.painted_count(),
                "" if before - project.painted_count() == 1 else "s",
                "was" if before - project.painted_count() == 1 else "were"))
        self.show_grid()
        return False

    def _grid_clear(self, arguments: List[str]) -> bool:
        if arguments:
            self.usage_error("grid clear")
            return False
        project = self.require_project()
        cleared = project.clear()
        self.say("Cleared {} painted cell{}.".format(cleared, "" if cleared == 1 else "s"))
        self.show_grid()
        return False

    def _grid_paint(self, arguments: List[str], usage: str) -> bool:
        if len(arguments) != 3:
            self.usage_error(usage)
            return False
        x = parse_int(arguments[0], "x")
        y = parse_int(arguments[1], "y")
        project = self.require_project()
        pigment_name = project.paint(x, y, arguments[2])
        symbol = project.symbols()[pigment_name]
        self.say("Painted '{}' at ({},{}) as '{}'.".format(pigment_name, x, y, symbol))
        self.show_grid()
        return False

    def _grid_erase(self, arguments: List[str], usage: str) -> bool:
        if len(arguments) != 2:
            self.usage_error(usage)
            return False
        x = parse_int(arguments[0], "x")
        y = parse_int(arguments[1], "y")
        project = self.require_project()
        previous = project.erase(x, y)
        if previous is None:
            self.say("Cell ({},{}) was already empty.".format(x, y))
        else:
            self.say("Erased '{}' at ({},{}).".format(previous, x, y))
        self.show_grid()
        return False

    def _cmd_mirror(self, arguments: Sequence[str]) -> bool:
        usage = "mirror vertical | mirror horizontal | mirror both"
        rest = [value.lower() for value in arguments]
        if rest and rest[0] == "apply":
            rest = rest[1:]
        if len(rest) != 1:
            self.usage_error(usage)
            return False
        axis = rest[0]
        project = self.require_project()
        changed = project.mirror(axis)
        labels = {
            "vertical": "Mirrored vertically (left half onto the right)",
            "horizontal": "Mirrored horizontally (top half onto the bottom)",
            "both": "Mirrored on both axes (one quadrant into all four)",
        }
        self.say("{}: {} cell{} changed.".format(
            labels[axis], changed, "" if changed == 1 else "s"))
        if changed == 0:
            self.say("The grid already matched its mirror; nothing moved.")
        self.show_grid()
        return False

    def _cmd_pigments(self, arguments: Sequence[str]) -> bool:
        usage = ("pigments add <name> <symbol> <recipe> | pigments list | "
                 "pigments remove <name>")
        if not arguments:
            self.usage_error(usage)
            return False
        action = arguments[0].lower()
        rest = list(arguments[1:])
        if action == "add":
            return self._pigments_add(rest, usage)
        if action in ("list", "show"):
            return self._pigments_list(rest)
        if action in ("remove", "rm", "delete"):
            return self._pigments_remove(rest, usage)
        self.say("Unknown command: pigments {}".format(arguments[0]))
        self.say("Usage: {}".format(usage))
        return False

    def _pigments_add(self, arguments: List[str], usage: str) -> bool:
        if len(arguments) < 2:
            self.usage_error(usage)
            return False
        name, symbol = arguments[0], arguments[1]
        recipe = " ".join(arguments[2:]).strip()
        project = self.require_project()
        pigment = project.add_pigment(name, symbol, recipe)
        self.say("Added pigment '{}' with symbol '{}'.".format(pigment.name, pigment.symbol))
        if not pigment.recipe:
            self.say("Tip: add a recipe with the same command, for example "
                     'pigments add {} {} "ground pigment in hide glue"'.format(
                         pigment.name, pigment.symbol))
        return False

    def _pigments_list(self, arguments: List[str]) -> bool:
        if arguments:
            self.usage_error("pigments list")
            return False
        project = self.require_project()
        if not project.pigments:
            self.say("No pigments yet. Add one with: "
                     'pigments add ochre o "iron oxide, roasted"')
            return False
        usage = project.usage_counts()
        name_width = max(len(pigment.name) for pigment in project.pigments)
        for pigment in project.pigments:
            preview = " ".join(pigment.recipe.split())
            if not preview:
                preview = "(no recipe recorded)"
            if len(preview) > MAX_RECIPE_PREVIEW:
                preview = preview[: MAX_RECIPE_PREVIEW - 3].rstrip() + "..."
            cells = usage.get(pigment.name, 0)
            marker = "{} cell{}".format(cells, "" if cells == 1 else "s")
            self.say("{}  {:<{}}  {}  [{}]".format(
                pigment.symbol, pigment.name, name_width, preview, marker))
        return False

    def _pigments_remove(self, arguments: List[str], usage: str) -> bool:
        if len(arguments) != 1:
            self.usage_error(usage)
            return False
        project = self.require_project()
        pigment = project.remove_pigment(arguments[0])
        self.say("Removed pigment '{}'.".format(pigment.name))
        return False

    def _cmd_project(self, arguments: Sequence[str]) -> bool:
        usage = "project save <path.json> | project load <path.json>"
        if not arguments:
            self.usage_error(usage)
            return False
        action = arguments[0].lower()
        rest = list(arguments[1:])
        if action == "save":
            if len(rest) != 1:
                self.usage_error("project save <path.json>")
                return False
            project = self.require_project()
            save_project(project, rest[0])
            self.say("Saved project '{}' to {} ({}x{}, {} pigment{}, {} painted cell{}).".format(
                project.name, rest[0], project.width, project.height,
                len(project.pigments), "" if len(project.pigments) == 1 else "s",
                project.painted_count(), "" if project.painted_count() == 1 else "s"))
            return False
        if action == "load":
            if len(rest) != 1:
                self.usage_error("project load <path.json>")
                return False
            loaded = load_project(rest[0])
            self.project = loaded
            self.say("Loaded project '{}' from {} ({}x{}, {} pigment{}).".format(
                loaded.name, rest[0], loaded.width, loaded.height,
                len(loaded.pigments), "" if len(loaded.pigments) == 1 else "s"))
            self.show_grid()
            return False
        self.say("Unknown command: project {}".format(arguments[0]))
        self.say("Usage: {}".format(usage))
        return False

    def _cmd_export(self, arguments: Sequence[str]) -> bool:
        usage = "export recipes <path.md>"
        if not arguments:
            self.usage_error(usage)
            return False
        if arguments[0].lower() != "recipes":
            self.say("Unknown command: export {}".format(arguments[0]))
            self.say("Usage: {}".format(usage))
            return False
        rest = list(arguments[1:])
        if len(rest) != 1:
            self.usage_error(usage)
            return False
        project = self.require_project()
        _, cards = export_recipe_cards(project, rest[0])
        self.say("Wrote {} recipe card{} to {} (project '{}', {}x{}).".format(
            cards, "" if cards == 1 else "s", rest[0], project.name,
            project.width, project.height))
        return False


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="parfleche",
        description=(
            "Rawhide pattern grid builder: lay out a pigment grid, mirror the motif "
            "across the vertical and horizontal axes, and export Markdown pigment "
            "recipe cards. Starts the interactive 'parfleche>' shell."
        ),
        epilog=(
            "examples:\n"
            "  python3 parfleche.py\n"
            "  python3 parfleche.py --version\n\n"
            "inside the shell:\n"
            "  grid new 6 6\n"
            '  pigments add ochre o "iron oxide, roasted"\n'
            "  grid paint 0 0 ochre\n"
            "  mirror both\n"
            "  export recipes ochre_cards.md\n"
            "  project save blanket.json\n"
            "  quit"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version="parfleche {}".format(__version__),
        help="print the release and exit",
    )
    return parser


def _silence_stdout() -> None:
    """Point stdout at /dev/null so the interpreter's last flush cannot raise."""
    try:
        null_fd = os.open(os.devnull, os.O_WRONLY)
        os.dup2(null_fd, sys.stdout.fileno())
    except (OSError, ValueError):
        pass


def main(argv: Optional[Sequence[str]] = None) -> int:
    build_parser().parse_args(argv)
    shell = ParflecheShell()
    try:
        shell.cmdloop()
    except KeyboardInterrupt:
        sys.stdout.write("\nGoodbye.\n")
        return 0
    except BrokenPipeError:
        # A reader closed the pipe (e.g. `parfleche.py | head`); exit quietly.
        _silence_stdout()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
