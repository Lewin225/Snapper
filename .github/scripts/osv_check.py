"""Looks up pinned Python packages ("name==version" lines) in OSV (https://osv.dev, the open vulnerability database that also
feeds the PyPI Advisory Database and GitHub's alerts) and fails if any version has a known vulnerability.
usage: osv_check.py FILE [FILE ...]   FILE is a text file of "name==version" lines, or a `pip install --report` JSON file.
Advisories we have looked at and accepted go in .github/osv-ignore.txt: one id per line, then a reason."""
import json
import os
import sys
import urllib.request
from pathlib import Path

API = "https://api.osv.dev/v1/querybatch"
IGNORE = Path(__file__).resolve().parents[1] / "osv-ignore.txt"


def pins(paths):
    found = {}
    for path in paths:
        if str(path).endswith(".json"):   # what pip would install, local versions (+cpu) cut off as PyPI does not list them
            for item in json.loads(Path(path).read_text())["install"]:
                found[(item["metadata"]["name"].lower(), item["metadata"]["version"].split("+")[0])] = None
            continue
        for line in Path(path).read_text().splitlines():
            line = line.split("#")[0].strip()
            if "==" in line:
                name, _, version = line.partition("==")
                found[(name.strip().lower(), version.strip())] = None
    return list(found)


def query(packages):
    """{(name, version): [advisory ids]} for the packages that have any."""
    hits = {}
    for start in range(0, len(packages), 500):
        chunk = packages[start:start + 500]
        body = json.dumps({"queries": [{"package": {"name": n, "ecosystem": "PyPI"}, "version": v} for n, v in chunk]}).encode()
        request = urllib.request.Request(API, body, {"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=60) as response:
            results = json.load(response)["results"]
        if len(results) != len(chunk):
            sys.exit(f"OSV answered {len(results)} results for {len(chunk)} packages")
        for package, result in zip(chunk, results):
            ids = [v["id"] for v in result.get("vulns", [])]
            if ids:
                hits[package] = ids
    return hits


def main(paths):
    ignored = {line.split()[0] for line in IGNORE.read_text().splitlines() if line.strip() and not line.startswith("#")} \
        if IGNORE.exists() else set()
    packages = pins(paths)
    if not packages:
        sys.exit("no pinned packages found: nothing was checked")
    print(f"checking {len(packages)} pinned packages against OSV")
    rows = []
    for (name, version), ids in sorted(query(packages).items()):
        live = [i for i in ids if i not in ignored]
        if live:
            rows.append((name, version, live))
            print(f"VULNERABLE {name}=={version}: " + ", ".join(f"{i} (https://osv.dev/{i})" for i in live))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:   # the table on the workflow run's page
        with open(summary, "a") as out:
            out.write(f"Checked {len(packages)} pinned packages against OSV: " + (f"**{len(rows)} with known vulnerabilities**\n\n" if rows else "none vulnerable.\n"))
            if rows:
                out.write("| Package | Advisories |\n|---|---|\n")
                for name, version, live in rows:
                    out.write(f"| `{name}=={version}` | " + ", ".join(f"[{i}](https://osv.dev/{i})" for i in live) + " |\n")
                out.write("\nTo accept an advisory after looking at it, add its id and the reason to `.github/osv-ignore.txt`.\n")
    if rows:
        sys.exit(f"{len(rows)} package(s) with known vulnerabilities")
    print("no known vulnerabilities")


if __name__ == "__main__":
    main(sys.argv[1:])
