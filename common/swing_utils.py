import numpy as np
import pandas as pd

# ──────────────── Helper: find the previous non-NaN in a 1D numpy array ────────────────
def previous_non_nan(arr: np.ndarray, idx: int):
    """
    Return the last non-nan value in 'arr' at an index < idx.
    If none found, returns np.nan. This precisely mimics Pine Script's
    'valuewhen(bool(series), series, 1)' behavior.
    """
    j = idx - 1
    while j >= 0:
        if not np.isnan(arr[j]):
            return arr[j]
        j -= 1
    return np.nan

# ──────────── 1) Compute “raw” left/right pivots exactly like ta.pivothigh/ta.pivotlow ────────────
def compute_raw_pivots(df: pd.DataFrame, left_bars: int, right_bars: int):
    """
    Given df sorted by date, returns two boolean numpy arrays of length N:
      - raw_ph[i] = True  if bar i is a left/right pivot high
      - raw_pl[i] = True  if bar i is a left/right pivot low
    Exactly mimics `ta.pivothigh(left_bars, right_bars)` and `ta.pivotlow(left_bars, right_bars)`.
    Includes tie-breaking: if multiple bars have the same extreme value within the window,
    only the *first* such bar is marked as a pivot.
    """
    highs = df["high"].values
    lows = df["low"].values
    n = len(df)

    raw_ph = np.zeros(n, dtype=bool)
    raw_pl = np.zeros(n, dtype=bool)

    for i in range(left_bars, n - right_bars):
        # Check pivot high condition with tie-breaking
        window_high = highs[i - left_bars : i + right_bars + 1]
        if highs[i] == np.max(window_high):
            # Check if current bar 'i' is the first occurrence of this max in the window
            # Adjusted index relative to original array
            first_occurrence_in_window_idx = np.argmax(window_high)
            if (i - left_bars + first_occurrence_in_window_idx) == i:
                raw_ph[i] = True

        # Check pivot low condition with tie-breaking
        window_low = lows[i - left_bars : i + right_bars + 1]
        if lows[i] == np.min(window_low):
            # Check if current bar 'i' is the first occurrence of this min in the window
            first_occurrence_in_window_idx = np.argmin(window_low)
            if (i - left_bars + first_occurrence_in_window_idx) == i:
                raw_pl[i] = True

    return raw_ph, raw_pl

# ──────────── 2) Build initial “zigzag arrays” (hl = +1/–1, zz = pivot price) ────────────
def build_initial_zigzag(df: pd.DataFrame, raw_ph: np.ndarray, raw_pl: np.ndarray):
    """
    Given df + raw ph/pl arrays, produce two numpy arrays (length N):
      - hl0[i] = +1 if raw_ph[i] (we flagged a pivot high),
               = –1 if raw_pl[i] (we flagged a pivot low),
               =    NaN otherwise.
      - zz0[i] = highs[i] if raw_ph[i], lows[i] if raw_pl[i], NaN otherwise.
    This mirrors:
        hl = bool(ph) ? 1 : (bool(pl) ? -1 : na)
        zz = bool(ph) ? ph : (bool(pl) ? pl : na)
    in PineScript.
    """
    highs = df["high"].values
    lows = df["low"].values
    n = len(df)

    hl0 = np.full(n, np.nan, dtype=float)
    zz0 = np.full(n, np.nan, dtype=float)

    for i in range(n):
        if raw_ph[i]:
            hl0[i] = 1.0
            zz0[i] = highs[i]
        elif raw_pl[i]:
            hl0[i] = -1.0
            zz0[i] = lows[i]
        # else hl0[i], zz0[i] remain NaN
    return hl0, zz0

