"""Automated regression tests for the v3 normalized scorer.

Run from the kit root::

    python -m unittest discover -s benchmark_real_v3/scoring/tests -v

The tests use only human-authored submissions derived from the frozen hidden
reference; no model is invoked.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from benchmark_real_v3.scoring.engine import HIDDEN, load_reference, score_submission
from benchmark_real_v3.scoring.demo import make_illegal, make_unverifiable


def _claims(task_id: str):
    return load_reference(task_id)["reference_claims"]


def _clean(claims):
    return [
        {k: v for k, v in claim.items()
         if k not in ("witness_id", "expected_status")}
        for claim in claims
    ]


def _score(task_id: str, claims):
    return score_submission({
        "submission_id": f"test-{task_id}",
        "task_id": task_id,
        "claims": claims,
    })


class ScorerTests(unittest.TestCase):
    def test_all_five_correct_submissions(self):
        for task_id in sorted(
                path.parent.name for path in (HIDDEN / "tasks").glob("*/reference.json")):
            with self.subTest(task_id=task_id):
                result = _score(task_id, _clean(_claims(task_id)))
                self.assertEqual(
                    [claim["status"] for claim in result["claims"]],
                    ["WITNESS_VERIFIED"] * len(result["claims"]),
                    result["claims"])
                self.assertEqual(result["score"]["claim_credit"],
                                 len(result["claims"]))

    def test_get_host_has_two_distinct_masking_paths(self):
        result = _score(
            "werkzeug_get_host_default_empty",
            _clean(_claims("werkzeug_get_host_default_empty")))
        keys = {
            claim["relation_key"] for claim in result["claims"]
            if claim["type"] in ("MSMS", "MMBS")
        }
        self.assertIn(
            "MSMS:src/werkzeug/sansio/utils.py:85", keys)
        self.assertIn(
            "MSMS:src/werkzeug/sansio/utils.py:87", keys)
        self.assertEqual(len(keys), 4)

    def test_finite_domain_exact_is_finite_only(self):
        result = _score("jinja2_bytecode_cache_read", [{
            "type": "MSMS",
            "inputs": [{"template": "{{ 1+1 }}"}, {"template": "{{ 2+2 }}"}],
            "operations": [{
                "file": "src/jinja2/loaders.py", "line": 137,
                "code": "code = environment.compile(source, name, filename)",
            }],
        }])
        claim = result["claims"][0]
        self.assertEqual(claim["status"], "FINITE_DOMAIN_EXACT")
        self.assertIn("not the whole legal input domain", claim["scope"])
        self.assertEqual(
            result["score"]["domain_exact_relations"], 1)

    def test_duplicate_claims_do_not_double_score(self):
        base = _clean(_claims("jinja2_bytecode_cache_read"))
        result = _score("jinja2_bytecode_cache_read", base + base)
        statuses = [claim["status"] for claim in result["claims"]]
        self.assertEqual(statuses[:len(base)], ["WITNESS_VERIFIED"] * len(base))
        self.assertEqual(statuses[len(base):], ["DUPLICATE"] * len(base))
        self.assertEqual(result["score"]["credited_relations"], len(base))
        self.assertEqual(result["score"]["claim_credit"], len(base))

    def test_same_relation_on_another_input_gets_no_second_credit(self):
        op = {
            "file": "src/jinja2/loaders.py", "line": 137,
            "code": "code = environment.compile(source, name, filename)",
        }
        result = _score("jinja2_bytecode_cache_read", [
            {"type": "MSMS", "input": {"template": "{{ 1+1 }}"},
             "operations": [op]},
            {"type": "MSMS", "input": {"template": "{{ 2+2 }}"},
             "operations": [op]},
        ])
        self.assertEqual(
            [claim["status"] for claim in result["claims"]],
            ["WITNESS_VERIFIED", "WITNESS_VERIFIED"])
        self.assertEqual(result["claims"][1]["credit"], 0)
        self.assertEqual(result["score"]["credited_relations"], 1)

    def test_illegal_and_unverifiable_statuses(self):
        result = _score(
            "jinja2_bytecode_cache_read",
            _clean(make_illegal(load_reference("jinja2_bytecode_cache_read"))[
                "claims"]))
        statuses = [claim["status"] for claim in result["claims"]]
        self.assertEqual(statuses[:3], ["INVALID", "INVALID", "INVALID"])
        self.assertIn("UNVERIFIED", statuses)
        self.assertIn("UNSUPPORTED", statuses)
        result = _score(
            "jinja2_bytecode_cache_read",
            _clean(make_unverifiable(
                load_reference("jinja2_bytecode_cache_read"))["claims"]))
        self.assertEqual(
            [claim["status"] for claim in result["claims"]],
            ["UNVERIFIED", "UNVERIFIED"])

    def test_non_executing_input_is_not_a_masking_witness(self):
        result = _score("werkzeug_bind_server_name_lower", [{
            "type": "MSMS",
            "input": {},
            "operations": [{
                "file": "src/werkzeug/routing/map.py", "line": 219,
                "code": "server_name = server_name.lower()",
            }],
        }])
        claim = result["claims"][0]
        self.assertEqual(claim["status"], "FALSE")
        self.assertIn("not executed", claim["reason"])

    def test_prerequisite_and_conditional_relations(self):
        ref = load_reference("werkzeug_bind_server_name_lower")
        op = {
            "file": "src/werkzeug/routing/map.py", "line": 219,
            "code": "server_name = server_name.lower()",
        }
        condition = {"server_name": "EXAMPLE.COM", "subdomain": "www"}
        control = {"server_name": "EXAMPLE.COM", "subdomain": None}
        result = _score("werkzeug_bind_server_name_lower", [
            {
                "type": "PREREQUISITE_BREAKING",
                "input": condition, "control_input": control,
                "operations": [op], "prerequisite": "subdomain is not None",
            },
            {
                "type": "CONDITIONAL_CORRECTNESS",
                "condition_input": condition, "conclusion_input": control,
                "operations": [op],
            },
        ])
        self.assertEqual(
            [claim["status"] for claim in result["claims"]],
            ["WITNESS_VERIFIED", "WITNESS_VERIFIED"])
        for claim in result["claims"]:
            self.assertIn("point witnesses", claim["scope"])
        self.assertTrue(ref["reference_claims"])

    def test_proven_is_never_assigned(self):
        result = _score("jinja2_bytecode_cache_read", [{
            "type": "PROVEN",
            "statement": "A theorem.",
            "proof": {"text": "not machine checked"},
        }])
        self.assertEqual(result["claims"][0]["status"], "UNVERIFIED")
        self.assertEqual(result["status_counts"]["PROVEN"], 0)


if __name__ == "__main__":
    unittest.main()
