def program(n):
    """convert long to signed 32 bit integer"""
    n = n & 0xFFFFFFFF  # TARGET_A
    return (n ^ 0x80000000) - 0x80000000