# ──────────── 3) Apply PineScript’s “valuewhen”-based zigzag filters ────────────
def apply_zigzag_filters(df: pd.DataFrame, raw_ph: np.ndarray, raw_pl: np.ndarray, hl0: np.ndarray, zz0: np.ndarray):
    """
    Replicates exactly the four “valuewhen” filter lines in your Pine code:
      1) zz := bool(pl) and hl == -1 and prev_hl == -1 and pl > prev_zz ? na : zz
      2) zz := bool(ph) and hl ==  1 and prev_hl ==  1 and ph < prev_zz ? na : zz
      3) hl := hl == -1 and prev_hl ==  1 and zz > prev_zz ? na : hl
      4) hl := hl ==  1 and prev_hl == -1 and zz < prev_zz ? na : hl
      zz := na(hl) ? na : zz

    The `previous_non_nan` helper correctly handles the `valuewhen(bool(series), series, 1)` behavior.
    Crucially, `prev_hl_valX` and `prev_zz_valX` are re-calculated after each potential modification
    within the loop for the current bar, mimicking Pine's immediate assignment (`:=`).
    """
    highs = df["high"].values
    lows = df["low"].values
    n = len(df)

    # Make working copies that will be modified in place
    hl1 = hl0.copy()
    zz1 = zz0.copy()

    for i in range(n):
        # PineScript logic for current bar (i) uses previous values *before* current bar's modification.
        # This is correctly handled by previous_non_nan(arr, i)

        # Filter 1: zz := bool(pl) and hl == -1 and prev_hl == -1 and pl > prev_zz ? na : zz
        # Note: bool(pl) means raw_pl[i] is True. hl == -1 implies hl1[i] was initially -1.
        prev_hl_val = previous_non_nan(hl1, i)
        prev_zz_val = previous_non_nan(zz1, i)
        if raw_pl[i] and (hl1[i] == -1.0) and (prev_hl_val == -1.0) and (lows[i] > prev_zz_val):
            hl1[i] = np.nan
            zz1[i] = np.nan

        # Re-grab prev_hl_val2 / prev_zz_val2 after Filter 1, as Pine does with chained valuewhen calls
        prev_hl_val2 = previous_non_nan(hl1, i)
        prev_zz_val2 = previous_non_nan(zz1, i)

        # Filter 2: zz := bool(ph) and hl == 1 and prev_hl == 1 and ph < prev_zz ? na : zz
        # Note: bool(ph) means raw_ph[i] is True. hl == 1 implies hl1[i] was initially 1.
        if raw_ph[i] and (hl1[i] == 1.0) and (prev_hl_val2 == 1.0) and (highs[i] < prev_zz_val2):
            hl1[i] = np.nan
            zz1[i] = np.nan
        
        # Re-grab prev_hl_val3 / prev_zz_val3 after Filter 2
        prev_hl_val3 = previous_non_nan(hl1, i)
        prev_zz_val3 = previous_non_nan(zz1, i)

        # Filter 3: hl := hl == -1 and prev_hl == 1 and zz > prev_zz ? na : hl
        # This filters out a pivot low if the previous pivot was a high AND the current pivot low
        # is actually higher than that previous high.
        if raw_pl[i] and (hl1[i] == -1.0) and (prev_hl_val3 == 1.0) and (zz1[i] > prev_zz_val3):
            hl1[i] = np.nan
            zz1[i] = np.nan

        # Re-grab prev_hl_val4 / prev_zz_val4 after Filter 3
        prev_hl_val4 = previous_non_nan(hl1, i)
        prev_zz_val4 = previous_non_nan(zz1, i)

        # Filter 4: hl := hl == 1 and prev_hl == -1 and zz < prev_zz ? na : hl
        # This filters out a pivot high if the previous pivot was a low AND the current pivot high
        # is actually lower than that previous low.
        if raw_ph[i] and (hl1[i] == 1.0) and (prev_hl_val4 == -1.0) and (zz1[i] < prev_zz_val4):
            hl1[i] = np.nan
            zz1[i] = np.nan

        # Final rule: zz := na(hl) ? na : zz. If hl[i] became NaN, force zz[i] = NaN.
        if np.isnan(hl1[i]):
            zz1[i] = np.nan

    return hl1, zz1

