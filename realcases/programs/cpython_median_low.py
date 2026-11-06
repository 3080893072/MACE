def program(data):
    data = sorted(data)  # TARGET_A
    n = len(data)
    if n % 2 == 1:
        return data[n // 2]
    i = n // 2
    return data[i - 1]
