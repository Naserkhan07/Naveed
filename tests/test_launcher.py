"""The launcher: `python main.py`.

The bot's front door. What matters here is that it behaves like a *person's* entry
point rather than a developer's: it finds Naveed wherever it is run from, it says
what is missing before a window opens, it does not invent a provider it cannot
see, and it passes everything else through to the real CLI.
"""

from __future__ import annotations

import importlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main as launcher  # noqa: E402  (the file under test, by design)

from naveed.config import Config, load_config  # noqa: E402


class PackagingTests(unittest.TestCase):
    """The install has to contain everything the code imports.

    `naveed.skills` was missing from `[tool.setuptools] packages`, which no test
    could notice on a cloned checkout (the directory is there) but which removed
    the Polarion pack and every learned routine from an installed copy.
    """

    def test_every_sub_package_is_listed_for_installation(self):
        import tomllib

        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        listed = set(pyproject["tool"]["setuptools"]["packages"])
        on_disk = {"naveed"}
        for path in (ROOT / "naveed").iterdir():
            if path.is_dir() and (path / "__init__.py").exists():
                on_disk.add(f"naveed.{path.name}")
        self.assertEqual(sorted(on_disk - listed), [], "these would be missing from a pip install")

    def test_the_console_scripts_point_at_real_callables(self):
        import tomllib

        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        scripts = pyproject["project"]["scripts"]
        self.assertIn("naveed", scripts)
        self.assertIn("naveed-web", scripts)
        for target in scripts.values():
            module_name, _, attribute = target.partition(":")
            module = importlib.import_module(module_name)
            self.assertTrue(callable(getattr(module, attribute)), target)

    def test_the_installers_do_not_ask_for_a_key(self):
        """The first thing a new user reads must not mention an API key.

        This is not hypothetical drift: the installers kept saying "paste your
        model key" long after Naveed had stopped having such a thing, because
        nothing checked the *text* a person actually reads. A wording test is the
        only thing that notices.
        """
        for name in ("scripts/install.sh", "scripts/install.ps1"):
            text = (ROOT / name).read_text(encoding="utf-8")
            lowered = text.lower()
            for phrase in ("model key", "api key", "api_key", "apikey"):
                self.assertNotIn(phrase, lowered, f"{name} still asks for a {phrase}")
            self.assertNotIn(
                "--setup --force --provider", text,
                f"{name} writes a starter config for a provider that may want a key",
            )
            self.assertIn("--setup --force", text, f"{name} must still write a starter config")
            self.assertIn("no key", lowered, f"{name} should say outright that there is none")
            self.assertIn("llm", lowered, f"{name} should talk about the LLM API")

    def test_the_shipped_example_names_an_llm_api_and_no_key(self):
        text = (ROOT / "examples" / "config.env.example").read_text(encoding="utf-8")
        active = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
        self.assertTrue(any(line.startswith("LLM_API=") for line in active), active)
        self.assertTrue(any(line.startswith("LLM_MODEL=") for line in active), active)
        for line in active:
            name = line.split("=", 1)[0].strip().upper()
            for banned in ("API_KEY", "APIKEY", "LLM_KEY", "OPENAI_KEY"):
                self.assertNotIn(banned, name, f"a credential setting survived in {line!r}")
        self.assertTrue(
            all(not line.startswith("LLM_TOKEN=") for line in active),
            "the token line must stay commented out: it is optional, and never asked for",
        )

    def test_the_versions_agree(self):
        import tomllib

        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        import naveed

        self.assertEqual(pyproject["project"]["version"], naveed.__version__)


class ImportTests(unittest.TestCase):
    def test_it_is_importable_and_knows_where_it_lives(self):
        self.assertEqual(launcher.REPO_ROOT, ROOT)
        self.assertTrue((ROOT / "naveed" / "__init__.py").exists())

    def test_it_finds_naveed_from_another_directory(self):
        """Double-clicking a shortcut can run with any working directory."""
        script = (
            "import sys; sys.path.insert(0, %r); import main; "
            "main._make_importable(); import naveed; print(naveed.__version__)" % str(ROOT)
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=tempfile.gettempdir(),
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.strip())

    def test_check_passes_through_to_the_cli(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "main.py"), "--check"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Naveed", result.stdout)
        self.assertIn("llm api", result.stdout)