# ──────────── Helper for finding a, b, c, d, e based on Pine's findprevious() logic ────────────
def find_abcd_e(current_hl_val: float, hl_arr: np.ndarray, zz_arr: np.ndarray, current_idx: int):
    """
    Replicates Pine Script's findprevious() logic to determine the 'b', 'c', 'd', 'e'
    pivot values (prices) based on their expected alternating types from the current 'a' pivot.
    
    Args:
        current_hl_val: The hl value (1 for high, -1 for low) of the current pivot 'a'.
        hl_arr: The filtered hl array (from apply_zigzag_filters).
        zz_arr: The filtered zz array (from apply_zigzag_filters).
        current_idx: The current bar index.
        
    Returns:
        A tuple (b, c, d, e) with the corresponding pivot prices, or np.nan if not found.
    """
    b, c, d, e = np.nan, np.nan, np.nan, np.nan

    # Determine the sequence of 'expected' HL types (ehl) for b, c, d, e.
    # This directly mirrors the 'ehl' assignments and loops in Pine Script's findprevious.
    sequence_ehls = []
    if current_hl_val == 1: # Current pivot 'a' is a High
        # Pine's sequence: b (opposite type), c (same type), d (opposite type), e (same type)
        sequence_ehls = [-1, 1, -1, 1] # Looking for B (Low), C (High), D (Low), E (High)
    elif current_hl_val == -1: # Current pivot 'a' is a Low
        sequence_ehls = [1, -1, 1, -1] # Looking for B (High), C (Low), D (High), E (Low)
    else:
        return b, c, d, e # Should not happen if current zz_arr[current_idx] is valid

    search_start_idx = current_idx - 1 # Start searching backwards from the bar before current

    found_pivots = [] # Temporarily store the found zz values (prices)

    for target_ehl in sequence_ehls:
        found_current_pivot = False
        # Iterate backwards from search_start_idx to find the next pivot of target_ehl type
        for x in range(search_start_idx, -1, -1):
            if not np.isnan(hl_arr[x]) and hl_arr[x] == target_ehl:
                found_pivots.append(zz_arr[x])
                search_start_idx = x - 1 # Update search start for the next pivot (mimics Pine's 'xx')
                found_current_pivot = True
                break
        if not found_current_pivot:
            # If a pivot of the target type isn't found, Pine's loop would break,
            # and subsequent 'loc' variables would remain their initialized value (na).
            break

    # Assign found pivots to b, c, d, e, filling with NaN if not enough were found
    if len(found_pivots) > 0: b = found_pivots[0]
    if len(found_pivots) > 1: c = found_pivots[1]
    if len(found_pivots) > 2: d = found_pivots[2]
    if len(found_pivots) > 3: e = found_pivots[3]

    return b, c, d, e

