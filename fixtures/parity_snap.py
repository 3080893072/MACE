def program(xs, even):
    total = sum(xs)
    total = total + 1  # TARGET_A
    if even:
        total = total - total % 2
    return total
