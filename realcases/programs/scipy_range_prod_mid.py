def program(lo, hi, k=1):
    if lo + k < hi:
        mid = (hi + lo) // 2
        if k > 1:
            mid = mid - ((mid - hi) % k)  # TARGET_A
        return program(lo, mid, k) * program(mid + k, hi, k)
    elif lo + k == hi:
        return lo * hi
    else:
        return hi
