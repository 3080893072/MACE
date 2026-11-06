def fn_0(xs):
    total = 0
    for x in xs:
        total = total + x
    return total


def program(xs, cap):
    total = fn_0(xs)

    total = total + 1  # TARGET_A

    if cap:
        total = total - total % 10
    return total