# ──────────── 4) Convert filtered zigzag into final HH/LH and HL/LL flags ────────────
def finalize_hhlh_labels(df: pd.DataFrame, hl1: np.ndarray, zz1: np.ndarray):
    """
    Now that hl1 and zz1 have been filtered exactly how PineScript does,
    this function identifies HH, LH, HL, LL using Pine’s “a, b, c, d, e” logic.
    
    'a' is the current pivot value (zz1[i]).
    'b, c, d, e' are found using the `find_abcd_e` helper, which respects their type sequence.

    Returns df with 4 new boolean columns: ‘is_HH’, ‘is_LH’, ‘is_HL’, ‘is_LL’,
    and also 'zz' and 'hl' columns for the final filtered zigzag data.
    """
    n = len(df)
    hh_flag = np.zeros(n, dtype=bool)
    ll_flag = np.zeros(n, dtype=bool)
    hl_flag = np.zeros(n, dtype=bool)
    lh_flag = np.zeros(n, dtype=bool)

    for i in range(n):
        if not np.isnan(zz1[i]): # Only process if current bar is a confirmed pivot
            a = zz1[i]
            current_hl_val = hl1[i] # The type (+1 or -1) of pivot 'a'

            # Get b, c, d, e using the precise Pine Script findprevious() logic
            b, c, d, e = find_abcd_e(current_hl_val, hl1, zz1, i)

            # HH: a > b and a > c and c > b and c > d
            # Requires a, b, c, d to be non-NaN.
            if (not np.isnan(a) and not np.isnan(b) and not np.isnan(c) and not np.isnan(d) and
                    (a > b and a > c and c > b and c > d)):
                hh_flag[i] = True

            # LL: a < b and a < c and c < b and c < d
            # Requires a, b, c, d to be non-NaN.
            if (not np.isnan(a) and not np.isnan(b) and not np.isnan(c) and not np.isnan(d) and
                    (a < b and a < c and c < b and c < d)):
                ll_flag[i] = True

            # HL logic (two patterns from PineScript's `_hl` definition):
            # _hl = bool(zz) and (a >= c and b > c and b > d and d > c and d > e or a < b and a > c and b < d)
            cond1_hl = (not np.isnan(a) and not np.isnan(b) and not np.isnan(c) and
                        not np.isnan(d) and not np.isnan(e) and # All five a-e are required for this sub-condition
                        (a >= c and b > c and b > d and d > c and d > e))
            cond2_hl = (not np.isnan(a) and not np.isnan(b) and not np.isnan(c) and
                        not np.isnan(d) and # 'e' is NOT part of this sub-condition
                        (a < b and a > c and b < d))
            if cond1_hl or cond2_hl:
                hl_flag[i] = True

            # LH logic (two patterns from PineScript's `_lh` definition):
            # _lh = bool(zz) and (a <= c and b < c and b < d and d < c and d < e or a > b and a < c and b > d)
            cond1_lh = (not np.isnan(a) and not np.isnan(b) and not np.isnan(c) and
                        not np.isnan(d) and not np.isnan(e) and # All five a-e are required for this sub-condition
                        (a <= c and b < c and b < d and d < c and d < e))
            cond2_lh = (not np.isnan(a) and not np.isnan(b) and not np.isnan(c) and
                        not np.isnan(d) and # 'e' is NOT part of this sub-condition
                        (a > b and a < c and b > d))
            if cond1_lh or cond2_lh:
                lh_flag[i] = True

    df["is_HH"] = hh_flag
    df["is_LL"] = ll_flag
    df["is_HL"] = hl_flag
    df["is_LH"] = lh_flag
    df["zz"] = zz1 # Store the final filtered zigzag prices
    df["hl"] = hl1 # Store the final filtered zigzag types (+1/-1)
    return df

