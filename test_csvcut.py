#!/usr/bin/env python3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Add directory to sys.path so we can import csvcut directly
sys.path.insert(0, str(Path(__file__).parent))
import csvcut


class TestFieldSpecParser(unittest.TestCase):
    def test_single_field(self):
        self.assertEqual(csvcut.parse_field_spec("1"), [(1, 1)])
        self.assertEqual(csvcut.parse_field_spec("5"), [(5, 5)])

    def test_closed_range(self):
        self.assertEqual(csvcut.parse_field_spec("1-3"), [(1, 3)])
        self.assertEqual(csvcut.parse_field_spec("2-2"), [(2, 2)])

    def test_open_range_suffix(self):
        self.assertEqual(csvcut.parse_field_spec("3-"), [(3, float("inf"))])

    def test_open_range_prefix(self):
        self.assertEqual(csvcut.parse_field_spec("-3"), [(1, 3)])

    def test_multiple_comma_separated(self):
        self.assertEqual(csvcut.parse_field_spec("1,3,5"), [(1, 1), (3, 3), (5, 5)])
        self.assertEqual(csvcut.parse_field_spec("1, 3, 5"), [(1, 1), (3, 3), (5, 5)])

    def test_reordering_and_deduplication(self):
        # Like cut, selected fields are strictly sorted and deduplicated
        self.assertEqual(csvcut.parse_field_spec("3,1"), [(1, 1), (3, 3)])
        self.assertEqual(csvcut.parse_field_spec("2,2"), [(2, 2)])
        self.assertEqual(csvcut.parse_field_spec("1-3,2-4"), [(1, 4)])
        self.assertEqual(csvcut.parse_field_spec("1-3,4-6"), [(1, 6)])

    def test_whitespace_separation(self):
        self.assertEqual(csvcut.parse_field_spec("1 3"), [(1, 1), (3, 3)])

    def test_invalid_ranges(self):
        # 0 is invalid (1-indexed)
        with self.assertRaises(ValueError) as ctx:
            csvcut.parse_field_spec("0")
        self.assertIn("fields and positions are numbered from 1", str(ctx.exception))

        with self.assertRaises(ValueError) as ctx:
            csvcut.parse_field_spec("-0")
        self.assertIn("fields and positions are numbered from 1", str(ctx.exception))

        with self.assertRaises(ValueError) as ctx:
            csvcut.parse_field_spec("0-")
        self.assertIn("fields and positions are numbered from 1", str(ctx.exception))

        with self.assertRaises(ValueError) as ctx:
            csvcut.parse_field_spec("1-0")
        self.assertIn("fields and positions are numbered from 1", str(ctx.exception))

        # High end less than low end
        with self.assertRaises(ValueError) as ctx:
            csvcut.parse_field_spec("4-2")
        self.assertIn("high end of range less than low end", str(ctx.exception))

        # No endpoint
        with self.assertRaises(ValueError) as ctx:
            csvcut.parse_field_spec("-")
        self.assertIn("invalid range with no endpoint", str(ctx.exception))

        # Malformed tokens
        with self.assertRaises(ValueError) as ctx:
            csvcut.parse_field_spec("")
        self.assertIn("failed to parse range", str(ctx.exception))

        with self.assertRaises(ValueError) as ctx:
            csvcut.parse_field_spec("1,")
        self.assertIn("failed to parse range", str(ctx.exception))

        with self.assertRaises(ValueError) as ctx:
            csvcut.parse_field_spec(",1")
        self.assertIn("failed to parse range", str(ctx.exception))

        with self.assertRaises(ValueError) as ctx:
            csvcut.parse_field_spec("1,,2")
        self.assertIn("failed to parse range", str(ctx.exception))

        with self.assertRaises(ValueError) as ctx:
            csvcut.parse_field_spec("abc")
        self.assertIn("failed to parse range", str(ctx.exception))


class TestExtractFields(unittest.TestCase):
    def test_extract(self):
        row = ["a", "b", "c", "d", "e"]
        intervals = [(2, 2)]
        self.assertEqual(csvcut.extract_fields(row, intervals), ["b"])

        intervals = [(1, 1), (3, 4)]
        self.assertEqual(csvcut.extract_fields(row, intervals), ["a", "c", "d"])

        intervals = [(4, float("inf"))]
        self.assertEqual(csvcut.extract_fields(row, intervals), ["d", "e"])

        intervals = [(10, 12)]
        self.assertEqual(csvcut.extract_fields(row, intervals), [])

        self.assertEqual(csvcut.extract_fields([], intervals), [])


