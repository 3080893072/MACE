def program(length, start, end):
    if end > length:
        end = length
    if end < 0:
        end += length  # TARGET_A
        if end < 0:
            end = 0
    if start < 0:
        start += length
        if start < 0:
            start = 0
    return start, end
