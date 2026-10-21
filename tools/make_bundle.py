"""Build a self-contained kankuro bundle: a relocatable Python 3.13 with bpy + kankuro installed.

    python tools/make_bundle.py --wheel dist/kankuro-0.1.0-py3-none-any.whl --name kankuro-0.1.0-linux-x64

Writes dist/<name>.tar.gz (or .zip on Windows). Unpacked, it runs anywhere on that OS with no
Python or Blender installed:

    <name>/kankuro schema              (Linux / macOS)
    <name>\\kankuro.cmd schema          (Windows)

Needs `uv` on PATH (it downloads the python-build-standalone interpreter).
"""
import argparse
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

WIN = sys.platform == "win32"
PY_VERSION = "3.13"

SH_LAUNCHER = """#!/bin/sh
# kankuro launcher: runs the bundled Python with the kankuro CLI.
here="$(cd "$(dirname "$0")" && pwd)"
exec "$here/python/bin/python3" -I -m kankuro "$@"
"""

CMD_LAUNCHER = """@echo off
rem kankuro launcher: runs the bundled Python with the kankuro CLI.
"%~dp0python\\python.exe" -I -m kankuro %*
"""

README = """kankuro {version} ({name})
=========================

A self-contained build of the kankuro character creator CLI. It bundles Python {py} and
Blender's bpy module, so nothing else needs to be installed.

Run it from this folder (or add this folder to your PATH):

  Linux / macOS:   ./kankuro schema
  Windows:         kankuro.cmd schema

Docs: https://github.com/alokdidde/kankuro/tree/main/docs
"""


def run(cmd, **kw):
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, **kw)


def find_python(install_dir):
    for d in sorted(os.listdir(install_dir)):
        full = os.path.join(install_dir, d)
        if d.startswith(f"cpython-{PY_VERSION}.") and os.path.isdir(full) and not os.path.islink(full):
            return full
    raise SystemExit(f"no cpython-{PY_VERSION}.x found in {install_dir}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wheel", required=True, help="the kankuro wheel to install")
    ap.add_argument("--name", required=True, help="bundle folder/archive name, e.g. kankuro-0.1.0-linux-x64")
    ap.add_argument("--out", default="dist", help="output directory (default: dist)")
    ap.add_argument("--version", default="", help="version shown in the bundle README")
    a = ap.parse_args()

    wheel = os.path.abspath(a.wheel)
    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="kankuro-bundle-")
    root = os.path.join(tmp, a.name)
    os.makedirs(root)

    # 1. A relocatable interpreter from python-build-standalone (via uv).
    run(["uv", "python", "install", PY_VERSION, "--install-dir", os.path.join(tmp, "py"), "--no-bin"])
    pydir = os.path.join(root, "python")
    shutil.copytree(find_python(os.path.join(tmp, "py")), pydir, symlinks=True)
    lib = os.path.join(pydir, "Lib") if WIN else os.path.join(pydir, "lib", f"python{PY_VERSION}")
    for junk in ("EXTERNALLY-MANAGED", "test", "idlelib"):
        p = os.path.join(lib, junk)
        if os.path.isdir(p):
            shutil.rmtree(p)
        elif os.path.exists(p):
            os.remove(p)
    python = os.path.join(pydir, "python.exe") if WIN else os.path.join(pydir, "bin", "python3")

    # 2. kankuro + its dependencies (bpy, numpy, pillow) into that interpreter.
    run([python, "-I", "-m", "pip", "install", "--no-cache-dir", "--disable-pip-version-check", wheel])
    run([python, "-I", "-m", "pip", "check"])
    run([python, "-I", "-m", "kankuro", "--version"])

    # 3. Launchers and a README.
    for name in ("kankuro",):
        if WIN:
            with open(os.path.join(root, name + ".cmd"), "w", newline="\r\n") as f:
                f.write(CMD_LAUNCHER)
        else:
            path = os.path.join(root, name)
            with open(path, "w") as f:
                f.write(SH_LAUNCHER)
            os.chmod(path, 0o755)
    with open(os.path.join(root, "README.txt"), "w") as f:
        f.write(README.format(version=a.version, name=a.name, py=PY_VERSION))

    # 4. Archive: zip on Windows, tar.gz elsewhere (keeps symlinks and exec bits).
    if WIN:
        archive = os.path.join(out, a.name + ".zip")
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for dirpath, _, files in os.walk(root):
                for fn in files:
                    full = os.path.join(dirpath, fn)
                    z.write(full, os.path.relpath(full, tmp))
    else:
        archive = os.path.join(out, a.name + ".tar.gz")
        with tarfile.open(archive, "w:gz", compresslevel=6) as t:
            t.add(root, arcname=a.name)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"bundle: {archive} ({os.path.getsize(archive) / 2**20:.0f} MB)")


if __name__ == "__main__":
    main()
