from benchmark_render import A, R, H
YN = [("yes", "Yes"), ("no", "No")]
YNN = [("yes", "Yes"), ("no", "No"), ("na", "N/A")]
MONTHS = [(f"{i+1:02d}", m) for i, m in enumerate("January February March April May June July August September October November December".split())]
def a(n, l, ans, src, note, tags="", kind="text", **kw):
    return A(n, l, kind, ans, src, note=note, tags=tags.split(), **kw)
def r(n, l, note, tags="", kind="text", **kw):
    return R(n, l, kind, note=note, tags=tags.split(), **kw)
def h(n, l, note, when=None, kind="text", **kw):
    return H(n, l, kind, when=when, note=note, tags=["hidden"], **kw)
