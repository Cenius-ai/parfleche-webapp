"""Tests for Parfleche.

Runs under pytest (``python3 -m pytest -q``) and, with no extra packages, under
the standard library runner (``python3 -m unittest discover -s tests -v``).
Every shell test drives the real entry point through a pipe, exactly the way a
user drives it, so command parsing, rendering and exit codes are all covered.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "parfleche.py"
sys.path.insert(0, str(ROOT))

import parfleche  # noqa: E402  (path has to be set up first)


def run_shell(commands, cwd=None, close_stdin=True):
    """Run the real CLI with piped commands and return the completed process."""
    lines = list(commands)
    if close_stdin and not any(line.strip() in ("quit", "exit") for line in lines):
        lines.append("quit")
    script = "\n".join(lines) + "\n"
    return subprocess.run(
        [sys.executable, str(APP)],
        input=script,
        capture_output=True,
        text=True,
        cwd=str(cwd or ROOT),
        timeout=60,
    )


def grid_rows(output, width):
    """The rendered grid rows of the wanted width, in order."""
    allowed = set(parfleche.EMPTY_CELL) | {"o", "a", "k", "w", "?"}
    return [line for line in output.splitlines() if len(line) == width and set(line) <= allowed]


class CodecTests(unittest.TestCase):
    """T1 - core data model and JSON codec."""

    def test_round_trip_preserves_project_and_pigments(self):
        project = parfleche.Project(
            name="demo",
            width=2,
            height=2,
            pigments=[parfleche.Pigment("ochre", "o", "iron oxide")],
        )
        restored = parfleche.project_from_dict(
            json.loads(json.dumps(parfleche.project_to_dict(project)))
        )
        self.assertEqual(restored.name, "demo")
        self.assertEqual((restored.width, restored.height), (2, 2))
        self.assertEqual(len(restored.pigments), 1)
        self.assertEqual(restored.pigments[0].name, "ochre")
        self.assertEqual(restored.pigments[0].symbol, "o")
        self.assertEqual(restored.pigments[0].recipe, "iron oxide")
        self.assertEqual(restored.cells, [[None, None], [None, None]])
        self.assertEqual(restored.schema_version, parfleche.SCHEMA_VERSION)

    def test_incompatible_schema_version_is_refused(self):
        payload = parfleche.project_to_dict(parfleche.Project(name="x", width=1, height=1))
        payload["schema_version"] = parfleche.SCHEMA_VERSION + 1
        with self.assertRaises(parfleche.ParflecheError) as caught:
            parfleche.project_from_dict(payload)
        self.assertIn("schema_version", str(caught.exception))

    def test_cell_referencing_unknown_pigment_is_refused(self):
        payload = parfleche.project_to_dict(parfleche.Project(name="x", width=1, height=1))
        payload["cells"] = [["ghost"]]
        with self.assertRaises(parfleche.ParflecheError) as caught:
            parfleche.project_from_dict(payload)
        self.assertIn("unknown pigment", str(caught.exception))


class MirrorUnitTests(unittest.TestCase):
    """T6 - mirror maths on the project object."""

    def _corner_project(self):
        project = parfleche.Project(
            name="corners", width=4, height=4, pigments=[parfleche.Pigment("ochre", "o", "")]
        )
        project.paint(0, 0, "ochre")
        return project

    def test_vertical_mirror_reports_one_cell(self):
        project = self._corner_project()
        self.assertEqual(project.mirror("vertical"), 1)
        self.assertEqual(project.cells[0][0], "ochre")
        self.assertEqual(project.cells[0][3], "ochre")
        self.assertIsNone(project.cells[0][1])

    def test_horizontal_mirror_moves_to_bottom_left(self):
        project = self._corner_project()
        project.mirror("horizontal")
        self.assertEqual(project.cells[3][0], "ochre")
        self.assertIsNone(project.cells[0][3])

    def test_both_axes_fill_all_four_corners(self):
        project = self._corner_project()
        changed = project.mirror("both")
        self.assertEqual(changed, 3)
        for x, y in ((0, 0), (3, 0), (0, 3), (3, 3)):
            self.assertEqual(project.cells[y][x], "ochre", (x, y))

    def test_mirroring_an_empty_grid_changes_nothing(self):
        project = parfleche.Project(name="empty", width=4, height=4)
        self.assertEqual(project.mirror("both"), 0)

    def test_unknown_axis_is_refused_without_mutation(self):
        project = self._corner_project()
        with self.assertRaises(parfleche.ParflecheError):
            project.mirror("diagonal")
        self.assertEqual(project.painted_count(), 1)


class ShellBasicsTests(unittest.TestCase):
    """T2 and T10 - dispatcher, help, quit and EOF."""

    def test_help_lists_every_command(self):
        result = run_shell(["help"])
        self.assertEqual(result.returncode, 0)
        for word in ("grid", "pigments", "mirror", "export", "project", "status", "quit"):
            self.assertIn(word, result.stdout)

    def test_unknown_command_prints_usage_and_keeps_the_prompt(self):
        result = run_shell(["bogus", "status"])
        self.assertEqual(result.returncode, 0)
        self.assertIn("Unknown command: bogus", result.stdout)
        self.assertIn("No project loaded", result.stdout)

    def test_quit_exits_zero(self):
        result = run_shell(["quit"], close_stdin=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Goodbye.", result.stdout)

    def test_end_of_input_exits_zero_with_goodbye(self):
        result = run_shell(["status"], close_stdin=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Goodbye.", result.stdout)

    def test_help_grid_shows_examples(self):
        result = run_shell(["help grid"])
        self.assertIn("grid new 6 6", result.stdout)
        self.assertIn("grid paint 0 0 ochre", result.stdout)

    def test_help_mirror_lists_three_axes_with_examples(self):
        result = run_shell(["help mirror"])
        for axis in ("vertical", "horizontal", "both"):
            self.assertIn("mirror {}".format(axis), result.stdout)

    def test_version_flag(self):
        result = subprocess.run(
            [sys.executable, str(APP), "--version"], capture_output=True, text=True, timeout=60
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("parfleche", result.stdout)

    def test_help_flag_mentions_the_shell(self):
        result = subprocess.run(
            [sys.executable, str(APP), "--help"], capture_output=True, text=True, timeout=60
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("parfleche>", result.stdout)


class GridCommandTests(unittest.TestCase):
    """T3, T5 and T9 - grid lifecycle, painting and grid validation."""

    def test_new_grid_renders_three_rows_of_four_dots(self):
        result = run_shell(["grid new 4 3"])
        rows = grid_rows(result.stdout, 4)
        self.assertEqual(rows, ["....", "....", "...."])
        self.assertIn("4x3", result.stdout)
        self.assertIn("Created an empty 4x3 grid", result.stdout)

    def test_resize_keeps_top_left_cells(self):
        result = run_shell(
            [
                "grid new 4 3",
                'pigments add ochre o "iron oxide"',
                "grid paint 1 1 ochre",
                "grid resize 6 5",
            ]
        )
        rows = grid_rows(result.stdout, 6)
        self.assertEqual(len(rows), 5)
        self.assertTrue(all(len(row) == 6 for row in rows))
        self.assertEqual(rows[1], ".o....")

    def test_clear_empties_every_cell(self):
        result = run_shell(
            ["grid new 4 3", 'pigments add ochre o "iron oxide"', "grid paint 1 1 ochre", "grid clear"]
        )
        rows = grid_rows(result.stdout, 4)
        self.assertEqual(rows[-3:], ["....", "....", "...."])
        self.assertIn("Cleared 1 painted cell", result.stdout)

    def test_erase_empties_one_cell(self):
        result = run_shell(
            ["grid new 4 3", 'pigments add ochre o "iron oxide"', "grid paint 1 1 ochre", "grid erase 1 1"]
        )
        rows = grid_rows(result.stdout, 4)
        self.assertEqual(rows[-3:], ["....", "....", "...."])
        self.assertIn("Erased 'ochre' at (1,1)", result.stdout)

    def test_paint_places_symbol_in_column_two_of_row_one(self):
        result = run_shell(
            ["grid new 4 3", 'pigments add ochre o "iron oxide"', "grid paint 2 1 ochre", "grid show"]
        )
        rows = grid_rows(result.stdout, 4)
        self.assertEqual(rows[-3:], ["....", "..o.", "...."])

    def test_paint_out_of_bounds_leaves_the_grid_untouched(self):
        result = run_shell(
            ["grid new 4 3", 'pigments add ochre o "iron oxide"', "grid paint 9 1 ochre", "grid show"]
        )
        self.assertIn("outside the 4x3 grid", result.stdout)
        rows = grid_rows(result.stdout, 4)
        self.assertEqual(rows[-3:], ["....", "....", "...."])

    def test_paint_unknown_pigment_leaves_the_grid_untouched(self):
        result = run_shell(["grid new 4 3", "grid paint 1 1 blue", "grid show"])
        self.assertIn("unknown pigment 'blue'", result.stdout)
        rows = grid_rows(result.stdout, 4)
        self.assertEqual(rows[-3:], ["....", "....", "...."])

    def test_negative_coordinate_is_rejected(self):
        result = run_shell(
            ["grid new 2 2", 'pigments add ochre o "iron oxide"', "grid paint -1 0 ochre"]
        )
        self.assertIn("outside the 2x2 grid", result.stdout)
        self.assertNotIn("Painted", result.stdout)

    def test_out_of_range_dimension_is_rejected(self):
        result = run_shell(["grid new 0 5", "status"])
        self.assertIn("grid dimensions must be between 1 and 64", result.stdout)
        self.assertIn("No project loaded", result.stdout)

    def test_dimension_above_sixty_four_is_rejected(self):
        result = run_shell(["grid new 65 2", "status"])
        self.assertIn("grid dimensions must be between 1 and 64", result.stdout)
        self.assertNotIn("Created", result.stdout)

    def test_non_numeric_dimension_is_rejected(self):
        result = run_shell(["grid new wide 3"])
        self.assertIn("must be a whole number", result.stdout)

    def test_grid_commands_without_a_project_explain_themselves(self):
        result = run_shell(["grid show"])
        self.assertIn("no project loaded", result.stdout)


class PigmentCommandTests(unittest.TestCase):
    """T4 - pigment library management."""

    def test_add_then_list_shows_symbol_name_and_recipe(self):
        result = run_shell(
            ["grid new 2 2", 'pigments add ochre o "iron oxide, roasted"', "pigments list"]
        )
        self.assertIn("o  ochre  iron oxide, roasted", result.stdout)

    def test_duplicate_name_is_refused(self):
        result = run_shell(
            [
                "grid new 2 2",
                'pigments add ochre o "iron oxide"',
                'pigments add ochre x "other"',
                "pigments list",
            ]
        )
        self.assertIn("already exists", result.stdout)
        self.assertEqual(result.stdout.count("o  ochre  iron oxide"), 1)

    def test_multi_character_symbol_is_refused(self):
        result = run_shell(["grid new 2 2", 'pigments add ochre oo "x"', "pigments list"])
        self.assertIn("exactly one character", result.stdout)
        self.assertIn("No pigments yet", result.stdout)

    def test_in_use_pigment_cannot_be_removed(self):
        result = run_shell(
            [
                "grid new 2 2",
                'pigments add ochre o "iron oxide"',
                "grid paint 0 0 ochre",
                "pigments remove ochre",
                "pigments list",
            ]
        )
        self.assertIn("is used by 1 cell", result.stdout)
        self.assertIn("ochre", result.stdout)

    def test_unused_pigment_is_removed(self):
        result = run_shell(
            [
                "grid new 2 2",
                'pigments add ochre o "iron oxide"',
                'pigments add lapis l "azurite"',
                "pigments remove ochre",
                "pigments list",
            ]
        )
        self.assertIn("Removed pigment 'ochre'", result.stdout)
        self.assertNotIn("ochre", result.stdout.split("Removed pigment 'ochre'")[1])


class MirrorCommandTests(unittest.TestCase):
    """T6 - mirroring through the shell."""

    def _corner_session(self, axis):
        return run_shell(
            [
                "grid new 4 4",
                'pigments add ochre o "iron oxide"',
                "grid paint 0 0 ochre",
                "mirror {}".format(axis),
            ]
        )

    def test_vertical_mirror_places_cell_at_far_right(self):
        result = self._corner_session("vertical")
        rows = grid_rows(result.stdout, 4)
        self.assertEqual(rows[-4:], ["o..o", "....", "....", "...."])
        self.assertIn("1 cell changed", result.stdout)

    def test_horizontal_mirror_places_cell_at_bottom(self):
        result = self._corner_session("horizontal")
        rows = grid_rows(result.stdout, 4)
        self.assertEqual(rows[-4:], ["o...", "....", "....", "o..."])

    def test_both_mirror_fills_all_four_corners(self):
        result = self._corner_session("both")
        rows = grid_rows(result.stdout, 4)
        self.assertEqual(rows[-4:], ["o..o", "....", "....", "o..o"])
        self.assertIn("3 cells changed", result.stdout)

    def test_empty_grid_mirror_reports_zero_changed(self):
        result = run_shell(["grid new 4 4", "mirror both"])
        self.assertIn("0 cells changed", result.stdout)

    def test_unknown_axis_is_rejected(self):
        result = run_shell(["grid new 4 4", "mirror diagonal"])
        self.assertIn("unknown mirror axis", result.stdout)


class ExportTests(unittest.TestCase):
    """T7 - Markdown recipe card export."""

    def test_export_writes_cards_for_used_pigments_only(self):
        with tempfile.TemporaryDirectory() as workdir:
            result = run_shell(
                [
                    "grid new 3 3",
                    'pigments add ochre o "iron oxide"',
                    'pigments add lapis l "azurite"',
                    "grid paint 0 0 ochre",
                    "export recipes ochre_cards.md",
                ],
                cwd=workdir,
            )
            self.assertEqual(result.returncode, 0)
            self.assertIn("Wrote 1 recipe card", result.stdout)
            target = Path(workdir) / "ochre_cards.md"
            text = target.read_text(encoding="utf-8")
            self.assertIn("# Parfleche Recipe Cards", text)
            self.assertIn("## o - ochre", text)
            self.assertIn("iron oxide", text)
            self.assertNotIn("lapis", text)
            self.assertIn("**Grid:** 3x3", text)
            self.assertIn("**Exported:**", text)

    def test_export_to_missing_directory_reports_a_path_error(self):
        with tempfile.TemporaryDirectory() as workdir:
            result = run_shell(
                [
                    "grid new 3 3",
                    'pigments add ochre o "iron oxide"',
                    "grid paint 0 0 ochre",
                    "export recipes no/such/dir/cards.md",
                ],
                cwd=workdir,
            )
            self.assertIn("does not exist", result.stdout)
            self.assertFalse((Path(workdir) / "no").exists())

    def test_export_with_no_painted_cells_explains_what_to_do(self):
        with tempfile.TemporaryDirectory() as workdir:
            result = run_shell(
                [
                    "grid new 3 3",
                    'pigments add ochre o "iron oxide"',
                    "export recipes cards.md",
                ],
                cwd=workdir,
            )
            self.assertIn("nothing to export", result.stdout)
            self.assertFalse((Path(workdir) / "cards.md").exists())


class ProjectFileTests(unittest.TestCase):
    """T8 - JSON save and load across processes."""

    def test_save_then_load_in_a_fresh_process_restores_the_grid(self):
        with tempfile.TemporaryDirectory() as workdir:
            first = run_shell(
                [
                    "grid new 2 2",
                    'pigments add ochre o "iron oxide"',
                    "grid paint 0 0 ochre",
                    "project save demo.json",
                ],
                cwd=workdir,
            )
            self.assertEqual(first.returncode, 0)
            saved = Path(workdir) / "demo.json"
            self.assertTrue(saved.exists())

            second = run_shell(["project load demo.json", "status", "grid show"], cwd=workdir)
            self.assertIn("demo.json", second.stdout)
            self.assertIn("2x2", second.stdout)
            rows = grid_rows(second.stdout, 2)
            self.assertEqual(rows[-2:], ["o.", ".."])
            payload = json.loads(saved.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], parfleche.SCHEMA_VERSION)
            self.assertEqual(payload["pigments"][0]["name"], "ochre")

    def test_missing_file_reports_no_such_file(self):
        with tempfile.TemporaryDirectory() as workdir:
            result = run_shell(["project load missing.json", "status"], cwd=workdir)
            self.assertIn("No such file", result.stdout)
            self.assertIn("No project loaded", result.stdout)

    def test_corrupt_file_reports_a_json_parse_error(self):
        with tempfile.TemporaryDirectory() as workdir:
            (Path(workdir) / "bad.json").write_text("{not json", encoding="utf-8")
            result = run_shell(["project load bad.json", "status"], cwd=workdir)
            self.assertIn("JSON parse error", result.stdout)
            self.assertEqual(result.returncode, 0)

    def test_failed_load_leaves_the_loaded_project_untouched(self):
        with tempfile.TemporaryDirectory() as workdir:
            (Path(workdir) / "bad.json").write_text("{not json", encoding="utf-8")
            result = run_shell(["grid new 3 3", "project load bad.json", "status"], cwd=workdir)
            self.assertIn("JSON parse error", result.stdout)
            self.assertIn("Grid:     3x3", result.stdout)

    def test_unsupported_schema_version_is_refused(self):
        with tempfile.TemporaryDirectory() as workdir:
            payload = parfleche.project_to_dict(parfleche.Project(name="future", width=1, height=1))
            payload["schema_version"] = 99
            (Path(workdir) / "future.json").write_text(json.dumps(payload), encoding="utf-8")
            result = run_shell(["project load future.json", "status"], cwd=workdir)
            self.assertIn("unsupported schema_version 99", result.stdout)
            self.assertIn("No project loaded", result.stdout)


class PathConfinementTests(unittest.TestCase):
    """Every user path is resolved inside the working directory and never escapes it."""

    def test_save_outside_the_working_directory_is_refused(self):
        with tempfile.TemporaryDirectory() as workdir:
            outside = Path(workdir).parent / "parfleche-escape-{}.json".format(os.getpid())
            result = run_shell(
                ["grid new 2 2", "project save ../{}".format(outside.name)], cwd=workdir
            )
            self.assertIn("outside the working directory", result.stdout)
            self.assertFalse(outside.exists())

    def test_absolute_path_outside_the_working_directory_is_refused(self):
        with tempfile.TemporaryDirectory() as workdir:
            result = run_shell(
                ["grid new 2 2", "project save /tmp/parfleche-absolute.json"], cwd=workdir
            )
            self.assertIn("outside the working directory", result.stdout)
            self.assertFalse(Path("/tmp/parfleche-absolute.json").exists())

    def test_export_traversal_is_refused_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as workdir:
            (Path(workdir) / "sub").mkdir()
            result = run_shell(
                [
                    "grid new 2 2",
                    'pigments add ochre o "iron oxide"',
                    "grid paint 0 0 ochre",
                    "export recipes sub/../../escaped.md",
                ],
                cwd=workdir,
            )
            self.assertIn("outside the working directory", result.stdout)
            self.assertFalse((Path(workdir).parent / "escaped.md").exists())

    def test_load_traversal_is_refused(self):
        with tempfile.TemporaryDirectory() as workdir:
            result = run_shell(["project load ../etc/passwd", "status"], cwd=workdir)
            self.assertIn("outside the working directory", result.stdout)
            self.assertIn("No project loaded", result.stdout)

    def test_confine_path_accepts_paths_inside_the_workspace(self):
        with tempfile.TemporaryDirectory() as workdir:
            previous = Path.cwd()
            os.chdir(workdir)
            try:
                inside = parfleche.confine_path("notes/cards.md", "export")
                self.assertTrue(str(inside).startswith(str(Path(workdir).resolve())))
                with self.assertRaises(parfleche.ParflecheError):
                    parfleche.confine_path("../../etc/passwd", "load")
                with self.assertRaises(parfleche.ParflecheError):
                    parfleche.confine_path("/etc/passwd", "load")
            finally:
                os.chdir(previous)


class BundledExampleTests(unittest.TestCase):
    """The shipped example project must load, mirror and export end to end."""

    def setUp(self):
        self._previous_cwd = Path.cwd()
        os.chdir(str(ROOT))

    def tearDown(self):
        os.chdir(str(self._previous_cwd))

    def test_example_project_loads_and_mirrors(self):
        self.assertTrue((ROOT / "examples" / "parfleche-blanket.json").exists())
        project = parfleche.load_project("examples/parfleche-blanket.json")
        self.assertEqual((project.width, project.height), (12, 12))
        self.assertEqual(len(project.pigments), 4)
        self.assertEqual(project.painted_count(), 20)
        self.assertEqual(project.render()[0], "....w.......")
        changed = project.mirror("both")
        self.assertEqual(changed, 60)
        self.assertEqual(project.painted_count(), 80)
        self.assertEqual(project.render()[0], "....w..w....")
        self.assertEqual(project.render()[1], "...w.aa.w...")
        self.assertEqual(project.render()[0], project.render()[11])
        markdown = parfleche.render_recipe_cards(project)
        self.assertEqual(markdown.count("\n## "), 4)
        self.assertIn("## w - bone white", markdown)


class DemoScriptTests(unittest.TestCase):
    """demo.sh must run non-interactively and exit cleanly."""

    def test_demo_script_runs_to_completion(self):
        result = subprocess.run(
            ["bash", "demo.sh"], capture_output=True, text=True, cwd=str(ROOT), timeout=120
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Demo complete.", result.stdout)
        self.assertIn("# Parfleche Recipe Cards", result.stdout)
        self.assertNotIn("Traceback", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
