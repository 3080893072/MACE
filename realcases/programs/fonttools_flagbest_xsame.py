flagOnCurve = 0x01
flagXShort = 0x02
flagYShort = 0x04
flagXsame = 0x10
flagYsame = 0x20


def program(x, y, onCurve):
    flag = flagOnCurve if onCurve else 0
    cost = 0
    if x == 0:
        flag = flag | flagXsame  # TARGET_A
    elif -255 <= x <= 255:
        flag = flag | flagXShort
        if x > 0:
            flag = flag | flagXsame
        cost += 1
    else:
        cost += 2
    if y == 0:
        flag = flag | flagYsame
    elif -255 <= y <= 255:
        flag = flag | flagYShort
        if y > 0:
            flag = flag | flagYsame
        cost += 1
    else:
        cost += 2
    return flag, cost
