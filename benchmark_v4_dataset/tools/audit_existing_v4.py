"""Read-only audit of the exploratory benchmark_real_v4 assets.

This tool never imports, runs, or modifies benchmark_real_v4 code.  It reads
the saved JSON evidence and re-labels each candidate under the V4 dataset
protocol (``benchmark_v4_dataset/PROTOCOL.md``), which is stricter than the
exploratory promotion gate: a DESIGNED test set may not serve as the declared
original-test evidence.

Outputs:
  registry/candidates.json      every unique screening candidate + status
  registry/existing_v4_audit.json   counts and per-candidate audit rows
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

KIT = Path(__file__).resolve().parents[2]
V4 = KIT / "benchmark_real_v4"
DS = KIT / "benchmark_v4_dataset"
EVID = V4 / "evidence"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def funnel_rows():
    rows = {}
    sources = defaultdict(list)
    for path in sorted(EVID.glob("screening_funnel*.json")):
        for row in load(path).get("candidates", []):
            cid = row["candidate_id"]
            rows[cid] = row
            sources[cid].append(path.name)
    return rows, sources


def qualification_index():
    """Return {candidate_id: {ORIGINAL: record|None, DESIGNED: record|None}}."""
    out = {}
    for root, kind in ((EVID / "qualification", "ORIGINAL"),
                       (EVID / "qualification_designed", "DESIGNED"),
                       (DS / "evidence" / "qualification", "ORIGINAL")):
        if not root.exists():
            continue
        for path in sorted(root.glob("*.json")):
            data = load(path)
            cid = data.get("candidate_id")
            if cid:
                out.setdefault(cid, {})[kind] = {
                    "path": str(path.relative_to(KIT)),
                    "counts": data.get("counts", {}),
                    "declared_test_set": data.get("declared_test_set"),
                }
    return out


def supplement_rows(known, quals, rels):
    """Build rows for hand-picked candidates absent from the funnel files."""
    rows = {}
    for cid in sorted(set(quals) | set(rels)):
        if cid in known:
            continue
        source = (quals.get(cid) or {}).get("DESIGNED") or \
                 (quals.get(cid) or {}).get("ORIGINAL")
        qpath = KIT / source["path"] if source else None
        qdata = load(qpath) if qpath and qpath.exists() else {}
        rows[cid] = {
            "candidate_id": cid,
            "project_id": qdata.get("project_id") or cid.split(":")[0],
            "project": qdata.get("project"),
            "version": qdata.get("version"),
            "file": qdata.get("file"),
            "function": qdata.get("function"),
            "target_A": qdata.get("target_A"),
            "source_sha256": qdata.get("source_sha256"),
            "screening_status": "NOT_IN_FUNNEL",
            "screening_rows": ["hand-picked candidate"],
        }
    return rows


def witness_index():
    out = {}
    root = EVID / "witnesses"
    if root.exists():
        for path in sorted(root.glob("*.json")):
            data = load(path)
            cid = data.get("candidate_id")
            if cid:
                out[cid] = {"path": str(path.relative_to(KIT)),
                            "summary": data.get("summary") or data.get("witness_summary")}
    return out


def release_index():
    out = {}
    root = V4 / "release_candidates"
    if root.exists():
        for path in sorted(root.glob("*.json")):
            data = load(path)
            cid = data.get("candidate_id")
            if cid:
                out[cid] = {"path": str(path.relative_to(KIT)),
                            "declared_test_set": data.get("declared_test_set"),
                            "conditions": data.get("conditions", {})}
    return out


def classify(row, quals, wit, rel):
    """Return (status, reason)."""
    screen = row.get("screening_status")
    orig = (quals or {}).get("ORIGINAL")
    designed = (quals or {}).get("DESIGNED")
    qcounts = (orig or {}).get("counts", {})

    if screen == "STATIC_REJECT_DEAD_BEFORE_READ":
        return "SCREENED_REJECT_DEAD_BEFORE_READ", "deletion is a dead store on the static shape"
    if screen == "NO_ORIGINAL_TEST_EXECUTES_A":
        return "SCREENED_REJECT_NO_A_EXECUTION", "no original test executes A"
    if screen == "TARGETED_TEST_DETECTS_DELETION":
        if designed:
            return "DESIGNED_TESTS_ONLY", "original suite detects deletion; only designed tests survive"
        return "SCREENED_REJECT_TEST_DETECTS_DELETION", "targeted original test fails under P-"
    if screen == "NOT_IN_FUNNEL":
        return "DESIGNED_TESTS_ONLY", "hand-picked candidate outside the original-test funnel; only designed tests available"

    if screen != "TEST_SURVIVING_DELETION":
        return "STATIC_CANDIDATE", f"unexpected screening status {screen!r}"

    # The original suite survives the deletion.  A DESIGNED-only rescue is not
    # sufficient under AC10, regardless of how many conditions it satisfies.
    if designed and not orig:
        return "DESIGNED_TESTS_ONLY", "no original-test qualification; designed tests only"
    if not orig:
        return "SCREENED_SURVIVOR", "original suite survives; no masking qualification recorded"
    if designed:
        return "DESIGNED_TESTS_ONLY", "qualification uses DESIGNED tests"

    masked = qcounts.get("MASKED_EFFECT", 0)
    inconclusive = qcounts.get("INCONCLUSIVE", 0)
    if masked:
        exposing = ((wit or {}).get("summary") or {}).get("exposing")
        if not wit:
            return "REJECT_NO_EXPOSING_INPUT", "masked effect but no saved witness"
        if not exposing:
            return "REJECT_NO_EXPOSING_INPUT", "masked witness exists but no legal exposing payload"
        return "MASKING_CANDIDATE", "original-suite masked effect with legal exposing witness; MSMS/MMBS not yet independently accepted"
    if inconclusive:
        return "INCONCLUSIVE", "qualification reports INCONCLUSIVE"
    if qcounts.get("NO_LOCAL_EFFECT"):
        return "REJECT_NO_LOCAL_EFFECT", "deletion does not change any observed test outcome"
    if qcounts.get("ASSERTION_GAP"):
        return "REJECT_NO_MASKING_RELATION", "only assertion gaps; no masking relationship"
    return "SCREENED_SURVIVOR", "qualified but no masking class"


def main():
    rows, sources = funnel_rows()
    quals = qualification_index()
    wits = witness_index()
    rels = release_index()
    rows.update(supplement_rows(rows, quals, rels))
    for cid in rows:
        sources.setdefault(cid, [])

    candidates = []
    for cid, row in sorted(rows.items()):
        qual = quals.get(cid)
        wit = wits.get(cid)
        rel = rels.get(cid)
        status, reason = classify(row, qual, wit, rel)
        candidates.append({
            "candidate_id": cid,
            "project_id": row.get("project_id"),
            "project": row.get("project"),
            "version": row.get("version"),
            "file": row.get("file"),
            "function": row.get("function"),
            "target_A": row.get("target_A"),
            "source_sha256": row.get("source_sha256"),
            "screening_status": row.get("screening_status"),
            "screening_rows": sources.get(cid, []),
            "qualification": qual,
            "witness": wit,
            "release_candidate": rel,
            "v4_status": status,
            "v4_reason": reason,
            "split": "DEV",
        })

    by_status = Counter(c["v4_status"] for c in candidates)
    by_project = Counter(c["project_id"] for c in candidates)
    by_screen = Counter(c["screening_status"] for c in candidates)

    audit = {
        "schema": "mace_v4_existing_assets_audit/1",
        "generated_from": "benchmark_real_v4/evidence (read-only)",
        "protocol": "benchmark_v4_dataset/PROTOCOL.md",
        "counts": {
            "unique_candidates": len(candidates),
            "by_screening_status": dict(by_screen),
            "by_v4_status": dict(by_status),
            "by_project": dict(by_project),
            "qualification_original": sum(1 for q in quals.values() if "ORIGINAL" in q),
            "qualification_designed": sum(1 for q in quals.values() if "DESIGNED" in q),
            "witnesses": len(wits),
            "release_candidates": len(rels),
        },
        "accepted_tasks": 0,
        "note": (
            "No candidate is promoted to an accepted V4 task by this audit. "
            "The five exploratory release candidates rely on DESIGNED tests and are "
            "recorded as DESIGNED_TESTS_ONLY under the V4 protocol."
        ),
        "candidates": candidates,
    }

    DS.mkdir(parents=True, exist_ok=True)
    (DS / "registry").mkdir(parents=True, exist_ok=True)
    (DS / "registry" / "candidates.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (DS / "registry" / "existing_v4_audit.json").write_text(
        json.dumps({k: v for k, v in audit.items() if k != "candidates"},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit["counts"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
