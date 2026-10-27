"""File-tool boundaries and response diagnostics, without provider calls."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from jsonschema import validate

from evals.adapters.openai_compatible import OpenaiCompatibleAdapter


def response(*, arguments=None, finish_reason="stop", tool=False, content="done"):
    message = {"role": "assistant", "content": content}
    if tool:
        message["tool_calls"] = [{"id": "call-1", "type": "function", "function": {
            "name": "write_file", "arguments": arguments,
        }}]
    return {"choices": [{"message": message, "finish_reason": finish_reason}]}


class OpenaiCompatibleDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="oms-oac-diagnostics-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.workspace = self.root / "project"
        self.workspace.mkdir()
        self.guidance = self.root / "benchmark-context/openmapstack"
        self.guidance.mkdir(parents=True)
        (self.guidance / "SKILL.md").write_text("controlled guidance")
        self.adapter = OpenaiCompatibleAdapter()
        self.adapter.trial_root = self.root

    def execute(self, name, **args):
        return self.adapter._execute_tool(name, args, self.workspace, 10)

    def run_responses(self, responses):
        with patch.dict(os.environ, {
            "OPENAI_COMPATIBLE_BASE_URL": "https://example.invalid/v1",
            "OPENAI_COMPATIBLE_API_KEY": "fake-api-key",
            "OPENAI_COMPATIBLE_MODEL": "test/model",
        }, clear=True), patch.object(self.adapter, "_post_chat", side_effect=responses) as post:
            result = self.adapter.run("build a project", self.workspace)
        return result, post

    def test_guidance_can_be_read_and_listed_while_workspace_remains_writable(self):
        self.assertEqual(self.execute("read_file", path="../benchmark-context/openmapstack/SKILL.md"),
                         (True, "controlled guidance"))
        self.assertEqual(self.execute("list_dir", path="../benchmark-context/openmapstack"),
                         (True, "SKILL.md"))
        self.assertTrue(self.execute("write_file", path="nested/result.txt", content="result")[0])
        self.assertEqual(self.execute("read_file", path="nested/result.txt"), (True, "result"))

    def test_read_boundary_rejects_siblings_prefix_matches_and_symlink_escapes(self):
        (self.root / "private.txt").write_text("private")
        other = self.root / "benchmark-context/openmapstack-other"
        other.mkdir()
        (other / "answer.txt").write_text("private")
        (self.guidance / "escape.txt").symlink_to(self.root / "private.txt")
        (self.workspace / "escape").symlink_to(self.root, target_is_directory=True)
        for name, path in [
            ("read_file", "../private.txt"),
            ("list_dir", ".."),
            ("read_file", "../benchmark-context/openmapstack-other/answer.txt"),
            ("read_file", "../benchmark-context/openmapstack/escape.txt"),
            ("read_file", "escape/private.txt"),
        ]:
            with self.subTest(tool=name, path=path):
                ok, output = self.execute(name, path=path)
                self.assertFalse(ok)
                self.assertIn("escapes", output)
                self.assertNotIn("private\n", output)

    def test_guidance_write_and_workspace_symlink_to_guidance_are_rejected(self):
        (self.workspace / "guidance").symlink_to(self.guidance, target_is_directory=True)
        for path in ["../benchmark-context/openmapstack/SKILL.md", "guidance/SKILL.md"]:
            with self.subTest(path=path):
                self.assertFalse(self.execute("write_file", path=path, content="changed")[0])
        self.assertEqual((self.guidance / "SKILL.md").read_text(), "controlled guidance")

    def test_guidance_is_read_only_even_when_nested_inside_workspace(self):
        self.workspace = self.root
        (self.guidance / "workspace-link.txt").symlink_to(self.root / "result.txt")
        for path in ["benchmark-context/openmapstack/SKILL.md",
                     "benchmark-context/openmapstack/workspace-link.txt"]:
            with self.subTest(path=path):
                ok, output = self.execute("write_file", path=path, content="changed")
                self.assertFalse(ok)
                self.assertIn("read-only", output)
        self.assertFalse((self.root / "result.txt").exists())
        self.assertEqual((self.guidance / "SKILL.md").read_text(), "controlled guidance")

    def test_guidance_access_requires_the_runners_trial_root(self):
        for root in [None, self.root / "unrelated-trial"]:
            with self.subTest(trial_root=root):
                self.adapter.trial_root = root
                self.assertFalse(self.execute("read_file", path="../benchmark-context/openmapstack/SKILL.md")[0])

    def test_redirected_guidance_root_is_not_an_allowance_to_read_another_directory(self):
        self.guidance.rename(self.root / "private-guidance")
        self.guidance.symlink_to(self.root / "private-guidance", target_is_directory=True)
        self.assertFalse(self.execute("read_file", path="../benchmark-context/openmapstack/SKILL.md")[0])
        self.workspace = self.root
        self.assertFalse(self.execute("write_file", path="benchmark-context/openmapstack/SKILL.md", content="changed")[0])
        self.assertEqual((self.root / "private-guidance/SKILL.md").read_text(), "controlled guidance")

    def test_malformed_and_truncated_arguments_keep_diagnostics_and_allow_repair(self):
        for reason, code in [("length", "tool_arguments_truncated"),
                             ("tool_calls", "tool_arguments_malformed"),
                             (None, "tool_arguments_malformed")]:
            with self.subTest(finish_reason=reason):
                (self.workspace / "result.txt").unlink(missing_ok=True)
                invalid = '{"path":"result.txt","content":"unfinished'
                responses = [response(arguments=invalid, tool=True, finish_reason=reason),
                             response(arguments=json.dumps({"path": "result.txt", "content": "repaired"}),
                                      tool=True, finish_reason="tool_calls"), response()]
                if reason is None:
                    del responses[0]["choices"][0]["finish_reason"]
                with patch.object(self.adapter, "_execute_tool", wraps=self.adapter._execute_tool) as execute:
                    result, post = self.run_responses(responses)
                self.assertTrue(result.success)
                self.assertEqual(execute.call_count, 1, "invalid arguments must not execute a tool")
                self.assertEqual((self.workspace / "result.txt").read_text(), "repaired")
                self.assertEqual(result.metadata["finish_reasons"], [reason, "tool_calls", "stop"])
                messages = [e for e in result.events if e["type"] == "assistant.message"]
                self.assertEqual([e["finish_reason"] for e in messages], [reason, "tool_calls", "stop"])
                self.assertEqual(messages[0]["tool_calls"][0]["arguments"], invalid)
                diagnostic = result.metadata["tool_call_diagnostics"][0]
                self.assertEqual(diagnostic["code"], code)
                self.assertEqual(diagnostic["finish_reason"], reason)
                self.assertEqual(diagnostic["tool_call_id"], "call-1")
                self.assertEqual(diagnostic["turn"], 1)
                self.assertIn("Unterminated string", diagnostic["parse_error"]["message"])
                self.assertGreater(diagnostic["parse_error"]["column"], 0)
                failure = next(e for e in result.events if e["type"] == "tool.result")
                self.assertFalse(failure["ok"])
                self.assertEqual(failure["diagnostic"], diagnostic)
                self.assertEqual(json.loads(failure["output"])["code"], code)
                self.assertNotIn("NoneType", failure["output"])
                # The same classified output is fed back to the model.
                tool_message = next(m for m in post.call_args_list[1].args[2]["messages"] if m["role"] == "tool")
                self.assertEqual(tool_message["content"], failure["output"])
                normalized = result.normalized(include_streams=False)
                self.assertEqual(normalized["metadata"]["tool_call_diagnostics"], [diagnostic])
                self.assertNotIn("fake-api-key", json.dumps(normalized))
                schema = Path(__file__).resolve().parents[2] / "evals/schemas/agent-run-v1.schema.json"
                validate(normalized, json.loads(schema.read_text()))

    def test_non_object_and_missing_arguments_are_classified_without_execution(self):
        for arguments in [None, "null", "[]", "42"]:
            with self.subTest(arguments=arguments), patch.object(self.adapter, "_execute_tool") as execute:
                result, _ = self.run_responses([response(arguments=arguments, tool=True), response()])
                execute.assert_not_called()
                diagnostic = result.metadata["tool_call_diagnostics"][0]
                self.assertEqual(diagnostic["code"], "tool_arguments_malformed")
                self.assertIn("object", diagnostic["message"])

    def test_finish_reason_survives_a_response_without_an_assistant_message(self):
        result, _ = self.run_responses([{"choices": [{"finish_reason": "length"}]}])
        self.assertFalse(result.success)
        self.assertEqual(result.normalized(include_streams=False)["metadata"]["finish_reasons"], ["length"])

    def test_a_truncated_final_response_is_not_a_completed_run(self):
        result, _ = self.run_responses([response(finish_reason="length", content="unfinished")])
        self.assertFalse(result.success)
        self.assertFalse(result.metadata["structured_completion"])
        self.assertIn("length", result.stderr)


if __name__ == "__main__":
    unittest.main()
