"""Step 8: the entry point.

The brief: "Entry point: `system/run <data_folder> <output_file>` — executable, reads
**only** that folder, writes **one JSON line per hit**." and "The system must still run
(regex-only) if the key is missing or the API fails."
"""

import ast
import io
import json
import os
import pathlib
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fixture  # noqa: E402
from system import cli, model  # noqa: E402

FOLDER = os.path.join(ROOT, "dev")
RUN = os.path.join(ROOT, "system", "run")


def tiny_folder():
    return fixture.Folder(
        alerts=[fixture.alert(name="Ada Lovelace", dob="1815-12-10", hit_ids=["H-1"])],
        hits=[{
            "hit_id": "H-1", "alert_id": "A-1", "entity_type": "Individual",
            "name": "Lovelace, Ada", "dobs": ["1815-12-10"], "categories": ["PEP"],
            "primary_category": "PEP", "countries": ["United Kingdom"],
        }],
        customers=[fixture.customer("CUS-A", "Ada Lovelace", dob="1815-12-10",
                                    residence_country="GB")],
    )


class TestPackaging(unittest.TestCase):
    def test_run_is_executable(self):
        self.assertTrue(os.path.isfile(RUN))
        self.assertTrue(os.stat(RUN).st_mode & stat.S_IXUSR, "system/run is not executable")

    def test_the_package_imports_nothing_outside_the_standard_library(self):
        found = set()
        for path in list(pathlib.Path(ROOT, "system").glob("*.py")) + [pathlib.Path(RUN)]:
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Import):
                    found |= {a.name.split(".")[0] for a in node.names}
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    found.add(node.module.split(".")[0])
        local = {p.stem for p in pathlib.Path(ROOT, "system").glob("*.py")} | {"system"}
        outside = sorted(found - local)
        self.assertTrue(outside)
        self.assertEqual([m for m in outside if m not in sys.stdlib_module_names], [])


class TestArguments(unittest.TestCase):
    def test_the_two_positional_arguments(self):
        args = cli.build_parser().parse_args(["dev", "out.jsonl"])
        self.assertEqual(args.data_folder, "dev")
        self.assertEqual(args.output_file, "out.jsonl")
        self.assertFalse(args.no_llm)

    def test_the_no_llm_flag(self):
        self.assertTrue(cli.build_parser().parse_args(["dev", "o", "--no-llm"]).no_llm)

    def test_missing_arguments_are_refused(self):
        with self.assertRaises(SystemExit):
            cli.build_parser().parse_args(["dev"])


class TestLlmAvailability(unittest.TestCase):
    def test_no_key_means_no_model(self):
        self.assertFalse(cli.llm_available(False, env={}))

    def test_a_key_means_it_may_be_used(self):
        self.assertTrue(cli.llm_available(False, env={cli.ENV_KEY: "sk-x"}))

    def test_a_blank_key_is_no_key(self):
        self.assertFalse(cli.llm_available(False, env={cli.ENV_KEY: "   "}))

    def test_no_llm_overrides_a_key(self):
        self.assertFalse(cli.llm_available(True, env={cli.ENV_KEY: "sk-x"}))

    def test_no_key_in_the_environment_means_no_model_whatever_is_on_disk(self):
        # The key comes from the environment variable the brief names and nowhere else, so
        # a .env sitting beside the code cannot change how a graded run behaves.
        before = os.environ.get(cli.ENV_KEY)
        os.environ.pop(cli.ENV_KEY, None)
        try:
            self.assertFalse(cli.llm_available(False))
            self.assertIsNone(cli.build_extractor(False))
        finally:
            if before is not None:
                os.environ[cli.ENV_KEY] = before

    def test_a_key_that_leads_nowhere_still_produces_a_run(self):
        before = os.environ.get(cli.ENV_KEY)
        os.environ[cli.ENV_KEY] = "sk-not-a-real-key"
        try:
            # A client is built, but it answers nothing, so every fact stays unknown.
            extractor = cli.build_extractor(False)
            self.assertIsNotNone(extractor)
            self.assertIsNone(extractor.hit_birth("He was born in 1950."))
        finally:
            if before is None:
                del os.environ[cli.ENV_KEY]
            else:
                os.environ[cli.ENV_KEY] = before