class FirstRunTests(unittest.TestCase):
    """It writes a config only when an LLM API is *obviously* available."""

    def test_it_writes_nothing_when_no_model_is_reachable(self):
        with tempfile.TemporaryDirectory() as home:
            config = Config(home=home)
            with mock.patch("naveed.agent.llm.LLMClient.probe", return_value=(False, "nothing is answering")):
                with redirect_stdout(io.StringIO()):
                    launcher._default_setup_if_possible(config)
            self.assertFalse(
                (Path(home) / "config.env").exists(),
                "guessing a provider that is not reachable would be worse than asking",
            )

    def test_it_uses_a_local_ollama_it_can_actually_reach(self):
        with tempfile.TemporaryDirectory() as home:
            config = Config(home=home)
            with mock.patch("naveed.agent.llm.LLMClient.probe", return_value=(True, "127.0.0.1:11434 is answering")):
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    launcher._default_setup_if_possible(config)
            written = Path(home) / "config.env"
            self.assertTrue(written.exists(), "a reachable local model should give a working config")
            body = written.read_text(encoding="utf-8")
            self.assertIn("127.0.0.1:11434", body)
            self.assertIn("LLM API: ollama", buffer.getvalue())

    def test_it_uses_an_llm_api_given_in_the_environment(self):
        """The endpoint is the configuration — there is no key to look for."""
        with tempfile.TemporaryDirectory() as home:
            config = Config(home=home)
            environment = {"LLM_API": "http://127.0.0.1:8080/v1", "LLM_MODEL": "my-small-model"}
            with mock.patch.dict(os.environ, environment), redirect_stdout(io.StringIO()):
                launcher._default_setup_if_possible(config)
            body = (Path(home) / "config.env").read_text(encoding="utf-8")
            self.assertIn("LLM_API=http://127.0.0.1:8080/v1", body)
            self.assertIn("LLM_MODEL=my-small-model", body)
            self.assertNotIn("API_KEY", body, "a key is not a concept in this project")

    def test_it_never_overwrites_an_existing_config(self):
        with tempfile.TemporaryDirectory() as home:
            written = Path(home) / "config.env"
            written.write_text("# mine\nLLM_MODEL=my-choice\n", encoding="utf-8")
            config = load_config(env_file=str(written), use_environment=False, ensure_dirs=False)
            with mock.patch.dict(os.environ, {"LLM_API": "http://127.0.0.1:8080/v1"}), redirect_stdout(io.StringIO()):
                launcher._default_setup_if_possible(config)
            self.assertIn("my-choice", written.read_text(encoding="utf-8"))

    def test_the_hints_name_what_is_missing_and_the_command_that_fixes_it(self):
        config = Config()
        buffer = io.StringIO()
        with mock.patch("naveed.lazy.find_spec_safe", return_value=None), redirect_stdout(buffer):
            launcher._first_run_hints(config)
        text = buffer.getvalue()
        self.assertIn("PySide6", text)
        self.assertIn("screen-capture", text)
        self.assertIn("input backend", text)
        self.assertIn('pip install "naveed[ui,capture,input]"', text)
        self.assertIn("--setup --provider ollama", text)

    def test_a_configured_machine_is_not_nagged_about_the_api(self):
        config = Config()
        config.source_file = "/tmp/config.env"      # there is a config already
        config.llm.base_url = "http://127.0.0.1:11434/v1"
        config.llm.model = "qwen2.5vl:7b"
        buffer = io.StringIO()
        with mock.patch("naveed.lazy.find_spec_safe", return_value=object()), redirect_stdout(buffer):
            launcher._first_run_hints(config)
        text = buffer.getvalue()
        self.assertNotIn("point me at a different one", text)
        self.assertNotIn("no model yet", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
