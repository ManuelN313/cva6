#!/usr/bin/env python3
"""Check the parts of the CVA6 fork this project owns.

Every check here caught a real defect at least once, and each was being run by
hand. Upstream OpenHW files are not touched: OWN_PATHS is the whole scope.

Each viewer has the same tool for its own repository, sharing this one's
helpers and check protocol: check_MinorFlow_repo.py and
check_CVA6Flow_repo.py.

    python3 scripts/check_CVA6_repo.py               # everything but the patch round trip
    python3 scripts/check_CVA6_repo.py --list        # name the checks and stop
    python3 scripts/check_CVA6_repo.py -k tests      # only checks whose name matches
    python3 scripts/check_CVA6_repo.py --patch-roundtrip   # also apply the patch (network)
"""
import argparse
import ast
import os
import re
import shutil
import subprocess
import sys
import tempfile

def repo_root():
    """The repository this script sits in, found by walking up to the nearest
    .git. The script lives in scripts/, so counting parents would be one more
    thing to fix the next time the tree moves."""
    here = os.path.dirname(os.path.abspath(__file__))
    path = here
    while True:
        if os.path.exists(os.path.join(path, ".git")):
            return path
        parent = os.path.dirname(path)
        if parent == path:
            return here
        path = parent


REPO = repo_root()

# This project's own files. Everything else in the fork is upstream OpenHW.
OWN_PATHS = (
    "scripts", "gem5_config_CVA6", "dockerfiles",
    "viewers/MinorFlow", "viewers/CVA6Flow", "viewers/FlowCompare.html",
    "README.md",
)

# Frozen artefacts. CARLA2026 is the evidence behind a published paper, so it
# is read-only by policy and must not be held to today's conventions.
FROZEN = ("docs/CARLA2026", "docs/old_versions", "docs/parser_phases")

# Scripts kept in two places so each repository is self-contained. They are one
# file, and a drift between the copies is a real bug: the container gets one
# and the host the other.
# After the reorganisation each driver has one home, in the viewer that owns
# it, so the only tool still kept in two places is this one: the same job for
# two repositories that each need their own .gitignore. Every script in the
# project has a distinct name, so the two copies differ where they name
# themselves, and only there. VIEWERS is what the comparison normalises away.
TWINS = (
    ("viewers/MinorFlow/scripts/ignore_big_MinorFlow_jsons.py",
     "viewers/CVA6Flow/scripts/ignore_big_CVA6Flow_jsons.py"),
)
VIEWERS = ("MinorFlow", "CVA6Flow")

# Calibration tables. Two entries that reduce to the same configuration are a
# silent no-op: the row runs, the sweep reports it, and it measures nothing.
TEST_TABLES = (
    "gem5_config_CVA6/gem5/configs/gem5_config_CVA6_testing.py",
    "gem5_config_CVA6/gem5/configs/gem5_config_CVA6_Patch_testing.py",
)

PATCH = "gem5_config_CVA6/gem5/configs/MinorCPU_CVA6.patch"
GEM5_TAG = "v25.0.0.1"
GEM5_RAW = f"https://raw.githubusercontent.com/gem5/gem5/{GEM5_TAG}/"

# Groups that are the same configuration on purpose, or were already so when
# this check was written. Anything not listed here is a new collapse and fails.
KNOWN_DUPLICATE_TESTS = {
    frozenset({47, 54}): "predates the check",
    frozenset({61, 65}): "predates the check",
    frozenset({66, 79}): "predates the check",
    frozenset({72, 81, 84}): "predates the check",
    frozenset({77, 78}): "predates the check",
    frozenset({95, 99}): "TEST 95 is the end of the structural I-side ramp, "
                         "so it is production by construction",
}

# The style is 79 columns, which most of the tree already keeps.
# Scripts named in our text that are not ours: gem5's and CVA6's own sources,
# and the placeholders an example needs. Anything else that does not exist is a
# rename someone did not finish.
EXTERNAL_SCRIPTS = {
    "BaseMinorCPU.py", "BranchPredictor.py", "Cache.py",   # gem5 sources
    "cva6.py",                                             # verif/sim driver
    "my_config.py",                                        # an example name
}

