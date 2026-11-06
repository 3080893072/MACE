def program(xs, cap):
    total = sum(xs)

    total = total + 1  # TARGET_A

    if cap:
        total = min(total, 10)
    return total
