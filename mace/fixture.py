"""Experiment fixtures: a program, its declared domain, and declared signatures."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from .domain import Domain, build_domain, input_sorts
from .program import declared_signatures

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = PROJECT_ROOT / "fixtures"
EXPERIMENT_DIR = PROJECT_ROOT / "experiments"


@dataclass
class Fixture:
    config: Dict[str, Any]
    source: str
    domain: Domain
    arg_sorts: Dict[str, str]
    functions: Dict[str, Any]
    channels: int
    entry: str

    @property
    def id(self) -> str:
        return self.config["id"]

    def domain_text(self) -> str:
        parts = []
        for arg in self.config["domain"]["args"]:
            name, sort = arg["name"], arg["sort"]
            if sort == "bool":
                parts.append(f"{name}: bool")
            elif sort == "int":
                values = arg.get("values") or list(range(*arg.get("range", [0, 0])))
                shown = ", ".join(map(str, values))
                parts.append(f"{name}: int in {{{shown}}}")
            elif sort == "list[int]":
                lo, hi = arg["length"]
                shown = ", ".join(map(str, arg["values"]))
                parts.append(f"{name}: list[int] with length {lo}..{hi}, "
                             f"values in {{{shown}}}")
        kind = self.config["domain"].get("kind", "exhaustive")
        tail = ("every combination is enumerated" if kind == "exhaustive"
                else f"a seeded random sample of {self.config['domain'].get('n')} combinations")
        return "; ".join(parts) + f" ({tail}; {len(self.domain)} cases)"


def load_fixture(path: str | Path, seed: int = 0) -> Fixture:
    path = Path(path)
    if not path.is_absolute():
        path = (EXPERIMENT_DIR / path) if (EXPERIMENT_DIR / path).exists() else (PROJECT_ROOT / path)
    config = json.loads(path.read_text(encoding="utf-8"))
    source_path = Path(config["source"])
    if not source_path.is_absolute():
        source_path = PROJECT_ROOT / source_path
    source = source_path.read_text(encoding="utf-8")
    domain = build_domain(config["domain"], seed=seed)
    functions = config.get("functions")
    if not functions:
        declared = declared_signatures(source)
        functions = {name: {"params": spec["params"], "ret": spec["ret"]}
                     for name, spec in declared.items() if spec["annotated"]}
    return Fixture(config=config, source=source, domain=domain,
                   arg_sorts=input_sorts(config["domain"]), functions=functions,
                   channels=int(config.get("channels", 1)),
                   entry=config.get("entry", "program"))


def fixture_paths() -> List[Path]:
    return sorted(EXPERIMENT_DIR.glob("*.json"))