MAX_COLS = 79
WIDTH_BUDGET = 291


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def owned(pattern=None):
    """Our files, from git so ignored artefacts never reach a check."""
    out = []
    for root in OWN_PATHS:
        full = os.path.join(REPO, root)
        if os.path.isfile(full):
            out.append(root)
            continue
        if not os.path.isdir(full):
            continue
        # A submodule has its own index, so ask the right repository.
        # Its .git is a file rather than a directory, which is why this
        # is exists and not isdir: isdir skipped the submodules whole.
        inner = full if os.path.exists(os.path.join(full, ".git")) else REPO
        rel = "." if inner == full else root
        # --others --exclude-standard adds files not yet staged, respecting
        # .gitignore. Without it a freshly moved tree is invisible here, which
        # is exactly when the checks are worth most.
        r = subprocess.run(["git", "-C", inner, "ls-files", "--cached",
                            "--others", "--exclude-standard", rel],
                           capture_output=True, text=True)
        # Submodule paths come back relative to the submodule, so they
        # need the prefix here. A root of "." already is the repository.
        prefix = root + "/" if inner == full and root != "." else ""
        out += [prefix + p for p in r.stdout.split()]
    # git ls-files reports the index, which still carries files deleted in the
    # working tree. A mid-reorganisation checkout is exactly when this matters.
    out = [p for p in out if not any(f in p for f in FROZEN)
           and os.path.isfile(os.path.join(REPO, p))]
    if pattern:
        out = [p for p in out if p.endswith(pattern)]
    return sorted(set(out))


def read(rel):
    with open(os.path.join(REPO, rel), encoding="utf-8") as handle:
        return handle.read()


