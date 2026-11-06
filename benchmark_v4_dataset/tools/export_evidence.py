"""Write one evidence directory per dynamically tested candidate.

Only candidates that reached Stage 3 (a real P- run) get a directory; Stage 1
rows stay in the inventory CSV.  Each directory is self-contained: the A
coordinates, original hit tests, P- outcome, and (when present) the Stage 4
probe record.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

KIT = Path(__file__).resolve().parents[2]
DISC = KIT / "benchmark_v4_dataset" / "discovery"
OUT = DISC / "evidence"


def safe(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text)[:150]


def main() -> int:
    count = 0
    probe_path = DISC / "stage4" / "probes.json"
    probes = {}
    if probe_path.exists():
        probes = json.loads(probe_path.read_text(encoding="utf-8"))
    for path in sorted((DISC / "stage2_3").glob("*.screen.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for cand in data["candidates"]:
            if "stage3" not in cand:
                continue
            cid = cand["candidate_id"]
            dest = OUT / safe(cid)
            dest.mkdir(parents=True, exist_ok=True)
            payload = {
                "candidate_id": cid,
                "project": cand["project"],
                "version": cand["version"],
                "split": cand["split"],
                "file": cand["file"],
                "function": cand["function"],
                "mechanism": cand["mechanism"],
                "target_A": cand["target_A"],
                "static_shape": cand["static_shape"],
                "original_hit_tests": cand.get("p_plus_hit_tests", []),
                "original_hit_test_count": cand.get("p_plus_hit_test_count", 0),
                "p_plus_suite": data.get("plus_summary"),
                "deletion": cand.get("deletion"),
                "stage2": cand.get("stage2"),
                "stage3": cand.get("stage3"),
                "status": cand.get("status"),
                "targeted_minus": _trim(cand.get("targeted_minus")),
                "full_minus": _trim(cand.get("full_minus")),
                "stage4_probe": probes.get(cid),
                "verdict": _verdict(cand, probes.get(cid)),
            }
            (dest / "candidate.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8")
            count += 1
    print(json.dumps({"evidence_dirs": count, "root": str(OUT)}, indent=2))
    return 0


def _trim(run: dict | None) -> dict | None:
    if not run:
        return None
    keep = {k: run.get(k) for k in
            ("returncode", "timed_out", "seconds", "failed_nodeids")}
    keep["stdout_tail"] = (run.get("stdout") or "")[-3000:]
    keep["stderr_tail"] = (run.get("stderr") or "")[-3000:]
    return keep


def _verdict(cand: dict, probe: dict | None) -> str:
    if probe:
        return probe.get("verdict", "STAGE4_RECORDED")
    if cand.get("status") == "TEST_SURVIVING_DELETION":
        return "SURVIVES_BUT_STAGE4_NOT_RUN"
    return "NOT_A_MASKING_CANDIDATE"


if __name__ == "__main__":
    raise SystemExit(main())
