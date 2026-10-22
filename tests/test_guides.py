"""The built-in help and guides: every command has help with examples, and guides match docs/."""
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def run(*args):
    env = dict(os.environ, PYTHONPATH=ROOT)
    return subprocess.run([sys.executable, "-m", "sasori", *args], capture_output=True, text=True, env=env, cwd=ROOT)


class Guides(unittest.TestCase):
    def test_guides_match_docs(self):
        from sasori.cli import GUIDES
        for fn, _ in GUIDES.values():
            with open(os.path.join(ROOT, "docs", fn), encoding="utf-8") as a, \
                    open(os.path.join(ROOT, "sasori", "guides", fn), encoding="utf-8") as b:
                self.assertEqual(a.read(), b.read(), f"sasori/guides/{fn} is stale: run python tools/sync_guides.py")

    def test_guide_prints_text(self):
        r = run("guide")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("sasori", r.stdout)
        self.assertFalse(r.stdout.lstrip().startswith("{"))
        r = run("guide", "nope")
        self.assertEqual(r.returncode, 2)
        self.assertIn("unknown_topic", r.stdout)

    def test_every_command_has_help_with_examples(self):
        from sasori import cli, helptext
        self.assertEqual(set(cli.COMMANDS), set(helptext.COMMANDS))
        top = run("--help")
        self.assertEqual(top.returncode, 0)
        self.assertIn("sasori guide", top.stdout)
        for name in cli.COMMANDS:
            r = run(name, "--help")
            self.assertEqual(r.returncode, 0, name)
            self.assertIn("examples:", r.stdout, name)
            self.assertNotIn("{", r.stdout.split("examples:")[1].replace("{\"", "").replace("{name", ""), name)


if __name__ == "__main__":
    unittest.main()
