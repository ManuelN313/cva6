#!/usr/bin/env python3
"""Move files between this checkout and the project's containers.

Pulling asks which of the run-output folders to bring back Pushing
sends the drivers, configurations and tests back in, which is the step whose
absence makes a container quietly run last week's script.

    python3 docker_sync.py                  # pull, both containers
    python3 docker_sync.py gem5             # pull, one container
    python3 docker_sync.py --push cva6      # push the sources in
    python3 docker_sync.py gem5 --jsons     # pull, then trace
    python3 docker_sync.py --list           # show, copy nothing
    python3 docker_sync.py gem5 --all -y    # every folder, no ask
"""
import argparse
import importlib.util
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)          # this script lives in scripts/

# Where a pulled folder lands, unless --out-dir says otherwise.
DEFAULT_OUT_DIR = "container_results"

# The cleaners list every folder a run leaves behind, which is not the same as
# every folder worth carrying home. A build tree is remade by the next run and
# runs to gigabytes, so it never reaches the menu.
NEVER_PULL = {"work-ver", "work-dpi", "build", "__pycache__"}

# Which folders each flow produces is already written down, with a reason for
# each, in the cleaners. Read from there so this script cannot drift from them.
CONTAINERS = {
    "gem5": {
        "root": "/gem5",
        "cleaner": "viewers/MinorFlow/scripts/clean_gem5_runs.py",
        # Mirrors the COPY lines in dockerfiles/gem5/Dockerfile.
        "push": [
            ("viewers/MinorFlow/scripts/run_gem5.py", "/gem5/"),
            ("viewers/MinorFlow/scripts/run_all_gem5_benchmarks.py", "/gem5/"),
            ("viewers/MinorFlow/scripts/clean_gem5_runs.py", "/gem5/"),
            ("gem5_config_CVA6/gem5/configs/.", "/gem5/"),
            ("viewers/MinorFlow/.", "/gem5/viewers/MinorFlow/"),
            ("dockerfiles/serve_viewers.py", "/gem5/serve_viewers.py"),
        ],
        "push_globs": [("gem5_config_CVA6/gem5/benchmarks", (".c", ".S"),
                        "/gem5/benchmarks/")],
        "jsons": "viewers/MinorFlow/scripts/create_all_MinorFlow_jsons.py",
    },
    "cva6": {
        "root": "/cva6",
        "cleaner": "viewers/CVA6Flow/scripts/clean_CVA6_runs.py",
        # Mirrors the layout dockerfiles/CVA6/Dockerfile builds: the drivers
        # sit at /cva6 and the tests in /cva6/benchmarks.
        "push": [
            ("viewers/CVA6Flow/scripts/run_CVA6.py", "/cva6/"),
            ("viewers/CVA6Flow/scripts/run_all_CVA6_benchmarks.py", "/cva6/"),
            ("viewers/CVA6Flow/scripts/clean_CVA6_runs.py", "/cva6/"),
            ("viewers/CVA6Flow/.", "/cva6/viewers/CVA6Flow/"),
            ("dockerfiles/serve_viewers.py", "/cva6/serve_viewers.py"),
        ],
        "push_globs": [("gem5_config_CVA6/CVA6/benchmarks", (".c", ".S"),
                        "/cva6/benchmarks/")],
        "jsons": "viewers/CVA6Flow/scripts/create_all_CVA6Flow_jsons.py",
    },
}


