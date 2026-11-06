def program(y1, y2):
    # Precondition (from the original docstring): y1 <= y2.
    y1 -= 1  # TARGET_A
    y2 -= 1
    return (y2//4 - y1//4) - (y2//100 - y1//100) + (y2//400 - y1//400)
