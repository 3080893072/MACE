def fn_0(xs):
    result = []
    for value in xs:
        pos = len(result)
        while pos > 0 and result[pos - 1] > value:
            pos -= 1
        result.insert(pos, value)
    return result


def fn_1(xs):
    value = xs[0]
    for item in xs[1:]:
        if item < value:
            value = item
    return value


def fn_2(xs):
    value = xs[0]
    for item in xs[1:]:
        if item > value:
            value = item
    return value


def program(xs, pre, use_left, use_right):
    if pre:
        xs = fn_0(xs)

    xs = sorted(xs)  # TARGET_A

    first = fn_1(xs) if use_left else xs[0]
    last = fn_2(xs) if use_right else xs[-1]
    return first, last
