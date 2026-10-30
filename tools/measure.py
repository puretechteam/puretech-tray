# puretech-tray - (C) 2025 Pure Tech
# Licensed under the MIT License

"""Measure puretech-tray against pystray: import time, RAM, threads, icon-update latency, installed size.

    python tools/measure.py [--runs 7] [--out docs/perf.json] [--site <site-packages with puretech_tray installed>]

Every number comes from fresh subprocesses of the same interpreter, alternating the two libraries. pystray and
Pillow must be importable (Pillow draws the identical test icons for both)."""

import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

IMPORT_SNIPPET = r"""
import sys, time
{pre}
t = time.perf_counter()
import {mod}
print((time.perf_counter() - t) * 1000)
"""

RUN_SNIPPET = r"""
import ctypes, json, sys, time
from ctypes import wintypes
sys.path.insert(0, {root!r})
from PIL import Image, ImageDraw

class PMC(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + \
               [(n, ctypes.c_size_t) for n in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage",
                "PeakPagefileUsage", "PrivateUsage")]

class TE32(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ThreadID", wintypes.DWORD),
                ("th32OwnerProcessID", wintypes.DWORD), ("tpBasePri", wintypes.LONG), ("tpDeltaPri", wintypes.LONG),
                ("dwFlags", wintypes.DWORD)]

k32 = ctypes.WinDLL("kernel32")
psapi = ctypes.WinDLL("psapi")
k32.GetCurrentProcess.restype = wintypes.HANDLE
k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
k32.Thread32First.argtypes = k32.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
k32.CloseHandle.argtypes = [wintypes.HANDLE]

def mem():
    pmc = PMC(); pmc.cb = ctypes.sizeof(PMC)
    psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
    return pmc.PrivateUsage, pmc.WorkingSetSize

def threads():
    snap = k32.CreateToolhelp32Snapshot(4, 0)
    te = TE32(); te.dwSize = ctypes.sizeof(TE32)
    pid, n = k32.GetCurrentProcessId(), 0
    ok = k32.Thread32First(snap, ctypes.byref(te))
    while ok:
        n += te.th32OwnerProcessID == pid
        ok = k32.Thread32Next(snap, ctypes.byref(te))
    k32.CloseHandle(snap)
    return n

def draw(color, mark=0):
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((4, 4, 60, 60), fill="#0E1014", outline="#2A2F38", width=3)
    d.ellipse((18, 18, 46, 46), fill=color)
    if mark:
        d.point((mark % 64, mark // 64 % 64), fill="#FFFFFF")
    return img

states = [draw(c) for c in ("#FF4D5E", "#FBBF24", "#A78BFA", "#8C93A1")]
fresh = [draw("#FF4D5E", i + 1) for i in range({fresh})]
time.sleep(0.3)
base_priv, base_ws = mem()
base_threads = threads()

t0 = time.perf_counter()
if {lib!r} == "pystray":
    import pystray
    icon = pystray.Icon("measure", states[0], "measure", pystray.Menu(pystray.MenuItem("Quit", lambda: None)))
    icon.run_detached()
    while not icon.visible:
        time.sleep(0.001)
    def set_icon(img): icon.icon = img
    stop = icon.stop
else:
    import puretech_tray as pt
    tray = pt.Tray(states[0], "measure", pt.Menu(pt.Item("Quit", None))).start()
    def set_icon(img): tray.update(icon=img)
    stop = tray.stop
startup_ms = (time.perf_counter() - t0) * 1000
time.sleep(1.0)
priv, ws = mem()
nthreads = threads()

def timed(seq):
    out = []
    for img in seq:
        t = time.perf_counter()
        set_icon(img)
        out.append((time.perf_counter() - t) * 1000)
    return out

states_ms = timed([states[i % 4] for i in range({updates})])
fresh_ms = timed(fresh)
stop()
print(json.dumps(dict(startup_ms=startup_ms, private_kb=(priv - base_priv) / 1024, working_set_kb=(ws - base_ws) / 1024,
                      threads_added=nthreads - base_threads, threads_total=nthreads, states_ms=states_ms, fresh_ms=fresh_ms)))
"""


def py(code, env=None):
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=120)
    if out.returncode:
        raise RuntimeError(out.stderr)
    return out.stdout.strip().splitlines()[-1]


