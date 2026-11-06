def program(timestamp):
    timestamp = int(timestamp)
    if timestamp > 253402300799:
        timestamp //= 1000  # TARGET_A
    return timestamp