def literal(node):
    """A structural value: literals as themselves, calls and names as tags, so
    two entries can be compared without importing gem5."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Dict):
        return {literal(k): literal(v)
                for k, v in zip(node.keys, node.values)}
    if isinstance(node, (ast.Tuple, ast.List)):
        return tuple(literal(e) for e in node.elts)
    if isinstance(node, ast.Name):
        return f"<{node.id}>"
    if isinstance(node, ast.Call):
        return f"<{ast.unparse(node.func)}()>"
    return f"<{ast.unparse(node)}>"


def class_defaults(tree, class_name, prefix):
    """Attribute assignments in a class body, last in source order winning, the
    way execution leaves them."""
    found = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            hits = []
            for sub in ast.walk(node):
                if isinstance(sub, ast.Assign):
                    for target in sub.targets:
                        if (isinstance(target, ast.Attribute)
                                and ast.unparse(target).startswith(prefix)):
                            hits.append((sub.lineno, target.attr,
                                         literal(sub.value)))
            for _, key, value in sorted(hits):
                found[key] = value
    return found


# ---------------------------------------------------------------------------
# Checks. Each returns a list of failure messages, empty when it passes.
# ---------------------------------------------------------------------------
def check_twins():
    """The scripts kept in two places are still one file, bar their own name.

    Reported as a diff rather than a bare mismatch: after normalising the
    viewer name away, every remaining line is a real difference and worth
    seeing."""
    import difflib
    bad = []
    for a, b in TWINS:
        pa, pb = os.path.join(REPO, a), os.path.join(REPO, b)
        if not (os.path.isfile(pa) and os.path.isfile(pb)):
            bad.append(f"{a} or {b} is missing")
            continue

        def normalise(path):
            text = open(path, encoding="utf-8").read()
            for viewer in VIEWERS:
                text = text.replace(viewer, "<VIEWER>")
            return text.splitlines()

        diff = [line for line in difflib.unified_diff(
            normalise(pa), normalise(pb), a, b, lineterm="", n=0)
            if line.startswith(("+", "-")) and not line.startswith(("+++",
                                                                    "---"))]
        if diff:
            bad.append(f"{a} and {b} have drifted apart:")
            bad += [f"    {line}" for line in diff[:8]]
    return bad


def check_test_tables():
    """No two calibration entries reduce to the same configuration."""
    bad = []
    for rel in TEST_TABLES:
        try:
            tree = ast.parse(read(rel))
        except OSError:
            bad.append(f"{rel} is missing")
            continue
        tests = None
        for node in tree.body:
            if (isinstance(node, ast.Assign)
                    and getattr(node.targets[0], "id", "") == "TESTS"):
                tests = {literal(k): literal(v)
                         for k, v in zip(node.value.keys, node.value.values)}
        if not tests:
            bad.append(f"{rel} has no TESTS table")
            continue
        cpu_base = class_defaults(tree, "CVA6CPU", "self.")
        ic_base = class_defaults(tree, "CVA6CacheHierarchy",
                                 "self.l1icaches[i].")

        def effective(entry):
            _, cpu, l1i, l1d, dcache, icache, clk, mem, bpred = entry
            merged_cpu = dict(cpu_base)
            merged_cpu.update(cpu or {})
            merged_ic = dict(ic_base)
            merged_ic.update(icache or {})
            return (l1i, l1d, tuple(sorted(merged_cpu.items())),
                    tuple(sorted((dcache or {}).items())),
                    tuple(sorted(merged_ic.items())), clk, mem,
                    tuple(sorted((bpred or {}).items())))

        seen = {}
        for number in sorted(tests):
            try:
                seen.setdefault(effective(tests[number]), []).append(number)
            except (TypeError, ValueError):
                bad.append(f"{rel}: TEST {number} has an unreadable shape")
        for numbers in seen.values():
            if len(numbers) > 1 and frozenset(numbers) not in \
                    KNOWN_DUPLICATE_TESTS:
                names = ", ".join(f"TEST {n} ({tests[n][0]})" for n in numbers)
                bad.append(f"{os.path.basename(rel)}: same configuration in "
                           f"{names}. If that is deliberate, say why in "
                           f"KNOWN_DUPLICATE_TESTS")
    return bad


def check_pyflakes():
    """Every script we own is clean under pyflakes."""
    if subprocess.run([sys.executable, "-m", "pyflakes", "--version"],
                      capture_output=True).returncode != 0:
        return ["SKIP pyflakes is not installed (pip install pyflakes)"]
    files = [os.path.join(REPO, p) for p in owned(".py")]
    r = subprocess.run([sys.executable, "-m", "pyflakes"] + files,
                       capture_output=True, text=True)
    return [line for line in r.stdout.splitlines() if line.strip()]


def check_compiles():
    """Every script we own parses, gem5 configurations included."""
    bad = []
    for rel in owned(".py"):
        try:
            ast.parse(read(rel))
        except SyntaxError as e:
            bad.append(f"{rel}:{e.lineno}: {e.msg}")
    return bad


def is_cli(rel):
    """A script with a command line, as opposed to a gem5 configuration, which
    only runs inside gem5 and cannot answer --help here."""
    text = read(rel)
    if "import m5" in text or "from m5" in text or "from gem5" in text:
        return False
    return "argparse" in text and '__main__' in text


def check_help():
    """Every command-line script answers --help.

    It is the cheapest end-to-end test there is: it runs module-level code and
    builds the whole parser, which is where a missing import or an argument
    referenced but never added shows up."""
    bad = []
    for rel in owned(".py"):
        if not is_cli(rel):
            continue
        r = subprocess.run([sys.executable, os.path.join(REPO, rel), "--help"],
                           capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            first = (r.stderr.strip().splitlines() or ["no output"])[-1]
            bad.append(f"{rel} --help exited {r.returncode}: {first}")
    return bad


def check_patch_hunks():
    """Every hunk header in the patch matches the lines under it."""
    try:
        lines = read(PATCH).split("\n")
    except OSError:
        return [f"{PATCH} is missing"]
    bad, index = [], 0
    header = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
    while index < len(lines):
        match = header.match(lines[index])
        if not match:
            index += 1
            continue
        want_old = int(match.group(2) or 1)
        want_new = int(match.group(4) or 1)
        start, index = index, index + 1
        old = new = 0
        while index < len(lines) and (old < want_old or new < want_new):
            line = lines[index]
            if line.startswith("\\"):
                index += 1
                continue
            if line.startswith("-"):
                old += 1
            elif line.startswith("+"):
                new += 1
            elif line.startswith(" ") or line == "":
                old += 1
                new += 1
            else:
                break
            index += 1
        if old != want_old or new != want_new:
            bad.append(f"{PATCH}:{start + 1}: {lines[start].strip()} covers "
                       f"-{old}/+{new}")
    return bad


def check_patch_roundtrip():
    """The patch applies to pristine gem5 and reverts to a byte-identical tree.

    Only with --patch-roundtrip: it downloads the files the patch touches."""
    if not shutil.which("git"):
        return ["SKIP git is not on PATH"]
    patch = os.path.join(REPO, PATCH)
    paths = sorted({line[6:] for line in read(PATCH).split("\n")
                    if line.startswith("--- a/")})
    work = tempfile.mkdtemp(prefix="check_CVA6_repo_")
    try:
        for rel in paths:
            os.makedirs(os.path.join(work, os.path.dirname(rel)),
                        exist_ok=True)
            r = subprocess.run(["curl", "-sSfL", "-o",
                                os.path.join(work, rel), GEM5_RAW + rel],
                               capture_output=True, timeout=60)
            if r.returncode != 0:
                return [f"SKIP could not fetch {rel} from gem5 {GEM5_TAG}"]
        for args in (["init", "-q", "."], ["add", "-A"],
                     ["-c", "user.email=c@r", "-c", "user.name=c",
                      "commit", "-qm", "pristine"]):
            subprocess.run(["git", "-C", work] + args, capture_output=True)
        if subprocess.run(["git", "-C", work, "apply", patch],
                          capture_output=True).returncode != 0:
            return [f"{PATCH} does not apply to pristine gem5 {GEM5_TAG}"]
        if subprocess.run(["git", "-C", work, "apply", "-R", patch],
                          capture_output=True).returncode != 0:
            return [f"{PATCH} applies but does not revert"]
        r = subprocess.run(["git", "-C", work, "status", "--porcelain"],
                           capture_output=True, text=True)
        if r.stdout.strip():
            return [f"{PATCH} reverts to a tree that is not byte-identical"]
        return []
    finally:
        shutil.rmtree(work, ignore_errors=True)


def check_viewer_js():
    """The viewer pages' inline JavaScript parses."""
    if not shutil.which("node"):
        return ["SKIP node is not on PATH"]
    bad = []
    block = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.S)
    for rel in owned(".html"):
        scripts = block.findall(read(rel))
        if not scripts:
            continue
        handle, path = tempfile.mkstemp(suffix=".js")
        with os.fdopen(handle, "w") as out:
            out.write("\n;\n".join(scripts))
        r = subprocess.run(["node", "--check", path],
                           capture_output=True, text=True)
        os.unlink(path)
        if r.returncode != 0:
            first = (r.stderr.strip().splitlines() or ["parse error"])
            detail = next((x for x in first if "Error" in x), first[-1])
            bad.append(f"{rel}: {detail.strip()}")
    return bad


