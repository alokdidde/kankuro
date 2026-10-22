# Development, CI and releases

## Set up

```bash
git clone https://github.com/alokdidde/sasori && cd sasori
python3.13 -m venv .venv && source .venv/bin/activate     # bpy 5.2 needs Python 3.13
pip install -e .
python -m unittest discover tests -v                       # ~1-2 minutes, end to end
```

If an editable install isn't possible (some network filesystems), install the dependencies and use
`PYTHONPATH`:

```bash
pip install "bpy==5.2.*" numpy pillow
PYTHONPATH=. python -m sasori schema
```

## Code layout

```
sasori/cli.py            commands, argument parsing, JSON output
sasori/spec.py           character.json schema, presets, validation
sasori/morph.py          MakeHuman macro and detail morphs (numpy, no Blender)
sasori/catalog.py        hair styles and garment definitions
sasori/textures.py       skin map, UV templates
sasori/fabric.py         fabric relief: weave/stitch/fold height -> normal map, albedo bake
sasori/blender/*.py      body and skeleton fit, garments, hair, materials, render, anim, autorig, validate
sasori/data/             compiled CC0 assets (tools/build_data.py regenerates them)
tests/test_cli.py          end-to-end tests through the CLI
tools/build_data.py        rebuild sasori/data from MakeHuman and Mesh2Motion sources
tools/make_bundle.py       build a self-contained release bundle
tools/smoke_test.py        smoke-test an installed sasori or a bundle
```

House rules:

* Every command prints exactly one JSON object. Errors are `CliError(code, message, hint=...)`.
* Modules under `sasori/blender/` may import `bpy`; everything else must not, so spec commands
  stay instant.
* New garments and hair styles go in `catalog.py`.
* A new command or option needs its help in `sasori/helptext.py` (summary, description, examples,
  per-option help); `tests/test_guides.py` checks every command has examples.
* After editing a doc that `sasori guide` prints (agents, getting-started, cli-reference,
  character-spec, codex-textures, installation), run `python tools/sync_guides.py` to copy it into
  `sasori/guides/`; the tests fail if the copies drift.

## CI

[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) runs on every push to `main` and every
pull request:

* **Tests** on `ubuntu-latest`, `macos-latest` (Apple Silicon) and `windows-latest`, Python 3.13
  with `bpy==5.2.*`. pip's cache is keyed on `pyproject.toml`, so the ~300 MB bpy download is
  usually cached.
* **Wheel installs and runs**: builds the wheel, installs it in a clean venv and runs
  `tools/smoke_test.py` against the installed `sasori` command (catches missing package data).

## How multi-platform support works

sasori is pure Python, so it ships as **one wheel** (`py3-none-any`) that depends on `bpy`. The
platform-specific part is `bpy`, which Blender publishes on PyPI as per-platform wheels for Python
3.13 only: Linux x86-64, macOS arm64, Windows x86-64 and Windows arm64. So:

1. **pip / uv users** get the right `bpy` automatically. One wheel covers every platform.
2. **Bundles** are for people without Python 3.13. The release workflow builds one per platform
   on that platform's own GitHub runner: it takes a relocatable CPython 3.13 from
   [python-build-standalone](https://github.com/astral-sh/python-build-standalone) (via `uv`),
   pip-installs the sasori wheel into it, adds `sasori` / `sasori.cmd` launchers, and archives
   it. Each bundle is then unpacked and smoke-tested on the same runner before it's published.

Platforms bpy doesn't cover (Intel Macs, Linux ARM) can't be supported without building Blender
from source, so they use Docker or a VM (see [installation.md](installation.md#docker)).

A bundle is about 500 MB, mostly bpy. That's well under GitHub's 2 GB per-file release limit.

You can build a bundle locally for your own platform:

```bash
pip install build && python -m build --wheel
python tools/make_bundle.py --wheel dist/sasori-0.1.0-py3-none-any.whl --name sasori-0.1.0-linux-x64
python tools/smoke_test.py ./unpacked/sasori-0.1.0-linux-x64/sasori     # after extracting it
```

## Cutting a release

Releases are automatic. Every push to `main` (a merged pull request) checks the version in
`pyproject.toml`; if there is no GitHub release for it yet, it is published as `v<version>`.
Merges that keep the version only run that check, so nothing is rebuilt.

1. In the pull request, bump the version in **both** `pyproject.toml` (`version`) and
   `sasori/cli.py` (`VERSION`). The workflow refuses to release if they disagree.
2. Merge it. [`.github/workflows/release.yml`](../.github/workflows/release.yml) then:
   * runs the full test matrix,
   * builds the wheel and sdist,
   * builds and smoke-tests the four bundles in parallel,
   * creates the GitHub release and tag with all files, a download table, auto-generated notes,
     and `SHA256SUMS.txt` (and uploads to PyPI once that is switched on, below).

To release by hand instead, push a tag, or push `main` to the `release` branch (handy where tag
pushes aren't allowed):

```bash
git tag v0.4.0 && git push origin v0.4.0
# or
git push origin main:release
```

Pull requests that change packaging (`release.yml`, `tools/make_bundle.py`, `tools/smoke_test.py`,
`pyproject.toml`) run the same pipeline as a dry run, and so does **Actions > Release > Run workflow**
on any branch. The bundles appear as workflow artifacts instead of a release.

## Publishing to PyPI (optional, one-time setup)

The release workflow has a `pypi` job that's off until you turn it on. It uses PyPI
[trusted publishing](https://docs.pypi.org/trusted-publishers/), so no API token is stored.

1. Sign in to [pypi.org](https://pypi.org) and open
   [Publishing > Add a new pending publisher](https://pypi.org/manage/account/publishing/).
2. Fill in: PyPI project name `sasori`, owner `alokdidde`, repository `sasori`, workflow name
   `release.yml`, environment `pypi`.
3. In the GitHub repo: **Settings > Environments > New environment** named `pypi`.
4. **Settings > Secrets and variables > Actions > Variables**: add `PUBLISH_PYPI` = `true`.

The next release then also uploads the wheel and sdist to PyPI, and
`pip install sasori` / `uv tool install sasori` work everywhere.

## Updating Blender

bpy is pinned to `5.2.*` in `pyproject.toml`. To move to a newer Blender, change the pin (and the
Python version if that bpy needs a different one: update `requires-python`, the workflows'
`python-version`, and `PY_VERSION` in `tools/make_bundle.py`), run the tests on all three CI
platforms, and check renders by eye, since material and render output can shift between versions.
