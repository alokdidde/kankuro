# Installation

kankuro runs Blender as a Python module (`bpy`), headless, on the CPU. No GPU and no separate
Blender install are needed. There are two ways to install it.

| | Download a bundle | pip / uv |
|---|---|---|
| needs | nothing | Python 3.13 (uv can fetch it for you) |
| size | ~500 MB unpacked folder | same, in your Python environment |
| best for | trying it out, machines without Python, agents in a sandbox | developers, CI, use as a library |

## Supported platforms

kankuro itself is pure Python. The platform limits come from Blender's `bpy` wheels on PyPI, which
exist only for **Python 3.13** on:

| platform | bundle | pip / uv |
|---|---|---|
| Linux x86-64 (glibc 2.28+, e.g. Ubuntu 20.04+, Debian 11+, RHEL 8+) | `linux-x64.tar.gz` | yes |
| macOS on Apple Silicon (macOS 11+) | `macos-arm64.tar.gz` | yes |
| Windows x86-64 (10/11) | `windows-x64.zip` | yes |
| Windows on ARM | `windows-arm64.zip` | yes |
| macOS on Intel, Linux ARM (incl. Raspberry Pi), Alpine/musl | no | no `bpy` wheel |

On an unsupported machine, use Docker with a Linux x86-64 image, or a Linux x86-64 cloud VM.

## Option 1: download a bundle

Each bundle is a folder with its own Python 3.13, `bpy` and kankuro. Get it from the
[latest release](https://github.com/alokdidde/kankuro/releases/latest).

**Linux**

```bash
curl -LO https://github.com/alokdidde/kankuro/releases/latest/download/kankuro-VERSION-linux-x64.tar.gz
tar -xzf kankuro-*-linux-x64.tar.gz
./kankuro-*-linux-x64/kankuro schema
```

**macOS (Apple Silicon)**

```bash
curl -LO https://github.com/alokdidde/kankuro/releases/latest/download/kankuro-VERSION-macos-arm64.tar.gz
tar -xzf kankuro-*-macos-arm64.tar.gz
./kankuro-*-macos-arm64/kankuro schema
```

The bundle isn't signed by Apple. Downloading with `curl` avoids Gatekeeper. If you downloaded it
in a browser and macOS says the file "can't be opened", clear the quarantine flag once:

```bash
xattr -dr com.apple.quarantine kankuro-*-macos-arm64
```

**Windows (PowerShell)**

```powershell
Invoke-WebRequest -OutFile kankuro.zip https://github.com/alokdidde/kankuro/releases/latest/download/kankuro-VERSION-windows-x64.zip
Expand-Archive kankuro.zip -DestinationPath .
.\kankuro-*-windows-x64\kankuro.cmd schema
```

Replace `VERSION` with the release number (for example `0.1.0`), or download the file from the
release page.

**Put it on your PATH** so you can type `kankuro` anywhere:

```bash
# Linux / macOS: add to ~/.bashrc or ~/.zshrc
export PATH="$HOME/tools/kankuro-0.1.0-linux-x64:$PATH"
```

```powershell
# Windows: current user
[Environment]::SetEnvironmentVariable("Path", $env:Path + ";C:\tools\kankuro-0.1.0-windows-x64", "User")
```

The folder can be moved anywhere; the launchers find the bundled Python relative to themselves.

Check the download against `SHA256SUMS.txt` from the release if you want to be sure it's intact:
`sha256sum -c SHA256SUMS.txt --ignore-missing`.

## Option 2: pip or uv

### With uv (recommended)

[uv](https://docs.astral.sh/uv/) installs Python 3.13 for you if you don't have it, and keeps
kankuro in its own environment:

```bash
uv tool install --python 3.13 kankuro
# or straight from a release wheel:
uv tool install --python 3.13 https://github.com/alokdidde/kankuro/releases/download/v0.1.0/kankuro-0.1.0-py3-none-any.whl
# or the latest code on main:
uv tool install --python 3.13 git+https://github.com/alokdidde/kankuro
kankuro schema
```

### With pip

You need Python **3.13** exactly (bpy 5.2 is built for it). Use a virtual environment:

```bash
python3.13 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install kankuro                  # or the .whl from a release, or git+https://github.com/alokdidde/kankuro
kankuro schema
```

pip picks the right `bpy` wheel for your platform (about 200 to 400 MB).

> PyPI publishing is set up in the release workflow but switched on separately. Until a release
> says it's on PyPI, use the wheel URL or the `git+https` form.

### From a clone (development)

```bash
git clone https://github.com/alokdidde/kankuro
cd kankuro
python3.13 -m venv .venv && source .venv/bin/activate
pip install -e .
python -m unittest discover tests -v
```

## Check it works

```bash
kankuro init /tmp/test --preset female
kankuro -p /tmp/test garment add tshirt
kankuro -p /tmp/test build
kankuro validate /tmp/test/build/test.glb      # "valid": true
```

The first command that uses Blender takes a few extra seconds while `bpy` loads.

## Troubleshooting

| symptom | fix |
|---|---|
| `"code": "no_blender"` | `bpy` isn't installed in the Python running kankuro, or that Python isn't 3.13. Use a bundle, or `uv tool install --python 3.13 kankuro`. |
| `pip` says no matching distribution for `bpy==5.2.*` | your Python isn't 3.13, or your platform has no bpy wheel (see the table above) |
| Linux: `libX11.so.6`, `libXi.so.6`, `libXfixes.so.3`, `libxkbcommon.so.0`, `libSM.so.6` or `libGL.so.1` not found | bpy loads a few X11/GL libraries even headless. Debian/Ubuntu: `sudo apt-get install -y libx11-6 libxi6 libxrender1 libxfixes3 libxext6 libxkbcommon0 libsm6 libgl1`. Fedora/RHEL: `sudo dnf install -y libX11 libXi libXrender libXfixes libXext libxkbcommon libSM mesa-libGL` |
| macOS: "cannot be opened because the developer cannot be verified" | `xattr -dr com.apple.quarantine <bundle folder>` |
| Windows: "Windows protected your PC" | the bundle isn't code-signed; choose "More info" > "Run anyway", or unblock the zip before extracting (`Unblock-File kankuro.zip`) |
| A command fails with `"code": "internal"` | read `error.traceback`, and `build/blender.log` in the project. Please open an issue with both. |
| Renders are slow | lower `--samples` and `--size`; renders use Cycles on the CPU |

## Docker

On machines without a supported bpy wheel, a Linux x86-64 container works:

```dockerfile
FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
      libx11-6 libxi6 libxrender1 libxfixes3 libxext6 libxkbcommon0 libsm6 libgl1 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir git+https://github.com/alokdidde/kankuro
WORKDIR /work
ENTRYPOINT ["kankuro"]
```

```bash
docker build -t kankuro .
docker run --rm -v "$PWD:/work" kankuro init hero --preset male
```

On Apple Silicon add `--platform linux/amd64` to both commands (it runs under emulation, so it's
slower than the native macOS bundle).
