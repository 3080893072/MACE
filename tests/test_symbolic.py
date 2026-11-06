from mace.domain import build_domain, input_sorts
from mace.fixture import Fixture, load_fixture
from mace.induct import verify_guard
from mace.symbolic import derive_guard, node_count, parse_expr


def test_alt_masking_derives_the_exact_guard():
    fixture = load_fixture("alt_masking.json")
    result = derive_guard(fixture)
    assert result["status"] == "DERIVED"
    assert node_count(parse_expr(result["guard"])) > 0
    check = verify_guard(fixture, result["guard"])
    assert check["status"] == "BOUNDED"
    assert check["exact"] is True


def test_dedup_guard_needs_the_helper_summary():
    fixture = load_fixture("dedup_channel.json")
    with_summary = derive_guard(fixture, use_summaries=True)
    without = derive_guard(fixture, use_summaries=False)
    assert with_summary["status"] == "DERIVED"
    assert "count(xs, xs[0] + 1)" in with_summary["guard"]
    assert without["status"] == "UNKNOWN"
    assert with_summary["coverage"]["ratio"] > without["coverage"]["ratio"]


def test_derivation_reports_source_coverage():
    fixture = load_fixture("swap_channels.json")
    result = derive_guard(fixture)
    coverage = result["coverage"]
    assert 0 < coverage["covered"] <= coverage["total"]
    assert 0 < coverage["ratio"] <= 1
    assert result["paths"] >= 1


def test_augassign_target_is_derived():
    # The target lookup originally accepted only ast.Assign, so a real-world
    # `x += 1` target was reported as "target assignment not found".
    source = '''def program(n):
    n += 1  # TARGET_A
    n = n - 1
    return n
'''
    domain = {"kind": "exhaustive", "args": [
        {"name": "n", "sort": "int", "values": [-1, 0, 1]}]}
    fixture = Fixture(config={"id": "augassign", "source": "inline",
                              "domain": domain},
                      source=source, domain=build_domain(domain),
                      arg_sorts=input_sorts(domain), functions={},
                      channels=1, entry="program")
    result = derive_guard(fixture)
    assert result["status"] == "DERIVED"
    check = verify_guard(fixture, result["guard"])
    assert check["status"] == "BOUNDED"
    assert check["exact"] is True
