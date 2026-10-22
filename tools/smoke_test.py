"""Smoke-test an installed sasori: build a dressed character, check the GLB, and autorig the reference body.

    python tools/smoke_test.py ./sasori-0.1.0-linux-x64/sasori        (a release bundle launcher)
    python tools/smoke_test.py sasori                                  (a pip install on PATH)
"""
import json
import os
import subprocess
import sys
import tempfile


def run(cli, *args):
    r = subprocess.run([cli, *args], capture_output=True, text=True)
    lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
    try:
        out = json.loads("".join(lines))
    except json.JSONDecodeError:
        sys.exit(f"`{' '.join(args)}` did not print JSON (exit {r.returncode}):\n{r.stdout}\n{r.stderr[-2000:]}")
    if not out.get("ok"):
        sys.exit(f"`{' '.join(args)}` failed: {json.dumps(out, indent=2)}")
    print(f"ok  {' '.join(args)}", flush=True)
    return out


def main():
    cli = sys.argv[1]
    if os.path.exists(cli):
        # cmd.exe misreads a relative "dir/sasori.cmd" as the command "dir" with a switch.
        cli = os.path.abspath(cli)
    tmp = tempfile.mkdtemp(prefix="sasori-smoke-")
    proj = os.path.join(tmp, "hero")
    run(cli, "schema")
    run(cli, "init", proj, "--preset", "athletic_male")
    run(cli, "-p", proj, "hair", "set", "short")
    run(cli, "-p", proj, "garment", "add", "tshirt", "--color", "#eeeeee")
    run(cli, "-p", proj, "garment", "add", "pants")
    out = run(cli, "-p", proj, "build", "--animations", "Idle_A")
    assert out["skeleton"]["bones"] == 66, out["skeleton"]
    v = run(cli, "validate", out["glb"])
    assert v["valid"], v["checks"]
    run(cli, "-p", proj, "render", "--views", "front", "--size", "128", "--samples", "2")
    ref = os.path.join(tmp, "ref.glb")
    run(cli, "reference-body", "--out", ref)
    r = run(cli, "autorig", ref, "--out", os.path.join(tmp, "rigged.glb"))
    assert run(cli, "validate", r["glb"])["valid"]
    print("smoke test passed")


if __name__ == "__main__":
    main()
