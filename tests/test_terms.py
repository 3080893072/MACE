import pytest

from mace import terms

ENV = {"xs": "list[int]", "pre": "bool", "n": "int", "d": "dict[int,int]"}
SIGS = terms.signature_table({"fn_0": {"params": ["list[int]"], "ret": "list[int]"},
                              "fn_1": {"params": ["list[int]"], "ret": "int"}})


def ev(expr, **values):
    return terms.evaluate(expr, values, SIGS, {}, declared_env=ENV)


def test_arithmetic_comparison_and_conditional():
    assert ev("1 + 2 * 3") == 7
    assert ev("(n // 2) % 2", n=7) == 1
    assert ev("3 if pre else n", pre=True, n=9) == 3
    assert ev("xs[0] == min(xs)", xs=[1, 1, 2]) is True
    assert ev("xs[-1] == max(xs)", xs=[1, 1, 2]) is True
    # Both Python arities: a list, or two integers.
    assert ev("min(n, 10)", n=12) == 10
    assert ev("max(n, 10)", n=3) == 10


def test_builtins():
    assert ev("distinct(xs)", xs=[1, 1, 2]) == 2
    assert ev("count(xs, 1)", xs=[1, 1, 2]) == 2
    assert ev("sorted(xs)", xs=[2, 1]) == [1, 2]
    assert ev("vals(d)", d={2: 5, 1: 4}) == [4, 5]
    assert ev("sum(sorted(d))", d={2: 5, 1: 4}) == 3


def test_dict_equality_and_lookup():
    assert ev("d[1] == 4", d={1: 4}) is True
    assert ev("d == {1: 4}", d={1: 4}) is True


def test_program_function_calls_are_typed():
    checked = terms.Checked.build("fn_1(xs) == min(xs)", ENV, SIGS)
    assert checked.sort == "bool"
    assert terms.evaluate_checked(checked, {"xs": [3, 1, 2]},
                                  SIGS, {"fn_1": lambda xs: min(xs)}) is True


@pytest.mark.parametrize("expr", [
    "lambda x: x",
    "__import__('os')",
    "xs.append(1)",
    "xs[1:3] == []",
    "len(xs) if pre",
    "open('x')",
    "fn_1(xs) + True",
    "xs == sorted(xs) == [1]",
])
def test_rejected_expressions(expr):
    with pytest.raises(terms.TermError):
        terms.Checked.build(expr, ENV, SIGS)


def test_unknown_name_and_sort_mismatch():
    with pytest.raises(terms.TermError):
        terms.Checked.build("ys[0] == 1", ENV, SIGS)
    assert terms.Checked.build("xs[0]", ENV, SIGS).sort == "int"
    with pytest.raises(terms.TermError):
        terms.Checked.build("xs == 3", ENV, SIGS)


def test_index_bounds_are_runtime_checked():
    with pytest.raises(terms.TermError):
        ev("xs[3] == 1", xs=[1, 2])


def test_no_eval_of_model_text():
    # evaluate() must never execute Python constructs outside the language even
    # when they are side-effect free, because the parser rejects them first.
    with pytest.raises(terms.TermError):
        ev("(lambda: 1)()")
