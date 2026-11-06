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


def program(xs, flag_0, flag_1, flag_2):
    if flag_0:
        xs = fn_0(xs)

    xs = sorted(xs)  # TARGET_A

    first = fn_1(xs) if flag_1 else xs[0]
    last = fn_2(xs) if flag_2 else xs[-1]
    return first, last
