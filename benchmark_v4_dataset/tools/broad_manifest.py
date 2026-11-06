"""Build, seal and fetch the broad DISCOVERY project pool.

Only PyPI metadata and sdist bytes are touched here.  No project source is
read, extracted or scanned before the HELDOUT seal is written.

Subcommands::

    python -I benchmark_v4_dataset/tools/broad_manifest.py manifest
    python -I benchmark_v4_dataset/tools/broad_manifest.py fetch
    python -I benchmark_v4_dataset/tools/broad_manifest.py seal
    python -I benchmark_v4_dataset/tools/broad_manifest.py download
    python -I benchmark_v4_dataset/tools/broad_manifest.py verify

The DEV/HELDOUT assignment is fixed by this file and never by a result.
HELDOUT projects are downloaded but never extracted in this phase.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[2]
DS = KIT / "benchmark_v4_dataset" / "discovery"
META = DS / "manifest"
SDISTS = DS / "sdists"
PYPI_JSON = META / "pypi"

# (pypi name, version).  Selection rule: published sdists that are expected to
# ship their original test suite.  Selection was fixed before any source was
# read; wrong guesses are recorded as STAGE0_NO_TESTS, not replaced.
DEV = [
    ("attrs", "23.2.0"), ("cattrs", "23.2.3"), ("cerberus", "1.3.5"),
    ("cloudpickle", "3.0.0"), ("coverage", "7.4.0"), ("decorator", "5.1.1"),
    ("diskcache", "5.6.3"), ("docutils", "0.20.1"), ("ecdsa", "0.18.0"),
    ("exceptiongroup", "1.2.0"), ("execnet", "2.0.2"), ("filetype", "1.2.0"),
    ("flake8", "7.0.0"), ("httpcore", "1.0.2"), ("h11", "0.14.0"),
    ("humanize", "4.9.0"), ("importlib_resources", "6.1.1"),
    ("iniconfig", "2.0.0"), ("isort", "5.13.2"), ("jedi", "0.19.1"),
    ("jsonschema", "4.20.0"), ("lark", "1.1.9"), ("Markdown", "3.5.1"),
    ("mccabe", "0.7.0"), ("more-itertools", "10.1.0"), ("msgpack", "1.0.7"),
    ("multidict", "6.0.4"), ("networkx", "3.2.1"), ("parso", "0.8.3"),
    ("parsimonious", "0.10.0"), ("passlib", "1.7.4"), ("pluggy", "1.3.0"),
    ("py", "1.11.0"), ("pycodestyle", "2.11.1"), ("pyflakes", "3.1.0"),
    ("Pygments", "2.17.2"), ("PyJWT", "2.8.0"), ("Pympler", "1.0.1"),
    ("pyrsistent", "0.20.0"), ("pytest", "7.4.4"),
    ("python-dateutil", "2.8.2"), ("pytz", "2023.3.post1"),
    ("PyYAML", "6.0.1"), ("requests", "2.31.0"), ("rfc3986", "2.0.0"),
    ("rsa", "4.9"), ("schema", "0.7.5"), ("simplejson", "3.19.2"),
    ("sqlparse", "0.4.4"), ("tabulate", "0.9.0"), ("tenacity", "8.2.3"),
    ("toml", "0.10.2"), ("toolz", "0.12.0"), ("urllib3", "2.1.0"),
    ("voluptuous", "0.14.2"), ("wheel", "0.42.0"), ("wrapt", "1.16.0"),
    ("zipp", "3.17.0"),
]

HELDOUT = [
    ("boltons", "23.1.1"), ("cachetools", "5.3.2"), ("docopt", "0.6.2"),
    ("aiofiles", "23.2.1"), ("bitstring", "4.1.2"), ("blinker", "1.7.0"),
    ("cssselect", "1.2.0"), ("feedparser", "6.0.11"),
    ("jsonpointer", "2.4"), ("pathspec", "0.12.1"), ("tqdm", "4.66.1"),
    ("xmltodict", "0.13.0"),
]


def slug(name: str) -> str:
    return name.lower().replace("_", "-").replace(".", "-")


def manifest_path() -> Path:
    return META / "projects_broad.json"


def entries() -> list[dict]:
    rows = []
    for split, pairs in (("DEV", DEV), ("HELDOUT_BROAD", HELDOUT)):
        for name, version in pairs:
            rows.append({
                "name": name,
                "version": version,
                "slug": slug(name) + "-" + version,
                "split": split,
                "source": "pypi-sdist",
            })
    return rows


def cmd_manifest() -> int:
    rows = entries()
    names = [(r["name"].lower(), r["version"]) for r in rows]
    assert len(names) == len(set(names)), "duplicate project/version"
    payload = {
        "schema": "mace_v4_broad_manifest/1",
        "selection_rule": (
            "Published PyPI sdists expected to ship their own test suite; "
            "chosen from public package metadata before any source inspection."
        ),
        "counts": {"DEV": len(DEV), "HELDOUT_BROAD": len(HELDOUT),
                   "total": len(rows)},
        "projects": rows,
        "excluded_existing": {
            "note": "existing V4 DEV projects are not re-scanned here",
            "DEV": ["click-8.4.1", "itsdangerous-2.0.1", "packaging-23.1",
                    "pyparsing-3.0.9", "six-1.16.0"],
        },
    }
    META.mkdir(parents=True, exist_ok=True)
    manifest_path().write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    seal_path = META / "seal_heldout_broad.json"
    if not seal_path.exists():
        heldout = [r for r in rows if r["split"] == "HELDOUT_BROAD"]
        canonical = json.dumps(heldout, sort_keys=True, separators=(",", ":"),
                               ensure_ascii=True)
        seal_path.write_text(json.dumps({
            "sealed_before_source_access": True,
            "scope": "HELDOUT_BROAD",
            "counts": {"projects": len(heldout)},
            "canonicalization": (
                "json.dumps(heldout, sort_keys=True, separators=(',',':'), "
                "ensure_ascii=True) over split/projects entries"),
            "seal_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
            "unsealed": None,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"manifest": str(manifest_path()),
                      "counts": payload["counts"]}, indent=2))
    return 0


def _curl(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "curl", "--ssl-no-revoke", "-fsSL", "--retry", "3",
        "--connect-timeout", "20", "-o", str(dest), url,
    ], check=True)


def cmd_fetch() -> int:
    data = json.loads(manifest_path().read_text(encoding="utf-8"))
    PYPI_JSON.mkdir(parents=True, exist_ok=True)
    for row in data["projects"]:
        dest = PYPI_JSON / f"{row['slug']}.json"
        if dest.exists() and dest.stat().st_size > 1000:
            continue
        url = f"https://pypi.org/pypi/{row['name']}/{row['version']}/json"
        _curl(url, dest)
        print("fetched", row["slug"], dest.stat().st_size)
    return 0


def _sdist_info(row: dict) -> dict:
    data = json.loads((PYPI_JSON / f"{row['slug']}.json").read_text(
        encoding="utf-8"))
    urls = [u for u in data["urls"] if u["packagetype"] == "sdist"]
    if not urls:
        raise SystemExit(f"no sdist for {row['slug']}")
    sdist = urls[0]
    info = data["info"]
    return {
        **row,
        "filename": sdist["filename"],
        "url": sdist["url"],
        "sha256": sdist["digests"]["sha256"],
        "size": sdist["size"],
        "license": info.get("license") or "",
        "license_classifiers": [c for c in info.get("classifiers", [])
                                if c.startswith("License ::")],
        "requires_python": info.get("requires_python"),
        "summary": (info.get("summary") or "")[:200],
        "upload_time": sdist.get("upload_time_iso_8601"),
    }


def cmd_seal() -> int:
    """Write the metadata registry and sealed project list."""
    data = json.loads(manifest_path().read_text(encoding="utf-8"))
    rows = [_sdist_info(row) for row in data["projects"]]
    registry = {
        "schema": "mace_v4_source_registry/1",
        "fetched_from": "https://pypi.org/pypi/<name>/<version>/json",
        "projects": rows,
    }
    (META / "source_registry.json").write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")

    seal_path = META / "seal_heldout_broad.json"
    heldout = [r for r in rows if r["split"] == "HELDOUT_BROAD"]
    canonical = json.dumps(heldout, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=True)
    previous = json.loads(seal_path.read_text(encoding="utf-8")) \
        if seal_path.exists() else {}
    if (previous.get("canonical") is not None
            and previous.get("unsealed") is None
            and previous.get("canonical") != heldout):
        raise SystemExit(
            "HELDOUT_BROAD already sealed with different metadata; "
            "refusing to reseal")
    seal_path.write_text(json.dumps({
        "sealed_before_source_access": True,
        "scope": "HELDOUT_BROAD",
        "sealed_at_utc": "2026-11-04T08:45:00Z",
        "counts": {"projects": len(heldout)},
        "canonical": heldout,
        "seal_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
        "unsealed": None,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "registry": str(META / "source_registry.json"),
        "seal": str(seal_path),
        "seal_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
        "heldout": len(heldout),
    }, indent=2))
    return 0


def cmd_download() -> int:
    registry = json.loads((META / "source_registry.json").read_text(
        encoding="utf-8"))
    SDISTS.mkdir(parents=True, exist_ok=True)
    for row in registry["projects"]:
        dest = SDISTS / row["filename"]
        if dest.exists() and dest.stat().st_size == row["size"]:
            continue
        _curl(row["url"], dest)
        print("downloaded", dest.name, dest.stat().st_size)
    return 0


def cmd_verify() -> int:
    registry = json.loads((META / "source_registry.json").read_text(
        encoding="utf-8"))
    bad = []
    ok = 0
    for row in registry["projects"]:
        path = SDISTS / row["filename"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != row["sha256"]:
            bad.append({"project": row["slug"], "expected": row["sha256"],
                        "actual": digest})
        else:
            ok += 1
    print(json.dumps({"verified": ok, "bad": bad,
                      "total": len(registry["projects"])}, indent=2))
    return 1 if bad else 0


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    table = {"manifest": cmd_manifest, "fetch": cmd_fetch, "seal": cmd_seal,
             "download": cmd_download, "verify": cmd_verify}
    if cmd not in table:
        print(__doc__)
        return 2
    return table[cmd]()


if __name__ == "__main__":
    raise SystemExit(main())
