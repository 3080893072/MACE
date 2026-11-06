def fn_0(xs):
    out = []
    for x in xs:
        if x not in out:
            out.append(x)
    return out


def program(xs, pre):
    if pre:
        xs = fn_0(xs)

    xs = xs + [xs[0] + 1]  # TARGET_A

    return len(fn_0(xs))