def check_links():
    """Every relative link in our markdown resolves."""
    bad = []
    link = re.compile(r"\]\(([^)\s]+)\)")
    for rel in owned(".md"):
        base = os.path.dirname(os.path.join(REPO, rel))
        for target in link.findall(read(rel)):
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            if not os.path.exists(os.path.join(base, target.split("#")[0])):
                bad.append(f"{rel}: {target}")
    return bad


def check_script_names():
    """Every script named in our docs, Dockerfiles and scripts exists."""
    import re
    known = {os.path.basename(p) for p in owned(".py")}
    bad = []
    for rel in owned():
        if not rel.endswith((".md", ".py", "Dockerfile")):
            continue
        for match in re.finditer(r"(?<![\w>])([A-Za-z][A-Za-z0-9_]*\.py)\b",
                                 read(rel)):
            name = match.group(1)
            if name in known or name in EXTERNAL_SCRIPTS:
                continue
            line = read(rel)[:match.start()].count("\n") + 1
            bad.append(f"{rel}:{line}: {name} does not exist here")
    return sorted(set(bad))


def check_dockerfiles():
    """Every COPY source in the images exists.

    A Dockerfile only fails at build time, which is an hour into the build, so
    a moved folder is worth catching here."""
    import glob
    bad = []
    for rel in owned("Dockerfile"):
        text = read(rel).replace("\\\n", " ")
        for line in text.splitlines():
            if not line.startswith("COPY "):
                continue
            for src in line.split()[1:-1]:
                if src.startswith("--"):
                    continue
                if not glob.glob(os.path.join(REPO, src)):
                    bad.append(f"{rel}: COPY {src} matches nothing")
    return bad


