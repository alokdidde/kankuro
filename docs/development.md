# Development, CI and releases

## Set up

```bash
git clone https://github.com/alokdidde/kankuro && cd kankuro
python3.13 -m venv .venv && source .venv/bin/activate     # bpy 5.2 needs Python 3.13
pip install -e .
python -m unittest discover tests -v                       # ~1-2 minutes, end to end
```

If an editable install isn't possible (some network filesystems), install the dependencies and use
`PYTHONPATH`:

```bash
pip install "bpy==5.2.*" numpy pillow
PYTHONPATH=. python -m kankuro schema
```

## Code layout

```
kankuro/cli.py            commands, argument parsing, JSON output
kankuro/spec.py           character.json schema, presets, validation
kankuro/morph.py          MakeHuman macro and detail morphs (numpy, no Blender)
kankuro/catalog.py        hair styles and garment definitions
kankuro/textures.py       skin map, UV templates
kankuro/fabric.py         fabric relief: weave/stitch/fold height -> normal map, albedo bake
kankuro/blender/*.py      body and skeleton fit, garments, hair, materials, render, anim, autorig, validate
kankuro/data/             compiled CC0 assets (tools/build_data.py regenerates them)
tests/test_cli.py          end-to-end tests through the CLI
tools/build_data.py        rebuild kankuro/data from MakeHuman and Mesh2Motion sources
tools/make_bundle.py       build a self-contained release bundle
tools/smoke_test.py        smoke-test an installed kankuro or a bundle
```

House rules:

* Every command prints exactly one JSON object. Errors are `CliError(code, message, hint=...)`.
* Modules under `kankuro/blender/` may import `bpy`; everything else must not, so spec commands
  stay instant.
* New garments and hair styles go in `catalog.py`.
* A new command or option needs its help in `kankuro/helptext.py` (summary, description, examples,
  per-option help); `tests/test_guides.py` checks every command has examples.
* After editing a doc that `kankuro guide` prints (agents, getting-started, cli-reference,
  character-spec, codex-textures, installation), run `python tools/sync_guides.py` to copy it into
  `kankuro/guides/`; the tests fail if the copies drift.

## CI

[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) runs on every push to `main` and every
pull request:

* **Tests** on `ubuntu-latest`, `macos-latest` (Apple Silicon) and `windows-latest`, Python 3.13
  with `bpy==5.2.*`. pip's cache is keyed on `pyproject.toml`, so the ~300 MB bpy download is
  usually cached.
* **Wheel installs and runs**: builds the wheel, installs it in a clean venv and runs
  `tools/smoke_test.py` against the installed `kankuro` command (catches missing package data).

## How multi-platform support works

kankuro is pure Python, so it ships as **one wheel** (`py3-none-any`) that depends on `bpy`. The
platform-specific part is `bpy`, which Blender publishes on PyPI as per-platform wheels for Python
3.13 only: Linux x86-64, macOS arm64, Windows x86-64 and Windows arm64. So:

1. **pip / uv users** get the right `bpy` automatically. One wheel covers every platform.
2. **Bundles** are for people without Python 3.13. The release workflow builds one per platform
   on that platform's own GitHub runner: it takes a relocatable CPython 3.13 from
   [python-build-standalone](https://github.com/astral-sh/python-build-standalone) (via `uv`),
   pip-installs the kankuro wheel into it, adds `kankuro` / `kankuro.cmd` launchers, and archives
   it. Each bundle is then unpacked and smoke-tested on the same runner before it's published.

Platforms bpy doesn't cover (Intel Macs, Linux ARM) can't be supported without building Blender
from source, so they use Docker or a VM (see [installation.md](installation.md#docker)).

A bundle is about 500 MB, mostly bpy. That's well under GitHub's 2 GB per-file release limit.

You can build a bundle locally for your own platform:

```bash
pip install build && python -m build --wheel
python tools/make_bundle.py --wheel dist/kankuro-0.1.0-py3-none-any.whl --name kankuro-0.1.0-linux-x64
python tools/smoke_test.py ./unpacked/kankuro-0.1.0-linux-x64/kankuro     # after extracting it
```

## Cutting a release

1. Bump the version in **both** `pyproject.toml` (`version`) and `kankuro/cli.py` (`VERSION`).
   The workflow refuses to release if they or the tag disagree.
2. Commit and push to `main`, then either push a tag or push `main` to the `release` branch
   (which tags the release `v<version>` for you, handy where tag pushes aren't allowed):

   ```bash
   git tag v0.2.0 && git push origin main v0.2.0
   # or
   git push origin main:release
   ```

3. [`.github/workflows/release.yml`](../.github/workflows/release.yml) then:
   * runs the full test matrix,
   * builds the wheel and sdist,
   * builds and smoke-tests the four bundles in parallel,
   * creates the GitHub release with all files, a download table, auto-generated notes, and
     `SHA256SUMS.txt`.

Pull requests that change packaging (`release.yml`, `tools/make_bundle.py`, `tools/smoke_test.py`,
`pyproject.toml`) run the same pipeline as a dry run, and so does **Actions > Release > Run workflow**
on any branch. The bundles appear as workflow artifacts instead of a release.

## Publishing to PyPI (optional, one-time setup)

The release workflow has a `pypi` job that's off until you turn it on. It uses PyPI
[trusted publishing](https://docs.pypi.org/trusted-publishers/), so no API token is stored.

1. Sign in to [pypi.org](https://pypi.org) and open
   [Publishing > Add a new pending publisher](https://pypi.org/manage/account/publishing/).
2. Fill in: PyPI project name `kankuro`, owner `alokdidde`, repository `kankuro`, workflow name
   `release.yml`, environment `pypi`.
3. In the GitHub repo: **Settings > Environments > New environment** named `pypi`.
4. **Settings > Secrets and variables > Actions > Variables**: add `PUBLISH_PYPI` = `true`.

The next tagged release then also uploads the wheel and sdist to PyPI, and
`pip install kankuro` / `uv tool install kankuro` work everywhere.

## Updating Blender

bpy is pinned to `5.2.*` in `pyproject.toml`. To move to a newer Blender, change the pin (and the
Python version if that bpy needs a different one: update `requires-python`, the workflows'
`python-version`, and `PY_VERSION` in `tools/make_bundle.py`), run the tests on all three CI
platforms, and check renders by eye, since material and render output can shift between versions.
