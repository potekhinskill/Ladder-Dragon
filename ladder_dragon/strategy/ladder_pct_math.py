# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: own unchanged percentage-ladder rounding and spacing helpers.

from decimal import Decimal


def round_down_to_step(value: Decimal, step: Decimal) -> Decimal:
    if step is None or step <= 0: return value
    return (value // step) * step


def round_up_to_step(value: Decimal, step: Decimal) -> Decimal:
    if step is None or step <= 0: return value
    if (value % step) == 0: return value
    return ((value // step) + 1) * step


def fmt_decimal(d: Decimal) -> str:
    s = f"{d.normalize():f}"
    return s.rstrip('0').rstrip('.') if '.' in s else s


def uniq_keep(seq):
    seen, out = set(), []
    for x in seq:
        k = fmt_decimal(x)
        if k not in seen:
            seen.add(k); out.append(x)
    return out


def thin_ticks(seq, tick, min_ticks: int) -> list[Decimal]:
    if min_ticks <= 0 or tick <= 0 or len(seq) <= 1:
        return seq
    out, last = [], None
    gap = tick * Decimal(min_ticks)
    for x in seq:
        if last is None or abs(x - last) >= gap:
            out.append(x); last = x
    return out


def thin_abs_pct(seq, min_pct_gap: Decimal) -> list[Decimal]:
    if min_pct_gap <= 0 or len(seq) <= 1:
        return seq
    out, last = [], None
    for x in seq:
        if last is None:
            out.append(x); last = x
        else:
            rel = abs((x - last) / last) * Decimal(100)
            if rel >= min_pct_gap:
                out.append(x); last = x
    return out


def raw_levels(now, tick, min_pct_in, max_pct_in, density, np, atr_abs):
    atr_pct = (atr_abs / float(now)) if now > 0 else 0.0
    scale_factor = Decimal(str(1 + atr_pct * 0.5))

    min_pct = (min_pct_in * scale_factor)
    max_pct = (max_pct_in * scale_factor)

    # Geometric spacing by magnitude.
    start_mag = float(abs(min_pct))
    stop_mag  = float(abs(max_pct))
    if abs(start_mag - stop_mag) < 1e-12:
        mags = [start_mag] * density
    else:
        mags = np.geomspace(start_mag, stop_mag, num=density).tolist()

    buy_pcts  = [-Decimal(str(m)) for m in mags]
    sell_pcts = [ Decimal(str(m)) for m in mags]

    # Levels.
    buy_levels  = [now * (Decimal(1) + p/Decimal(100)) for p in buy_pcts]
    sell_levels = [now * (Decimal(1) + p/Decimal(100)) for p in sell_pcts]

    # Rounding.
    buy_q  = [round_down_to_step(lv, tick) for lv in buy_levels]
    sell_q = [round_up_to_step(lv,   tick) for lv in sell_levels]
    return min_pct, max_pct, atr_pct, buy_q, sell_q