def median(xs):
    return round(statistics.median(xs), 2)


def p95(xs):
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(len(xs) * 0.95))], 3)


def tree_size(paths):
    total = 0
    for p in paths:
        if os.path.isfile(p):
            total += os.path.getsize(p)
            continue
        for d, dirs, files in os.walk(p):
            dirs[:] = [x for x in dirs if x != "__pycache__"]
            total += sum(os.path.getsize(os.path.join(d, f)) for f in files)
    return total


def installed_sizes(our_site):
    import importlib.metadata as md
    def dist_paths(name, site):
        dist = md.distribution(name) if site is None else next(md.distributions(name=name, path=[site]))
        base = dist.locate_file("")
        tops = {str(f).split("/")[0].split("\\")[0] for f in dist.files if "__pycache__" not in str(f)}
        return [os.path.join(base, t) for t in tops]
    pystray = tree_size(dist_paths("pystray", None))
    six = tree_size(dist_paths("six", None))
    pillow = tree_size(dist_paths("pillow", None))
    ours = tree_size(dist_paths("puretech-tray", our_site)) if our_site else None
    return dict(pystray_bytes=pystray, six_bytes=six, pystray_plus_six_bytes=pystray + six, pillow_bytes=pillow,
                puretech_tray_bytes=ours)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=7)
    ap.add_argument("--updates", type=int, default=200)
    ap.add_argument("--fresh", type=int, default=50)
    ap.add_argument("--out", default=os.path.join(ROOT, "docs", "perf.json"))
    ap.add_argument("--site", help="site-packages of a scratch venv where the built wheel is installed")
    args = ap.parse_args()

    env = dict(os.environ, PYTHONPATH=ROOT)
    results = {"pystray": {}, "puretech_tray": {}}
    for label, pre in (("import_cold_ms", ""), ("import_with_pil_ms", "import PIL.Image")):
        for name in results:
            results[name][label] = []
        for _ in range(args.runs * 2):
            for name in results:
                results[name][label].append(float(py(IMPORT_SNIPPET.format(pre=pre, mod=name), env)))
    for name in results:
        for key in ("startup_ms", "private_kb", "working_set_kb", "threads_added", "threads_total", "states_ms", "fresh_ms"):
            results[name][key] = []
    for _ in range(args.runs):
        for name in results:
            r = json.loads(py(RUN_SNIPPET.format(root=ROOT, lib=name,
                                                 updates=args.updates, fresh=args.fresh), env))
            for k, v in r.items():
                results[name][k] += v if isinstance(v, list) else [v]
            time.sleep(0.5)

    summary = {}
    for name, r in results.items():
        summary[name] = {
            "import_cold_ms": median(r["import_cold_ms"]),
            "import_with_pil_ms": median(r["import_with_pil_ms"]),
            "startup_to_visible_ms": median(r["startup_ms"]),
            "private_bytes_added_kb": median(r["private_kb"]),
            "working_set_added_kb": median(r["working_set_kb"]),
            "threads_added": median(r["threads_added"]),
            "icon_update_states_median_ms": round(statistics.median(r["states_ms"]), 3),
            "icon_update_states_p95_ms": p95(r["states_ms"]),
            "icon_update_fresh_median_ms": round(statistics.median(r["fresh_ms"]), 3),
            "icon_update_fresh_p95_ms": p95(r["fresh_ms"]),
        }
    summary["installed"] = installed_sizes(args.site)
    import pystray  # noqa: F401  (version only)
    import importlib.metadata as md
    summary["setup"] = {
        "date": time.strftime("%Y-%m-%d"), "python": platform.python_version(), "windows": platform.version(),
        "machine": platform.processor(), "pystray": md.version("pystray"), "six": md.version("six"),
        "pillow": md.version("pillow"), "runs": args.runs, "updates_per_run": args.updates,
        "fresh_updates_per_run": args.fresh,
        "method": "fresh subprocess per sample, libraries alternated; medians. RAM and threads are deltas from a "
                  "baseline taken after Pillow drew the test icons, measured 1 s after the icon became visible. "
                  "'states' cycles 4 pre-drawn icons (the FrameKeep pattern); 'fresh' sets 50 never-seen icons. "
                  "Installed size counts package files and dist-info, without __pycache__.",
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
        f.write("\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