# ──────────── 5) One true “wrapper” to run all steps at once ────────────────
def find_hhlh_pivots(df: pd.DataFrame, left_bars: int = 2, right_bars: int = 4):
    """
    Main wrapper function to compute all swing levels, support/resistance, and trend,
    mimicking the Pine Script swing/zigzag and trend logic for HH, LL, HL, LH detection.
    
    This version has been updated to more accurately reflect Pine Script's `pivothigh`,
    `pivotlow`, and `valuewhen` behavior, and the precise `a,b,c,d,e` pivot identification.

    Returns a new DataFrame (copy of df) with several new columns:
       - is_HH (boolean: higher high, based on pivot geometry)
       - is_LH (boolean: lower high, based on pivot geometry)
       - is_HL (boolean: higher low, based on pivot geometry)
       - is_LL (boolean: lower low, based on pivot geometry)
       - zz (float: final filtered zigzag price)
       - hl (float: final filtered zigzag type: +1 high, -1 low)
       - support (float: dynamic support level)
       - resistance (float: dynamic resistance level)
       - trend (float: 1 for uptrend, -1 for downtrend)
    """
    # Create a copy to avoid modifying the original DataFrame
    df_processed = df.copy().reset_index(drop=True)
    n = len(df_processed)
    close_prices = df_processed['close'].values

    # Step 1: Compute raw pivots
    raw_ph, raw_pl = compute_raw_pivots(df_processed, left_bars, right_bars)

    # Step 2: Build initial zigzag arrays (hl0, zz0)
    hl0, zz0 = build_initial_zigzag(df_processed, raw_ph, raw_pl)

    # Step 3: Apply Pine Script’s “valuewhen”-based zigzag filters
    hl1, zz1 = apply_zigzag_filters(df_processed, raw_ph, raw_pl, hl0, zz0)
    
    # Step 4: Finalize HH/LH/HL/LL flags using precise a,b,c,d,e logic
    df_processed = finalize_hhlh_labels(df_processed, hl1, zz1) # This populates is_HH, etc., zz, hl

    # Step 5: Calculate dynamic support/resistance and trend
    res_vals = np.full(n, np.nan, dtype=float)
    sup_vals = np.full(n, np.nan, dtype=float)
    trend_vals = np.full(n, np.nan, dtype=float)

    for i in range(n):
        # Initialize current bar's S/R with previous values if no update
        current_res_val = res_vals[i-1] if i > 0 else np.nan
        current_sup_val = sup_vals[i-1] if i > 0 else np.nan
        current_trend_val = trend_vals[i-1] if i > 0 else np.nan # nz(trend1[1])

        # First set of res/sup updates (Pine: res := _lh ? zz : res[1] and sup := _hl ? zz : sup[1])
        if df_processed["is_LH"].iloc[i]:
            current_res_val = df_processed["zz"].iloc[i]
        
        if df_processed["is_HL"].iloc[i]:
            current_sup_val = df_processed["zz"].iloc[i]
        
        res_vals[i] = current_res_val
        sup_vals[i] = current_sup_val

        # Trend calculation (Pine: trend1 := close > res ? 1 : (close < sup ? -1 : nz(trend1[1])))
        if close_prices[i] > res_vals[i]:
            current_trend_val = 1.0 # Uptrend
        elif close_prices[i] < sup_vals[i]:
            current_trend_val = -1.0 # Downtrend
        # else: current_trend_val remains its previous value (or NaN)
        trend_vals[i] = current_trend_val

        # Second set of res/sup updates (Pine: res := trend1 == 1 and _hh or trend1 == -1 and _lh ? zz : res)
        # Apply these on the *current bar's* already updated res/sup values.
        if (not np.isnan(trend_vals[i])):
            if (trend_vals[i] == 1.0 and df_processed["is_HH"].iloc[i]) or \
               (trend_vals[i] == -1.0 and df_processed["is_LH"].iloc[i]):
                res_vals[i] = df_processed["zz"].iloc[i]
            
            if (trend_vals[i] == 1.0 and df_processed["is_HL"].iloc[i]) or \
               (trend_vals[i] == -1.0 and df_processed["is_LL"].iloc[i]):
                sup_vals[i] = df_processed["zz"].iloc[i]

    df_processed["resistance"] = res_vals
    df_processed["support"] = sup_vals
    df_processed["trend"] = trend_vals

    return df_processed

# ──────────── 6) Utility to fetch “last confirmed swing” of each type ────────────────
def get_last_swing_points(df: pd.DataFrame):
    """
    After calling find_hhlh_pivots(), this returns a 4-tuple of the last
    confirmed swing points (HH, LL, HL, LH).

    Each element in the tuple is a dictionary { 'timestamp': Timestamp, 'price': float }
    or None if no such swing point is found. The price returned is the `zz` (zigzag)
    price, which is the actual pivot level confirmed by the strategy.
    """
    # Helper to create dict from row, using the 'zz' price
    def row_to_dict(row):
        return {'timestamp': row['timestamp'], 'price': row['zz']}

    last_hh = df[df['is_HH']].iloc[-1] if df['is_HH'].any() else None
    last_ll = df[df['is_LL']].iloc[-1] if df['is_LL'].any() else None
    last_hl = df[df['is_HL']].iloc[-1] if df['is_HL'].any() else None
    last_lh = df[df['is_LH']].iloc[-1] if df['is_LH'].any() else None
    
    return (
        row_to_dict(last_hh) if last_hh is not None else None,
        row_to_dict(last_ll) if last_ll is not None else None,
        row_to_dict(last_hl) if last_hl is not None else None,
        row_to_dict(last_lh) if last_lh is not None else None,
    )