class TestCsvCutCLI(unittest.TestCase):
    def run_csvcut(self, args, stdin_data=None):
        cmd = [sys.executable, str(Path(__file__).parent / "csvcut.py")] + args
        proc = subprocess.run(
            cmd,
            input=stdin_data,
            capture_output=True,
            text=True,
        )
        return proc

    def test_missing_fields_flag(self):
        res = self.run_csvcut([])
        self.assertEqual(res.returncode, 1)
        self.assertIn("csvcut: invalid usage: expects --fields (-f)", res.stderr)

    def test_help_flag(self):
        res = self.run_csvcut(["--help"])
        self.assertEqual(res.returncode, 0)
        self.assertIn("Select columns from CSV files", res.stdout)

    def test_basic_stdin(self):
        input_csv = "a,b,c\n1,2,3\n4,5,6\n"
        res = self.run_csvcut(["-f", "1,3"], stdin_data=input_csv)
        self.assertEqual(res.returncode, 0)
        self.assertEqual(res.stdout, "a,c\n1,3\n4,6\n")

    def test_quoted_commas_and_escapes(self):
        # The key reason cut(1) fails on CSV: commas inside quotes!
        input_csv = '1,"Smith, John",35,"Engineer, Lead"\n2,"Doe, Jane",28,"Designer"\n'
        res = self.run_csvcut(["-f", "2"], stdin_data=input_csv)
        self.assertEqual(res.returncode, 0)
        self.assertEqual(res.stdout, '"Smith, John"\n"Doe, Jane"\n')

        res = self.run_csvcut(["-f", "1,3"], stdin_data=input_csv)
        self.assertEqual(res.returncode, 0)
        self.assertEqual(res.stdout, "1,35\n2,28\n")

    def test_multiline_fields(self):
        input_csv = '1,"Line 1\nLine 2",3\n4,simple,5\n'
        res = self.run_csvcut(["-f", "2"], stdin_data=input_csv)
        self.assertEqual(res.returncode, 0)
        self.assertEqual(res.stdout, '"Line 1\nLine 2"\nsimple\n')

        res = self.run_csvcut(["-f", "1,3"], stdin_data=input_csv)
        self.assertEqual(res.returncode, 0)
        self.assertEqual(res.stdout, "1,3\n4,5\n")

    def test_ranges_and_open_ends(self):
        input_csv = "1,2,3,4,5\n"
        # Prefix range
        res = self.run_csvcut(["-f", "-2"], stdin_data=input_csv)
        self.assertEqual(res.returncode, 0)
        self.assertEqual(res.stdout, "1,2\n")

        # Suffix range
        res = self.run_csvcut(["-f", "4-"], stdin_data=input_csv)
        self.assertEqual(res.returncode, 0)
        self.assertEqual(res.stdout, "4,5\n")

        # Range
        res = self.run_csvcut(["-f", "2-4"], stdin_data=input_csv)
        self.assertEqual(res.returncode, 0)
        self.assertEqual(res.stdout, "2,3,4\n")

    def test_file_arguments(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as f1, tempfile.NamedTemporaryFile("w", delete=False) as f2:
            f1.write("a,b,c\n1,2,3\n")
            f2.write("d,e,f\n4,5,6\n")
            f1_path = f1.name
            f2_path = f2.name

        try:
            res = self.run_csvcut(["-f", "2", f1_path, f2_path])
            self.assertEqual(res.returncode, 0)
            self.assertEqual(res.stdout, "b\n2\ne\n5\n")
        finally:
            Path(f1_path).unlink(missing_ok=True)
            Path(f2_path).unlink(missing_ok=True)

    def test_missing_file_handling(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write("a,b\n1,2\n")
            f_path = f.name

        try:
            res = self.run_csvcut(["-f", "1", f_path, "/nonexistent/file.csv"])
            self.assertEqual(res.returncode, 1)
            self.assertIn("a\n1\n", res.stdout)
            self.assertIn("csvcut: /nonexistent/file.csv:", res.stderr)
        finally:
            Path(f_path).unlink(missing_ok=True)

    def test_explicit_dash_for_stdin(self):
        input_csv = "x,y,z\n"
        res = self.run_csvcut(["-f", "2", "-"], stdin_data=input_csv)
        self.assertEqual(res.returncode, 0)
        self.assertEqual(res.stdout, "y\n")

    def test_out_of_range_field(self):
        input_csv = "a,b\n"
        res = self.run_csvcut(["-f", "5"], stdin_data=input_csv)
        self.assertEqual(res.returncode, 0)
        self.assertEqual(res.stdout, "\n")

    def test_selection_order_basic(self):
        # User requested example: echo 1,2,3 | csvcut --selection-order -f3,2,1 should emit 3,2,1
        input_csv = "1,2,3\n"
        res = self.run_csvcut(["--selection-order", "-f3,2,1"], stdin_data=input_csv)
        self.assertEqual(res.returncode, 0)
        self.assertEqual(res.stdout, "3,2,1\n")

    def test_selection_order_default_preserved(self):
        # Without --selection-order, order is row input order
        input_csv = "1,2,3\n"
        res = self.run_csvcut(["-f3,2,1"], stdin_data=input_csv)
        self.assertEqual(res.returncode, 0)
        self.assertEqual(res.stdout, "1,2,3\n")

    def test_selection_order_ranges_and_duplicates(self):
        input_csv = "a,b,c,d,e\n"
        res = self.run_csvcut(["--selection-order", "-f", "5,1-2,4,2"], stdin_data=input_csv)
        self.assertEqual(res.returncode, 0)
        self.assertEqual(res.stdout, "e,a,b,d,b\n")

    def test_selection_order_open_suffix(self):
        input_csv = "a,b,c,d\n"
        res = self.run_csvcut(["--selection-order", "-f", "4,2-"], stdin_data=input_csv)
        self.assertEqual(res.returncode, 0)
        self.assertEqual(res.stdout, "d,b,c,d\n")

    def test_selection_order_alias_flags(self):
        input_csv = "1,2,3\n"
        # -O alias
        res = self.run_csvcut(["-O", "-f", "3,1"], stdin_data=input_csv)
        self.assertEqual(res.returncode, 0)
        self.assertEqual(res.stdout, "3,1\n")

        # --preserve-order alias
        res = self.run_csvcut(["--preserve-order", "-f", "2,1"], stdin_data=input_csv)
        self.assertEqual(res.returncode, 0)
        self.assertEqual(res.stdout, "2,1\n")


if __name__ == "__main__":
    unittest.main()