def load_cleaner(rel):
    """Import a cleaner for its folder tables, without running it."""
    path = os.path.join(REPO, rel)
    spec = importlib.util.spec_from_file_location("cleaner", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def candidates(name):
    """[(path relative to the container root, why it exists)], from the
    cleaner that already knows this flow's output folders."""
    spec = CONTAINERS[name]
    try:
        cleaner = load_cleaner(spec["cleaner"])
    except (OSError, ImportError) as e:
        print(f"[WARN] Could not read {spec['cleaner']}: {e}")
        return []
    out = [(d, why) for d, why in cleaner.ROOT_DIRS.items()
           if d not in NEVER_PULL]
    out += [(d, why) for d, why in cleaner.SIBLING_DIRS.items()
            if d not in NEVER_PULL]
    if getattr(cleaner, "OUT_GLOB", None):
        out.append((cleaner.OUT_GLOB, cleaner.OUT_REASON))
    return out


def docker(args, **kwargs):
    return subprocess.run(["docker"] + args, **kwargs)


def running(name):
    r = docker(["inspect", "-f", "{{.State.Running}}", name],
               capture_output=True, text=True)
    return r.returncode == 0 and r.stdout.strip() == "true"


def ensure_running(name, assume_yes):
    """A stopped container cannot be looked into. Offer to start it."""
    if running(name):
        return True
    print(f"[INFO] '{name}' is not running.")
    if not assume_yes:
        # Starting a container is a change to the machine, so it is never done
        # on its own. Without a terminal to ask, say so and leave it alone.
        if not sys.stdin.isatty():
            print(f"[INFO] Skipping '{name}'. Start it, or pass -y.")
            return False
        try:
            if input("  Start it? [Y/n] ").strip().lower() in ("n", "no"):
                return False
        except (EOFError, KeyboardInterrupt):
            print()
            return False
    if docker(["start", name], capture_output=True).returncode != 0:
        print(f"[ERROR] Could not start '{name}'")
        return False
    print(f"[INFO] Started '{name}'")
    return True


def container_exists(name):
    r = docker(["ps", "-a", "--format", "{{.Names}}"],
               capture_output=True, text=True)
    if r.returncode != 0:
        return None
    return name in r.stdout.split()


def present(name):
    """[(path, size)] for the candidate folders that exist in the container.

    One `docker exec` for the whole list: a container that is not running has
    to be started for exec, so asking once keeps that to a single wake-up."""
    spec = CONTAINERS[name]
    paths = [p for p, _ in candidates(name)]
    if not paths:
        return []
    # The trailing exit 0 matters: the loop's status is that of its last
    # test, so a run whose last candidate is absent would look like a failure.
    script = (f"cd {spec['root']} 2>/dev/null || exit 0; "
              "for d in " + " ".join(paths) + "; do "
              "[ -e \"$d\" ] && du -sh \"$d\" 2>/dev/null; done; exit 0")
    r = docker(["exec", name, "sh", "-c", script],
               capture_output=True, text=True)
    if r.returncode != 0:
        print(f"[ERROR] Could not look inside '{name}'"
              + (f": {r.stderr.strip().splitlines()[0]}" if r.stderr.strip()
                 else ""))
        return None
    found = []
    for line in r.stdout.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2:
            found.append((parts[1].strip(), parts[0]))
    return found


def choose(found, reasons, assume_all):
    """Ask which folders to pull. Returns the chosen paths."""
    print()
    for i, (path, size) in enumerate(found, 1):
        why = reasons.get(path, reasons.get(path.split("/")[0], ""))
        print(f"  {i:2}. {path:32} {size:>7}   {why}")
    if assume_all:
        return [p for p, _ in found]
    if not sys.stdin.isatty():
        # Nothing to read from, so listing is all this can honestly do.
        print("\n  Not a terminal, so nothing is chosen. Use --all to pull "
              "every folder.")
        return []
    print("\n  Numbers separated by spaces, 'a' for all, or Enter to skip.")
    try:
        reply = input("  Pull: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return []
    if not reply:
        return []
    if reply in ("a", "all"):
        return [p for p, _ in found]
    chosen = []
    for token in reply.replace(",", " ").split():
        if token.isdigit() and 1 <= int(token) <= len(found):
            chosen.append(found[int(token) - 1][0])
        else:
            print(f"[WARN] Ignoring '{token}'")
    return chosen


def pull(name, out_dir, assume_all, list_only):
    spec = CONTAINERS[name]
    found = present(name)
    if found is None:
        return []
    if not found:
        print(f"[INFO] {name}: nothing to pull, no run output in "
              f"{spec['root']}")
        return []
    reasons = dict(candidates(name))
    print(f"\n=== {name} ({spec['root']}) ===")
    chosen = choose(found, reasons, assume_all or list_only)
    if list_only:
        return []

    pulled = []
    for path in chosen:
        target = os.path.join(out_dir, name)
        os.makedirs(target, exist_ok=True)
        source = f"{name}:{spec['root']}/{path}"
        print(f"[INFO] {source} -> {target}/")
        if docker(["cp", source, target + os.sep]).returncode == 0:
            pulled.append(os.path.join(target, os.path.basename(path)))
        else:
            print(f"[WARN] Could not copy {path}")
    return pulled


def push(name, dry_run):
    """Send the drivers, configurations and tests back into the container."""
    spec = CONTAINERS[name]
    items = list(spec["push"])
    for folder, exts, dest in spec.get("push_globs", []):
        base = os.path.join(REPO, folder)
        if os.path.isdir(base):
            items += [(os.path.join(folder, f), dest)
                      for f in sorted(os.listdir(base))
                      if f.endswith(exts)]

    print(f"\n=== {name}: pushing {len(items)} item(s) ===")
    failed = 0
    for rel, dest in items:
        source = os.path.join(REPO, rel)
        if not os.path.exists(source.rstrip("/.")):
            print(f"[WARN] {rel} does not exist here, skipped")
            continue
        print(f"[INFO] {rel} -> {name}:{dest}")
        if dry_run:
            continue
        # The destination folder may not exist yet in a hand-made container.
        docker(["exec", name, "mkdir", "-p", os.path.dirname(dest.rstrip("/"))
                or "/"], capture_output=True)
        if docker(["cp", source, f"{name}:{dest}"]).returncode != 0:
            print(f"[WARN] Could not copy {rel}")
            failed += 1
    return failed


def make_jsons(name, pulled, jobs):
    """Run the viewer's batch tracer over each folder that came back."""
    script = os.path.join(REPO, CONTAINERS[name]["jsons"])
    if not os.path.isfile(script):
        print(f"[WARN] {CONTAINERS[name]['jsons']} not found, "
              f"skipping --jsons")
        return
    for folder in pulled:
        if not os.path.isdir(folder):
            continue
        print(f"\n[INFO] Tracing {folder}")
        subprocess.run([sys.executable, script, folder, "-j", str(jobs)])


def main():
    parser = argparse.ArgumentParser(
        description="Copy run output out of the project's containers, and the "
                    "drivers back in.")
    # No choices= here: with nargs="*" argparse validates its own empty
    # default against them and rejects it, so the names are checked below.
    parser.add_argument("container", nargs="*", metavar="CONTAINER",
                        help=f"Which container to work on, "
                             f"{' or '.join(sorted(CONTAINERS))}. Defaults to "
                             f"both")
    parser.add_argument("--push", action="store_true",
                        help="Send the drivers, configurations and tests into "
                             "the container instead of pulling results out")
    parser.add_argument("--jsons", action="store_true",
                        help="After pulling, run the viewer's batch tracer "
                             "over every folder that came back")
    parser.add_argument("-j", "--jobs", type=int, default=4, metavar="N",
                        help="Traces to convert at a time with --jsons")
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR, metavar="DIR",
                        help=f"Where pulled folders land. Defaults to "
                             f"{DEFAULT_OUT_DIR}/<container>/")
    parser.add_argument("--all", action="store_true",
                        help="Pull everything without asking")
    parser.add_argument("-y", "--yes", action="store_true",
                        help="Alias for --all, and skips the push "
                             "confirmation")
    parser.add_argument("--list", action="store_true",
                        help="Show what each container holds and copy nothing")
    parser.add_argument("--dry-run", action="store_true",
                        help="With --push, name every file without copying it")
    args = parser.parse_args()

    probe = subprocess.run(["which", "docker"], capture_output=True)
    if probe.returncode != 0:
        print("[ERROR] docker is not on PATH")
        return 2

    unknown = [n for n in args.container if n not in CONTAINERS]
    if unknown:
        print(f"[ERROR] No such container: {', '.join(unknown)}. "
              f"Known: {', '.join(sorted(CONTAINERS))}")
        return 2
    names = args.container or sorted(CONTAINERS)
    missing = [n for n in names if container_exists(n) is False]
    if missing:
        print(f"[ERROR] No container named {', '.join(missing)}. "
              f"See the README for how to create one.")
        names = [n for n in names if n not in missing]
    if not names:
        return 2

    if args.push:
        if not (args.yes or args.dry_run):
            print(f"[INFO] This overwrites the drivers inside "
                  f"{', '.join(names)} with the ones in this checkout.")
            try:
                if input("  Continue? [y/N] ").strip().lower() not in ("y",
                                                                      "yes"):
                    return 0
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
        return 1 if sum(push(n, args.dry_run) for n in names) else 0

    out_dir = os.path.abspath(args.out_dir)
    total = []
    names = [n for n in names if ensure_running(n, args.yes)]
    for name in names:
        total += pull(name, out_dir, args.all or args.yes, args.list)
    if args.list:
        return 0
    if not total:
        print("\n[INFO] Nothing copied")
        return 0
    print(f"\n[INFO] {len(total)} folder(s) now under {out_dir}")
    if args.jsons:
        for name in names:
            mine = [p for p in total if f"{os.sep}{name}{os.sep}" in p]
            make_jsons(name, mine, args.jobs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