def check_formatting():
    """No trailing whitespace, a final newline, and no new over-long lines."""
    bad, wide = [], 0
    for rel in owned():
        if not rel.endswith((".py", ".md", ".sh", "Dockerfile")):
            continue
        text = read(rel)
        if text and not text.endswith("\n"):
            bad.append(f"{rel}: no newline at end of file")
        for number, line in enumerate(text.split("\n"), 1):
            if line != line.rstrip():
                bad.append(f"{rel}:{number}: trailing whitespace")
            if rel.endswith(".py") and len(line) > MAX_COLS:
                wide += 1
    if wide > WIDTH_BUDGET:
        bad.append(f"{wide} lines over {MAX_COLS} columns, up from "
                   f"{WIDTH_BUDGET}. Wrap the new ones, or raise "
                   f"WIDTH_BUDGET deliberately")
    elif WIDTH_BUDGET - wide >= 10:
        # Only worth saying after a real tidy-up. Wrapping one line while
        # working on something else should not produce a chore.
        bad.append(f"SKIP {wide} lines over {MAX_COLS} columns, down from "
                   f"{WIDTH_BUDGET}. Lower WIDTH_BUDGET to hold the gain")
    return bad


CHECKS = (
    ("twins", check_twins),
    ("test-tables", check_test_tables),
    ("compiles", check_compiles),
    ("pyflakes", check_pyflakes),
    ("help", check_help),
    ("patch-hunks", check_patch_hunks),
    ("viewer-js", check_viewer_js),
    ("dockerfiles", check_dockerfiles),
    ("script-names", check_script_names),
    ("links", check_links),
    ("formatting", check_formatting),
)
OPTIONAL = (("patch-roundtrip", check_patch_roundtrip),)


def main():
    parser = argparse.ArgumentParser(
        description="Check this project's own files. Upstream OpenHW is left "
                    "alone.")
    parser.add_argument("-k", "--only", metavar="TEXT",
                        help="Run only the checks whose name contains TEXT")
    parser.add_argument("--patch-roundtrip", action="store_true",
                        help="Also apply and revert MinorCPU_CVA6.patch "
                             "against pristine gem5. Needs the network")
    parser.add_argument("--list", action="store_true",
                        help="Name the checks and stop")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="Print only the checks that fail")
    args = parser.parse_args()

    checks = list(CHECKS) + (list(OPTIONAL) if args.patch_roundtrip else [])
    if args.only:
        checks = [c for c in checks if args.only in c[0]]
    if args.list:
        for name, function in list(CHECKS) + list(OPTIONAL):
            print(f"  {name:16} {(function.__doc__ or '').splitlines()[0]}")
        return 0
    if not checks:
        print(f"[ERROR] No check matches '{args.only}'")
        return 2

    failed = skipped = 0
    for name, function in checks:
        try:
            problems = function()
        except Exception as e:                       # a broken check is news
            problems = [f"the check itself raised {type(e).__name__}: {e}"]
        skips = [p for p in problems if p.startswith("SKIP ")]
        real = [p for p in problems if not p.startswith("SKIP ")]
        if real:
            failed += 1
            print(f"[FAIL] {name}")
            for problem in real[:20]:
                print(f"         {problem}")
            if len(real) > 20:
                print(f"         ... and {len(real) - 20} more")
        elif skips:
            skipped += 1
            if not args.quiet:
                print(f"[SKIP] {name}: {skips[0][5:]}")
        elif not args.quiet:
            print(f"[ ok ] {name}")

    total = len(checks)
    print(f"\n{total - failed - skipped} passed, {failed} failed, "
          f"{skipped} skipped, of {total}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
