def program(n, k, show_gap):
    a = n
    b = k

    a, b = b, a  # TARGET_A

    gap = (a - b) if show_gap else 0
    return a + b, a * b, gap
