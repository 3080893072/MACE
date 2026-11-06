def program(xs, mode):
    d = {0: 0, 1: len(xs)}
    d[0] = 5  # TARGET_A
    if mode:
        d[0] = 7
    return d[0], d[1] + len(d) + sum(xs)
