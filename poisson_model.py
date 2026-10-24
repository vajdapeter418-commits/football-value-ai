"""Unchanged main baseline and 0..100 Poisson table; no UI dependency."""
import math


def goltabla(gh, gv):
    if not all(
        math.isfinite(x) and 0 < x <= 20
        for x in (gh, gv)
    ):
        raise ValueError("A gólátlag kívül esik a modell tartományán.")

    ph = [math.exp(-gh)]
    pv = [math.exp(-gv)]

    for k in range(1, 101):
        ph.append(ph[-1] * gh / k)
        pv.append(pv[-1] * gv / k)

    return [
        (h, v, p * q)
        for h, p in enumerate(ph)
        for v, q in enumerate(pv)
    ]


def becsles(meccsek, hazai, vendeg):
    lh = sum(m[2] for m in meccsek) / len(meccsek)
    lv = sum(m[3] for m in meccsek) / len(meccsek)

    h = [m for m in meccsek if m[0] == hazai]
    v = [m for m in meccsek if m[1] == vendeg]

    if not h or not v or min(lh, lv) <= 0:
        raise ValueError("Nincs elég megfelelő csapatadat.")

    hf = (sum(m[2] for m in h) + 5 * lh) / (len(h) + 5)
    hc = (sum(m[3] for m in h) + 5 * lv) / (len(h) + 5)
    vf = (sum(m[3] for m in v) + 5 * lv) / (len(v) + 5)
    vc = (sum(m[2] for m in v) + 5 * lh) / (len(v) + 5)

    gh = hf * vc / lh
    gv = vf * hc / lv

    p = [0.0, 0.0, 0.0]

    for a, b, esely in goltabla(gh, gv):
        index = 0 if a > b else 1 if a == b else 2
        p[index] += esely

    return (
        [x / sum(p) for x in p],
        gh,
        gv,
        len(h),
        len(v),
    )


def pontos_eredmenyek(gh, gv):
    tabla = sorted(
        goltabla(gh, gv),
        key=lambda r: (-r[2], r[0], r[1]),
    )

    return tabla[:5]


