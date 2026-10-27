"""Ranged reads and exact-string edits of the openai_compatible file tools."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from evals.adapters.openai_compatible import MAX_TOOL_OUTPUT_CHARS, TOOLS, OpenaiCompatibleAdapter


class OpenaiCompatibleFileToolTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="oms-oac-file-tools-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.workspace = self.root / "project"
        self.workspace.mkdir()
        self.guidance = self.root / "benchmark-context/openmapstack"
        self.guidance.mkdir(parents=True)
        (self.guidance / "SKILL.md").write_text("line one\nline two\nline three\n")
        self.adapter = OpenaiCompatibleAdapter()
        self.adapter.trial_root = self.root

    def execute(self, name, **args):
        return self.adapter._execute_tool(name, args, self.workspace, 10)

    def write(self, name, text):
        (self.workspace / name).write_text(text, newline="")

    def test_tools_are_declared_to_the_model(self):
        declared = {tool["function"]["name"]: tool["function"]["parameters"] for tool in TOOLS}
        self.assertEqual(set(declared["read_file"]["properties"]), {"path", "offset", "limit"})
        self.assertEqual(declared["edit_file"]["required"], ["path", "old_string", "new_string"])

    def test_small_whole_file_read_is_unchanged(self):
        self.write("small.txt", "alpha\nbeta\n")
        self.assertEqual(self.execute("read_file", path="small.txt"), (True, "alpha\nbeta\n"))

    def test_ranged_read_reports_lines_size_and_continuation(self):
        text = "".join(f"row {n}\n" for n in range(1, 11))
        self.write("rows.txt", text)
        ok, output = self.execute("read_file", path="rows.txt", offset=3, limit=2)
        self.assertTrue(ok)
        self.assertEqual(output, f"[read_file: lines 3-4 of 10; {len(text)} characters total; "
                                 "more remains, continue with offset=5]\nrow 3\nrow 4\n")
        ok, output = self.execute("read_file", path="rows.txt", offset=9)
        self.assertTrue(ok)
        self.assertEqual(output, f"[read_file: lines 9-10 of 10; {len(text)} characters total; end of file]\nrow 9\nrow 10\n")

    def test_a_last_line_without_a_newline_is_shown_exactly(self):
        self.write("tail.txt", "one\ntwo")
        ok, output = self.execute("read_file", path="tail.txt", offset=2)
        self.assertTrue(ok)
        self.assertEqual(output, "[read_file: lines 2-2 of 2; 7 characters total; end of file]\ntwo")

    def test_line_numbers_match_sed_despite_other_line_separators(self):
        # str.splitlines() would also split on these; tracebacks, grep -n and sed do not.
        text = "first\x0cpage\nsecond\u2028same line\nthird\x0b\x1c\x1d\x1e\x85\nfourth\r\nfifth\n"
        (self.workspace / "odd.txt").write_bytes(text.encode("utf-8"))
        for offset in range(1, 6):
            with self.subTest(offset=offset):
                ok, output = self.execute("read_file", path="odd.txt", offset=offset, limit=1)
                self.assertTrue(ok)
                note, line = output.split("\n", 1)
                self.assertIn(f"lines {offset}-{offset} of 5", note)
                self.assertEqual(line, text.split("\n")[offset - 1] + "\n")
                if shutil.which("sed"):
                    sed = subprocess.run(["sed", "-n", f"{offset}p", "odd.txt"], cwd=self.workspace,
                                         capture_output=True, check=True)
                    self.assertEqual(line.encode("utf-8"), sed.stdout)
        ok, output = self.execute("edit_file", path="odd.txt", old_string="fifth", new_string="5th")
        self.assertTrue(ok, output)
        self.assertIn("file now has 5 lines", output)

    def test_large_file_is_paged_by_whole_lines_until_the_end(self):
        line = "x" * 99 + "\n"
        text = line * 450  # 45,000 characters, like the 45 KB pipeline in #120
        self.write("pipeline.py", text)
        pieces, offset = [], None
        for _ in range(10):
            ok, output = self.execute("read_file", **({"path": "pipeline.py"} | ({"offset": offset} if offset else {})))
            self.assertTrue(ok)
            note, body = output.split("\n", 1)
            self.assertLessEqual(len(body), MAX_TOOL_OUTPUT_CHARS)
            self.assertIn(f"of 450; {len(text)} characters total", note)
            pieces.append(body)
            if "end of file" in note:
                break
            offset = int(note.rsplit("offset=", 1)[1].rstrip("]"))
        self.assertEqual("".join(pieces), text)
        self.assertEqual(len(pieces), 3)

    def test_a_single_overlong_line_is_cut_and_reported(self):
        text = "y" * (MAX_TOOL_OUTPUT_CHARS + 500) + "\nnext\n"
        self.write("data.geojson", text)
        ok, output = self.execute("read_file", path="data.geojson")
        self.assertTrue(ok)
        note, body = output.split("\n", 1)
        self.assertTrue(note.startswith("[read_file: lines 1-1 of 2;"))
        self.assertIn(f"line 1 was cut at {MAX_TOOL_OUTPUT_CHARS} characters", note)
        self.assertIn("continue with offset=2", note)
        self.assertEqual(body, "y" * MAX_TOOL_OUTPUT_CHARS)

    def test_invalid_ranges_are_rejected(self):
        self.write("rows.txt", "a\nb\n")
        for args in [{"offset": 0}, {"offset": -1}, {"limit": 0}, {"offset": "2"}, {"offset": True}, {"offset": 1.5}]:
            with self.subTest(args=args):
                ok, output = self.execute("read_file", path="rows.txt", **args)
                self.assertFalse(ok)
                self.assertIn("positive integer", output)
        ok, output = self.execute("read_file", path="rows.txt", offset=3)
        self.assertFalse(ok)
        self.assertIn("past the end of the file (2 lines)", output)
        self.write("empty.txt", "")
        self.assertEqual(self.execute("read_file", path="empty.txt"), (True, ""))
        self.assertEqual(self.execute("read_file", path="empty.txt", offset=1), (True, "[read_file: empty file]"))

    def test_ranged_read_keeps_the_guidance_boundary(self):
        ok, output = self.execute("read_file", path="../benchmark-context/openmapstack/SKILL.md", offset=2, limit=1)
        self.assertTrue(ok)
        self.assertTrue(output.startswith("[read_file: lines 2-2 of 3;"))
        self.assertTrue(output.endswith("]\nline two\n"))
        (self.root / "private.txt").write_text("private\n")
        ok, output = self.execute("read_file", path="../private.txt", offset=1)
        self.assertFalse(ok)
        self.assertIn("escapes", output)

    def test_edit_replaces_a_unique_exact_string(self):
        self.write("pipeline.py", "def main():\n    return 1\n\n\ndef helper():\n    return 2\n")
        ok, output = self.execute("edit_file", path="pipeline.py", old_string="    return 1\n", new_string="    return 10\n")
        self.assertTrue(ok, output)
        self.assertIn("replaced 1 occurrence in pipeline.py", output)
        self.assertEqual((self.workspace / "pipeline.py").read_text(),
                         "def main():\n    return 10\n\n\ndef helper():\n    return 2\n")

    def test_ambiguous_or_missing_matches_change_nothing(self):
        original = "x = 1\ny = 1\n"
        self.write("values.py", original)
        ok, output = self.execute("edit_file", path="values.py", old_string="1", new_string="2")
        self.assertFalse(ok)
        self.assertIn("occurs 2 times", output)
        ok, output = self.execute("edit_file", path="values.py", old_string="z = 1", new_string="z = 2")
        self.assertFalse(ok)
        self.assertIn("not found", output)
        self.assertEqual((self.workspace / "values.py").read_text(), original)
        ok, output = self.execute("edit_file", path="values.py", old_string="1", new_string="2", replace_all=True)
        self.assertTrue(ok, output)
        self.assertIn("replaced 2 occurrences", output)
        self.assertEqual((self.workspace / "values.py").read_text(), "x = 2\ny = 2\n")

    def test_overlapping_matches_are_not_unique(self):
        self.write("gaps.txt", "x\n\n\ny\n")
        ok, output = self.execute("edit_file", path="gaps.txt", old_string="\n\n", new_string="\n")
        self.assertFalse(ok)
        self.assertIn("occurs 2 times", output)
        self.assertEqual((self.workspace / "gaps.txt").read_text(), "x\n\n\ny\n")

    def test_edit_preserves_line_endings_seen_by_read_file(self):
        self.write("windows.txt", "first\r\nsecond\r\n")
        ok, output = self.execute("read_file", path="windows.txt", offset=1, limit=1)
        self.assertTrue(output.endswith("]\nfirst\r\n"))
        ok, output = self.execute("edit_file", path="windows.txt", old_string="first\r\n", new_string="1st\r\n")
        self.assertTrue(ok, output)
        self.assertEqual((self.workspace / "windows.txt").read_bytes(), b"1st\r\nsecond\r\n")

    def test_lf_old_string_matches_a_crlf_file_in_its_own_line_endings(self):
        self.write("windows.txt", "first\r\nsecond\r\nthird\r\n")
        ok, output = self.execute("edit_file", path="windows.txt", old_string="first\nsecond\n",
                                  new_string="1st\n2nd\n")
        self.assertTrue(ok, output)
        self.assertIn("using its CRLF line endings", output)
        self.assertEqual((self.workspace / "windows.txt").read_bytes(), b"1st\r\n2nd\r\nthird\r\n")
        ok, output = self.execute("edit_file", path="windows.txt", old_string="1st\nmissing\n", new_string="x")
        self.assertFalse(ok)
        self.assertIn("CRLF", output)
        self.assertEqual((self.workspace / "windows.txt").read_bytes(), b"1st\r\n2nd\r\nthird\r\n")

    def test_invalid_edit_arguments_are_rejected(self):
        self.write("a.txt", "a\n")
        for args in [{"old_string": "", "new_string": "b"}, {"old_string": "a", "new_string": None},
                     {"old_string": "a", "new_string": "a"}, {"old_string": "a", "new_string": "b", "replace_all": "yes"}]:
            with self.subTest(args=args):
                self.assertFalse(self.execute("edit_file", path="a.txt", **args)[0])
        self.assertFalse(self.execute("edit_file", path="missing.txt", old_string="a", new_string="b")[0])
        self.assertEqual((self.workspace / "a.txt").read_text(), "a\n")

    def test_edit_is_confined_to_the_workspace_and_cannot_touch_guidance(self):
        (self.root / "outside.txt").write_text("outside\n")
        (self.workspace / "guidance").symlink_to(self.guidance, target_is_directory=True)
        for path, expected in [("../outside.txt", "escapes"),
                               ("../benchmark-context/openmapstack/SKILL.md", "read-only"),
                               ("guidance/SKILL.md", "read-only")]:
            with self.subTest(path=path):
                ok, output = self.execute("edit_file", path=path, old_string="line", new_string="LINE")
                self.assertFalse(ok)
                self.assertIn(expected, output)
        self.assertEqual((self.root / "outside.txt").read_text(), "outside\n")
        self.assertEqual((self.guidance / "SKILL.md").read_text(), "line one\nline two\nline three\n")


if __name__ == "__main__":
    unittest.main()
