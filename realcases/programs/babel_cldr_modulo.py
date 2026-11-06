def program(a, b):
    reverse = 0
    if a < 0:
        a *= -1  # TARGET_A
        reverse = 1
    if b < 0:
        b *= -1
    rv = a % b
    if reverse:
        rv *= -1
    return rv
