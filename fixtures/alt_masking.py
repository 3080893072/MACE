def program(xs, mode):
    v = xs[0] if len(xs) > 0 else 0

    v = v + 1  # TARGET_A

    if mode == 0:
        out = v * 0
    elif mode == 1:
        out = v - v
    else:
        out = v
    return out
