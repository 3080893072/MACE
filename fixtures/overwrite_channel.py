def fn_0(xs):
    total = 0
    for x in xs:
        total = total + x
    return total


def program(xs, keep):
    value = fn_0(xs)

    value = 0  # TARGET_A

    if keep:
        value = fn_0(xs)
    return value, value + 1