class TestRunOnATinyFolder(unittest.TestCase):
    def setUp(self):
        self.folder = tiny_folder()
        self.out = tempfile.mkdtemp(prefix="sponl-out-")

    def tearDown(self):
        self.folder.close()
        shutil.rmtree(self.out, ignore_errors=True)

    def test_it_writes_one_json_line_per_hit(self):
        target = os.path.join(self.out, "o.jsonl")
        cli.run(self.folder.path, target, quiet=True)
        with open(target, encoding="utf-8") as fh:
            lines = [json.loads(l) for l in fh if l.strip()]
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["hit_id"], "H-1")
        self.assertIn(lines[0]["decision"], model.DECISIONS)

    def test_it_creates_a_missing_output_directory(self):
        target = os.path.join(self.out, "deeper", "still", "o.jsonl")
        cli.run(self.folder.path, target, quiet=True)
        self.assertTrue(os.path.isfile(target))

    def test_the_report_names_the_counts_and_the_model(self):
        before = os.environ.get(cli.ENV_KEY)
        os.environ.pop(cli.ENV_KEY, None)
        buffer = io.StringIO()
        try:
            cli.run(self.folder.path, os.path.join(self.out, "o.jsonl"), out=buffer)
        finally:
            if before is not None:
                os.environ[cli.ENV_KEY] = before
        text = buffer.getvalue()
        self.assertIn("1 hits", text)
        self.assertIn("language model: not used", text)

    def test_quiet_prints_nothing(self):
        buffer = io.StringIO()
        cli.run(self.folder.path, os.path.join(self.out, "o.jsonl"), quiet=True, out=buffer)
        self.assertEqual(buffer.getvalue(), "")

    def test_an_unreadable_folder_exits_two_without_a_traceback(self):
        self.assertEqual(cli.main([os.path.join(self.out, "nope"), "x.jsonl"]), 2)


@unittest.skipUnless(os.path.isdir(FOLDER), "development data not present")
class TestRunOnTheDevelopmentSet(unittest.TestCase):
    """Driven through the executable, as the graders will drive it."""

    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.mkdtemp(prefix="sponl-run-")
        cls.target = os.path.join(cls.directory, "out.jsonl")
        # Run from another working directory, with no key in the environment.
        environment = dict(os.environ)
        environment.pop(cli.ENV_KEY, None)
        cls.result = subprocess.run(
            [RUN, FOLDER, cls.target],
            cwd=tempfile.gettempdir(),
            env=environment,
            capture_output=True,
            text=True,
        )
        with open(cls.target, encoding="utf-8") as fh:
            cls.rows = [json.loads(l) for l in fh if l.strip()]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.directory, ignore_errors=True)

    def test_it_succeeds(self):
        self.assertEqual(self.result.returncode, 0, self.result.stderr)
        self.assertEqual(self.result.stderr, "")

    def test_one_line_per_hit(self):
        self.assertEqual(len(self.rows), 819)

    def test_every_line_has_the_seven_fields_and_nothing_else(self):
        for row in self.rows:
            self.assertEqual(
                sorted(row),
                ["alert_id", "customer_record_id", "decision", "evidence", "hit_id",
                 "reason", "reason_code"],
            )

    def test_the_same_output_as_the_committed_file(self):
        with open(os.path.join(ROOT, "output", "dev.jsonl"), encoding="utf-8") as fh:
            committed = [json.loads(l) for l in fh if l.strip()]
        self.assertEqual(self.rows, committed)

    def test_the_report_says_the_model_was_not_used(self):
        self.assertIn("language model: not used", self.result.stdout)

    def test_no_llm_gives_the_same_answers(self):
        other = os.path.join(self.directory, "nollm.jsonl")
        environment = dict(os.environ)
        environment[cli.ENV_KEY] = "sk-not-a-real-key"
        result = subprocess.run(
            [RUN, FOLDER, other, "--no-llm", "--quiet"],
            cwd=tempfile.gettempdir(), env=environment, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        with open(other, encoding="utf-8") as fh:
            self.assertEqual([json.loads(l) for l in fh if l.strip()], self.rows)


if __name__ == "__main__":
    unittest.main(verbosity=2)
