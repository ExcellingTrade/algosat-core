#!/usr/bin/env python3
import datetime
import time
from typing import List
from urllib.parse import parse_qs, urlparse

import pandas as pd
import pyotp
from kiteconnect import KiteConnect
from seleniumbase import SB

# ─── CREDENTIALS ───────────────────────────────────────────────
API_KEY = "tmbs3tp9sqareij7"
API_SECRET = "ewjtz3k0oonhubn89tgzfrj4kahu33hl"
USER_ID = "HU6119"
PASSWORD = "Sat@5858"
TOTP_SECRET = "DDEULTWO73Q65KT7AO3SQQM5Y24BLZ7K"
# ───────────────────────────────────────────────────────────────

pd.set_option('display.width', 1500)
# pd.set_option('display.height', 1500)
pd.set_option('display.max_columns', 75)
pd.set_option('display.max_rows', 2500)



def get_request_token():
    kite = KiteConnect(api_key=API_KEY)
    login_url = kite.login_url()

    with SB(uc=True, headless=False, test=False, save_screenshot=False) as sb:
        sb.open(login_url)
        sb.wait_for_element_visible("#userid", timeout=20)
        sb.type("#userid", USER_ID)
        sb.type("#password", PASSWORD)
        sb.click('button[type="submit"]')
        sb.wait_for_ready_state_complete(10)

        # TOTP step
        sb.wait_for_element_visible("#userid", timeout=20)
        totp_code = pyotp.TOTP(TOTP_SECRET).now()
        sb.type("#userid", totp_code)
        sb.sleep(2)

        # Wait for redirect
        start_time = time.time()
        max_wait = 60
        final_url = None
        while time.time() - start_time < max_wait:
            current_url = sb.get_current_url()
            if "request_token" in current_url:
                final_url = current_url
                break
            sb.sleep(1)
            print("⏳ Waiting for redirect…")

        sb.save_screenshot("zerodha_final.png")
        print("🔗 Final URL:", final_url)

    if final_url:
        parsed = urlparse(final_url)
        token = parse_qs(parsed.query).get("request_token", [None])[0]
        return token
    return None


def get_access_token(request_token):
    kite = KiteConnect(api_key=API_KEY)
    data = kite.generate_session(request_token, api_secret=API_SECRET)
    print(data['access_token'])
    return data["access_token"]


def get_nearest_expiry(symbol: str, ref_date: datetime.date = None) -> datetime.date:
    if ref_date is None:
        ref_date = datetime.date.today()
    days_ahead = (3 - ref_date.weekday() + 7) % 7 if symbol.upper() == "NIFTY" else 0
    return ref_date + datetime.timedelta(days=days_ahead)


def get_strike_list(kite, symbol: str, expiry, atm_count=2, itm_count=50, otm_count=50) -> List[str]:
    instruments = pd.DataFrame(kite.instruments("NFO"))
    instruments['expiry'] = pd.to_datetime(instruments['expiry'])

    expiry = pd.to_datetime(expiry)

    df = instruments[
        (instruments['name'] == symbol.upper()) &
        (instruments['segment'] == 'NFO-OPT') &
        (instruments['expiry'] == expiry)
        ].copy()
    ltp_symbol = f"NSE:{symbol.upper()}"
    if symbol.upper() == 'NIFTY':
        ltp_symbol = f"NSE:{symbol.upper()} 50"
    ltp = kite.ltp(ltp_symbol)
    spot = ltp[ltp_symbol]["last_price"]

    df["_strike_val"] = df["strike"].astype(float)

    ce = df[df["instrument_type"] == "CE"]
    pe = df[df["instrument_type"] == "PE"]

    all_strikes = sorted(df["_strike_val"].unique())
    atm_strike = min(all_strikes, key=lambda x: abs(x - spot))

    atm = df[df["_strike_val"] == atm_strike]["tradingsymbol"].tolist()

    ce_itm = ce[ce["_strike_val"] < atm_strike].copy().sort_values(by="_strike_val", ascending=False).head(itm_count)
    ce_otm = ce[ce["_strike_val"] > atm_strike].copy().sort_values(by="_strike_val").head(otm_count)
    pe_itm = pe[pe["_strike_val"] > atm_strike].copy().sort_values(by="_strike_val").head(itm_count)
    pe_otm = pe[pe["_strike_val"] < atm_strike].copy().sort_values(by="_strike_val", ascending=False).head(otm_count)

    picks = atm[:atm_count] + ce_itm["tradingsymbol"].tolist() + ce_otm["tradingsymbol"].tolist() + \
            pe_itm["tradingsymbol"].tolist() + pe_otm["tradingsymbol"].tolist()
    return picks


def get_token(kite, symbol: str, ins_type="EQ"):
    instruments = kite.instruments()
    df = pd.DataFrame(instruments)
    # print(df)
    segment = "NSE"
    exchange = "NSE"
    if ins_type == "EQ":
        segment = "NSE"
        exchange = "NSE"

    elif ins_type == 'OP':
        segment = "NFO-OPT"
        exchange = "NFO"
    elif ins_type == "FO":
        segment = "NFO-FUT"
        exchange = "NFO"
    elif ins_type == "MCX-OP":
        segment = "MCX-OPT"
        exchange = "MCX"
    elif ins_type == "MCX":
        segment = "MCX-FUT"
        exchange = "MCX"
    print(df.tail(2))
    filtered = df[
        (df['segment'] == 'NSE') &
        (df['instrument_type'] == 'EQ') &
        (df['exchange'] == "NSE") &
        (df['tradingsymbol'].str.contains(symbol))
        # (df['tradingsymbol'].str.contains(symbol))
        # (df['expiry'] == '2025-05-22')
        ]
    print(filtered)
    # print(exchange, segment, symbol)
    # for i in instruments:
    #     if i['exchange'] == exchange:
    #         print(i)
    #         # return i["instrument_token"]
    # raise Exception(f"Token not found for {symbol}")
    return


def get_history(kite, symbol: str, fromdate: str, todate: str, interval="5minute"):
    try:
        return kite.historical_data(symbol, fromdate, todate, interval)
    except Exception as e:
        print(f"❌ Failed for {symbol}: {e}")
        return []


# def place_order(symbol, action, qty, entryprice, triggerprice=None, stoploss=None, squareoff=None, ins_type="EQ",
#                 trailing=None,
#                 ordertype="SL", producttype="CNC", variety=None):
#     """
#             placing an order, many fields are optional and are not required
#     :param symbol: Scrip Name
#     :param action: Action - Buy or Sell
#     :param qty:  No of quantity
#     :param entryprice: Entry Price
#     :param stoploss: Stoploss
#     :param target: Target
#     :param ins_type: Instrument Type: Supports EQ (NSE_EQ), FO (NSE_FO), MCX, NCD (NSE_CURRENCY)
#     :param trailing: Trialing ticks - Should be multiple of 20 (20 * 0.05). Should be 20 for 1 point
#     :param ordertype: Type of Order. For ex: Stoploss Limit, Market Order
#     :param producttype: Product Type. for ex, Delivery, OneCancelOther, Bracket Order
#     :return: Dictionary of repsonse received form Place Order
#     """
#     global u
#     instrument = u.EXCHANGE_NSE
#     if ins_type == "EQ":
#         instrument = u.EXCHANGE_NSE
#     elif ins_type in ["FO", "OP"]:
#         instrument = u.EXCHANGE_NFO
#     elif ins_type in ["MCX", "MCX-OP"]:
#         instrument = u.EXCHANGE_MCX
#     elif ins_type == "CDS":
#         instrument = u.EXCHANGE_CDS
#     try:
#         segment = "NSE"
#         exchange = "NSE"
#         if ins_type == "EQ":
#             segment = "NSE"
#             exchange = "NSE"
#
#         elif ins_type == 'OP':
#             segment = "NFO-OPT"
#             exchange = "NFO"
#         elif ins_type == "FO":
#             segment = "NFO-FUT"
#             exchange = "NFO"
#         elif ins_type == "MCX-OP":
#             segment = "MCX-OPT"
#             exchange = "MCX"
#         elif ins_type == "MCX":
#             segment = "MCX-FUT"
#             exchange = "MCX"
#         print("Qty is {0}".format(qty))
#         scrip = get_instrument(symbol, segment, exchange)
#         return u.place_order(tradingsymbol=scrip.get('tradingsymbol'),
#                              exchange=instrument,
#                              transaction_type=action.upper(),
#                              quantity=int(qty) if 'MCX' in ins_type else qty,
#                              order_type=ordertype,
#                              price=float(entryprice),
#                              trigger_price=float(triggerprice),
#                              product=producttype,
#                              squareoff=squareoff,
#                              stoploss=stoploss,
#                              variety=variety,
#                              trailing_stoploss=trailing,
#                              tag="AlgoOrder")
#     except Exception as error:
#         logger.info("Unable to place order for {0}. Error: {1}".format(symbol, error))
#         print("Unable to place order for {0}. Error: {1}".format(symbol, error))
#         return None

import numpy as np
import pandas as pd


# ──────────────── Helper: find the previous non-NaN in a 1D numpy array ────────────────
def previous_non_nan(arr: np.ndarray, idx: int):
    """
    Return the last non-nan value in 'arr' at an index < idx.
    If none found, returns np.nan.
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
    """
    highs = df["high"].values
    lows = df["low"].values
    n = len(df)

    raw_ph = np.zeros(n, dtype=bool)
    raw_pl = np.zeros(n, dtype=bool)

    for i in range(left_bars, n - right_bars):
        # Check pivot high condition
        h = highs[i]
        if (h > highs[i - left_bars: i]).all() and (h > highs[i + 1: i + 1 + right_bars]).all():
            raw_ph[i] = True

        # Check pivot low condition
        l = lows[i]
        if (l < lows[i - left_bars: i]).all() and (l < lows[i + 1: i + 1 + right_bars]).all():
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

    Steps:
      1. Copy hl0 → hl1 (working copy), zz0 → zz1.
      2. Loop forward i=0→n–1 in strict date order.
      3. At i, look up the most recent non-NaN hl1 (this is “valuewhen(bool(hl), hl, 1)”).
      4. At i, look up the most recent non-NaN zz1 (this is “valuewhen(bool(zz), zz, 1)”).
      5. Apply filter #1 if raw_pl[i] and hl1[i]==–1 and prev_hl_value==–1 and lows[i] > prev_zz_value → drop this pivot low.
      6. Apply filter #2 if raw_ph[i] and hl1[i]==1 and prev_hl_value==1 and highs[i] < prev_zz_value → drop this pivot high.
      7. Recompute prev_hl/prev_zz “one step back” (for use in steps #3–#4 for the next pivot).
      8. Filter #3, #4 check if a pivot low appears (hl1[i]==–1) but it’s actually higher than “previous pivot low,” etc.
      9. At end, if hl1[i] became NaN, force zz1[i]=NaN.

    Returns two numpy arrays, hl1 and zz1, after all filters.
    """
    highs = df["high"].values
    lows = df["low"].values
    n = len(df)

    # Make working copies
    hl1 = hl0.copy()
    zz1 = zz0.copy()

    # We’ll need a helper to track “most recent non-NaN” at each step.
    # But because we modify hl1/zz1 in place, “previous_non_nan(hl1, i)” will give exactly
    # what Pine’s valuewhen(bool(hl), hl, 1) does at bar i.

    for i in range(n):
        # 1) Grab prev_hl_val = valuewhen(bool(hl1), hl1, 1)
        prev_hl_val = previous_non_nan(hl1, i)
        # 2) Grab prev_zz_val = valuewhen(bool(zz1), zz1, 1)
        prev_zz_val = previous_non_nan(zz1, i)

        # 3) If this bar is a “raw pivot low” and previous hl was –1, and current low > previous pivot value → drop
        if raw_pl[i] and (hl1[i] == -1.0) and (prev_hl_val == -1.0) and (lows[i] > prev_zz_val):
            hl1[i] = np.nan
            zz1[i] = np.nan

        # 4) Re-grab prev_hl_val2 / prev_zz_val2 after possibly removing above
        prev_hl_val2 = previous_non_nan(hl1, i)
        prev_zz_val2 = previous_non_nan(zz1, i)

        # 5) If this bar is a “raw pivot high” and previous hl was +1, and current high < previous pivot value → drop
        if raw_ph[i] and (hl1[i] == 1.0) and (prev_hl_val2 == 1.0) and (highs[i] < prev_zz_val2):
            hl1[i] = np.nan
            zz1[i] = np.nan

        # 6) Re-grab prev_hl_val3 / prev_zz_val3
        prev_hl_val3 = previous_non_nan(hl1, i)
        prev_zz_val3 = previous_non_nan(zz1, i)

        # 7) If hl1[i] == -1 (pivot low), but previous hl was +1 (pivot high), and current zz > previous zz → drop this low
        if raw_pl[i] and (hl1[i] == -1.0) and (prev_hl_val3 == 1.0) and (zz1[i] > prev_zz_val3):
            hl1[i] = np.nan
            zz1[i] = np.nan

        # 8) Re-grab prev_hl_val4 / prev_zz_val4
        prev_hl_val4 = previous_non_nan(hl1, i)
        prev_zz_val4 = previous_non_nan(zz1, i)

        # 9) If hl1[i] == +1 (pivot high), but previous hl was –1 (pivot low), and current zz < previous zz → drop this high
        if raw_ph[i] and (hl1[i] == 1.0) and (prev_hl_val4 == -1.0) and (zz1[i] < prev_zz_val4):
            hl1[i] = np.nan
            zz1[i] = np.nan

        # 10) Finally, if we’ve removed hl1[i] (set it to NaN), force zz1[i] = NaN.
        # This matches Pine’s last line:  `zz := na(hl) ? na : zz`
        if np.isnan(hl1[i]):
            zz1[i] = np.nan

    return hl1, zz1


# ──────────────── 4) Convert filtered zigzag into final HH/LH and HL/LL flags ────────────────
def finalize_hhlh_labels(df: pd.DataFrame, hl1: np.ndarray, zz1: np.ndarray):
    """
    Now that hl1 and zz1 have been filtered exactly how PineScript does,
    we find _exact_ HH, LH, HL, LL using Pine’s “a, b, c, d, e” logic:

      _hh = bool(zz) and a > b and a > c and c > b and c > d
      _ll = bool(zz) and a < b and a < c and c < b and c < d
      _hl = bool(zz) and
              ( (a >= c and b > c and b > d and d > c and d > e)
                or (a < b and a > c and b < d) )
      _lh = bool(zz) and
              ( (a <= c and b < c and b < d and d < c and d < e)
                or (a > b and a < c and b > d) )

    Here, “a” is the *current* pivot value (zz1[i]);
    “b” is the previous non-NaN pivot (the last pivot, high or low);
    “c” is the pivot before that;
    “d” the one before that;
    “e” the one before that.
    (If you have fewer than 5 pivots so far, any missing ones are NaN.)

    Returns df with 4 new boolean columns: ‘is_HH’, ‘is_LH’, ‘is_HL’, ‘is_LL’.
    """
    n = len(df)
    hh_flag = np.zeros(n, dtype=bool)
    ll_flag = np.zeros(n, dtype=bool)
    hl_flag = np.zeros(n, dtype=bool)
    lh_flag = np.zeros(n, dtype=bool)

    # We’ll keep a rolling list of the last five non-NaN zz1 values (from newest to oldest).
    # Each time we hit a new pivot (zz1[i] not NaN), we push it to index 0.  Then hh/ll/hl/lh
    # tests use that list (a=last_five[0], b=last_five[1], …).
    last_five = []

    for i in range(n):
        if not np.isnan(zz1[i]):
            # Insert current pivot at front
            last_five.insert(0, zz1[i])
            if len(last_five) > 5:
                last_five.pop()

            # Unpack a, b, c, d, e (or NaN if fewer than 5 pivots so far)
            a = last_five[0] if len(last_five) > 0 else np.nan
            b = last_five[1] if len(last_five) > 1 else np.nan
            c = last_five[2] if len(last_five) > 2 else np.nan
            d = last_five[3] if len(last_five) > 3 else np.nan
            e = last_five[4] if len(last_five) > 4 else np.nan

            # HH: a > b and a > c and c > b and c > d
            if (
                    not np.isnan(a) and not np.isnan(b) and not np.isnan(c) and not np.isnan(d)
                    and (a > b and a > c and c > b and c > d)
            ):
                hh_flag[i] = True

            # LL: a < b and a < c and c < b and c < d
            if (
                    not np.isnan(a) and not np.isnan(b) and not np.isnan(c) and not np.isnan(d)
                    and (a < b and a < c and c < b and c < d)
            ):
                ll_flag[i] = True

            # HL logic (two patterns):
            cond1 = (
                    not np.isnan(a) and not np.isnan(b) and not np.isnan(c)
                    and not np.isnan(d) and not np.isnan(e)
                    and (a >= c and b > c and b > d and d > c and d > e)
            )
            cond2 = (
                    not np.isnan(a) and not np.isnan(b) and not np.isnan(c)
                    and not np.isnan(d)
                    and (a < b and a > c and b < d)
            )
            if cond1 or cond2:
                hl_flag[i] = True

            # LH logic (two patterns):
            cond3 = (
                    not np.isnan(a) and not np.isnan(b) and not np.isnan(c)
                    and not np.isnan(d) and not np.isnan(e)
                    and (a <= c and b < c and b < d and d < c and d < e)
            )
            cond4 = (
                    not np.isnan(a) and not np.isnan(b) and not np.isnan(c)
                    and not np.isnan(d)
                    and (a > b and a < c and b > d)
            )
            if cond3 or cond4:
                lh_flag[i] = True

    # Attach these new boolean columns to the DataFrame
    df["is_HH"] = hh_flag
    df["is_LL"] = ll_flag
    df["is_HL"] = hl_flag
    df["is_LH"] = lh_flag
    return df


# ──────────────── 5) One true “wrapper” to run all steps at once ────────────────
def find_pivots_and_label(df: pd.DataFrame, left_bars: int = 2, right_bars: int = 4):
    """
    1) Sorts df by 'date' ascending.
    2) Computes raw_ph / raw_pl (left/right pivot).
    3) Builds initial zigzag arrays hl0/zz0.
    4) Applies PineScript's four zigzag filters (valuewhen logic).
    5) Finalizes HH/LH/HL/LL exactly like your Pine indicator.
    Returns a new DataFrame (copy of df) with four extra boolean columns:
       - is_HH (higher high)
       - is_LH (lower high)
       - is_HL (higher low)
       - is_LL (lower low)
    """
    # 1) Sort by date
    df2 = df.sort_values("date").reset_index(drop=True)

    # 2) raw pivots
    raw_ph, raw_pl = compute_raw_pivots(df2, left_bars, right_bars)

    # 3) initial zigzag arrays
    hl0, zz0 = build_initial_zigzag(df2, raw_ph, raw_pl)

    # 4) apply Pine’s zigzag filters
    hl1, zz1 = apply_zigzag_filters(df2, raw_ph, raw_pl, hl0, zz0)

    # 5) finalize HH/LH/HL/LL
    df3 = finalize_hhlh_labels(df2, hl1, zz1)

    return df3


# ──────────────── 6) Utility to fetch “last confirmed swing” of each type ────────────────
def get_last_swing_points(df: pd.DataFrame):
    """
    After calling find_pivots_and_label(), this returns a 4-tuple:
      ( last_HH, last_LL, last_HL, last_LH ).

    Each is a dict { 'date': Timestamp, 'price': float } or None if not found.
    """
    # HH → take the last row where is_HH == True
    hh_mask = df["is_HH"] == True
    hh_row = df[hh_mask].iloc[-1] if hh_mask.any() else None

    # LL → take the last row where is_LL == True
    ll_mask = df["is_LL"] == True
    ll_row = df[ll_mask].iloc[-1] if ll_mask.any() else None

    # HL → the last row where is_HL == True
    hl_mask = df["is_HL"] == True
    hl_row = df[hl_mask].iloc[-1] if hl_mask.any() else None

    # LH → the last row where is_LH == True
    lh_mask = df["is_LH"] == True
    lh_row = df[lh_mask].iloc[-1] if lh_mask.any() else None

    last_hh = {
        "date": hh_row["date"],
        "price": hh_row["high"]
    } if hh_row is not None else None

    last_ll = {
        "date": ll_row["date"],
        "price": ll_row["low"]
    } if ll_row is not None else None

    last_hl = {
        "date": hl_row["date"],
        "price": hl_row["low"]
    } if hl_row is not None else None

    last_lh = {
        "date": lh_row["date"],
        "price": lh_row["high"]
    } if lh_row is not None else None

    return last_hh, last_ll, last_hl, last_lh


def main():
    print("🔐 Logging in...")
    # req_token = get_request_token()
    # if not req_token:
    #     print("❌ Could not retrieve request token.")
    #     return
    #
    # access_token = get_access_token(req_token)
    # print("✅ Access token obtained.")
    access_token = 'tcI8kbY59MrIvlhaFu5uFBGgP0ioka1L'

    kite = KiteConnect(api_key=API_KEY)
    kite.set_access_token(access_token)
    # print(kite.ltp(256265))

    instruments = pd.DataFrame(kite.instruments("NSE"))

    # print(instruments)
    # quit()

    # expiry = get_nearest_expiry("NIFTY")
    # print("📅 Nearest expiry:", expiry)
    #
    # strikes = get_strike_list(kite, "NIFTY", expiry)
    # print(f"🎯 Total strikes selected: {len(strikes)}")
    # order_details = kite.orders()
    # statuses = [d['status'] for d in order_details]
    # print(statuses)
    # print(order_details)
    # for orders in order_details:
    #     print(f"{orders['order_id']}:{orders['status']}")
    #     # print(orders['order_id'])
    today = datetime.datetime.now()
    fromdate = (today - datetime.timedelta(days=20)).strftime("%Y-%m-%d %H:%M:%S")
    todate = today.strftime("%Y-%m-%d %H:%M:%S")
    # fromdate = '2025-05-20 09:15:00'
    # todate = '2025-05-20 09:20:00'
    # print(get_token(kite, "BHARTIARTL", ins_type = "EQ"))
    # quit()
    symbol = 2714625 #Airtel
    # symbol = 2953217 #TCS
    # symbol = 341249 #HDFCBANK
    # symbol = 81153 #BajajFiannce
    # symbol = 256265 #Nifty
    # fromdate = '2025-05-10 09:15:00'
    # todate = '2025-05-30 15:20:00'
    print(f"From {fromdate} to {todate}")
    data = get_history(kite, symbol, fromdate, todate)
    print(pd.DataFrame(data).tail(2))
    history_data = pd.DataFrame(data)
    df2 = find_pivots_and_label(history_data, left_bars=2, right_bars=4)

    # Now df2 has these new boolean columns:
    #    df2["is_HH"]  → True exactly where Pine would draw a green “HH” dot
    #    df2["is_LH"]  → True exactly where Pine draws a red “LH” dot
    #    df2["is_HL"]  → True exactly where Pine draws a green “HL” dot
    #    df2["is_LL"]  → True exactly where Pine draws a red “LL” dot
    #
    # # 3) If you want the final “last confirmed pivot” of each type (just like your Pine helper),
    last_hh, last_ll, last_hl, last_lh = get_last_swing_points(df2)

    print("Last HH (swing high):", last_hh)
    print("Last LL (swing low):", last_ll)
    print("Last HL (higher low):", last_hl)
    print("Last LH (lower high):", last_lh)
    quit()
    available = kite.margins('equity')
    print(available)
    print(f"available {available.get('cash', 0.0)}, utilized: {available.get('live_balance')}")
    # print(pd.DataFrame(kite.margins('equity')['net']))
    print(kite.orders())
    # [{'account_id': 'HU6119', 'placed_by': 'HU6119', 'order_id': '250604600550963',
    #   'exchange_order_id': '1100000051207595', 'parent_order_id': None, 'status': 'TRIGGER PENDING',
    #   'status_message': None, 'status_message_raw': None, 'order_timestamp': datetime.datetime(2025, 6, 4, 10, 48, 24),
    #   'exchange_update_timestamp': '2025-06-04 10:48:24',
    #   'exchange_timestamp': datetime.datetime(2025, 6, 4, 10, 48, 24), 'variety': 'regular', 'modified': False,
    #   'exchange': 'NFO', 'tradingsymbol': 'NIFTY2560525600CE', 'instrument_token': 10373890, 'order_type': 'SL',
    #   'transaction_type': 'BUY', 'validity': 'DAY', 'validity_ttl': 0, 'product': 'MIS', 'quantity': 75,
    #   'disclosed_quantity': 0, 'price': 1.4, 'trigger_price': 1.35, 'average_price': 0, 'filled_quantity': 0,
    #   'pending_quantity': 75, 'cancelled_quantity': 0, 'market_protection': 0, 'meta': {}, 'tag': None,
    #   'guid': '01Xwlt75Sl5472N'}]
    # [{'account_id': 'HU6119', 'placed_by': 'HU6119', 'order_id': '250604600550963',
    #   'exchange_order_id': '1100000051207595', 'parent_order_id': None, 'status': 'COMPLETE', 'status_message': None,
    #   'status_message_raw': None, 'order_timestamp': datetime.datetime(2025, 6, 4, 11, 35, 56),
    #   'exchange_update_timestamp': '2025-06-04 11:35:56',
    #   'exchange_timestamp': datetime.datetime(2025, 6, 4, 11, 35, 56), 'variety': 'regular', 'modified': True,
    #   'exchange': 'NFO', 'tradingsymbol': 'NIFTY2560525600CE', 'instrument_token': 10373890, 'order_type': 'MARKET',
    #   'transaction_type': 'BUY', 'validity': 'DAY', 'validity_ttl': 0, 'product': 'MIS', 'quantity': 75,
    #   'disclosed_quantity': 0, 'price': 0, 'trigger_price': 0, 'average_price': 1.25, 'filled_quantity': 75,
    #   'pending_quantity': 0, 'cancelled_quantity': 0, 'market_protection': 0, 'meta': {}, 'tag': None,
    #   'guid': '01Xwlt75Sl5472N'}]
    print(kite.positions())
    # {'net': [{'tradingsymbol': 'NIFTY2560525600CE', 'exchange': 'NFO', 'instrument_token': 10373890, 'product': 'MIS',
    #           'quantity': 75, 'overnight_quantity': 0, 'multiplier': 1, 'average_price': 1.25, 'close_price': 0,
    #           'last_price': 1.25, 'value': -93.75, 'pnl': 0, 'm2m': 0, 'unrealised': 0, 'realised': 0,
    #           'buy_quantity': 75, 'buy_price': 1.25, 'buy_value': 93.75, 'buy_m2m': 93.75, 'sell_quantity': 0,
    #           'sell_price': 0, 'sell_value': 0, 'sell_m2m': 0, 'day_buy_quantity': 75, 'day_buy_price': 1.25,
    #           'day_buy_value': 93.75, 'day_sell_quantity': 0, 'day_sell_price': 0, 'day_sell_value': 0}], 'day': [
    #     {'tradingsymbol': 'NIFTY2560525600CE', 'exchange': 'NFO', 'instrument_token': 10373890, 'product': 'MIS',
    #      'quantity': 75, 'overnight_quantity': 0, 'multiplier': 1, 'average_price': 1.25, 'close_price': 0,
    #      'last_price': 1.25, 'value': -93.75, 'pnl': 0, 'm2m': 0, 'unrealised': 0, 'realised': 0, 'buy_quantity': 75,
    #      'buy_price': 1.25, 'buy_value': 93.75, 'buy_m2m': 93.75, 'sell_quantity': 0, 'sell_price': 0, 'sell_value': 0,
    #      'sell_m2m': 0, 'day_buy_quantity': 75, 'day_buy_price': 1.25, 'day_buy_value': 93.75, 'day_sell_quantity': 0,
    #      'day_sell_price': 0, 'day_sell_value': 0}]}
    print("*" * 50)
    trades = kite.positions()
    orders = kite.orders()
    for trade in trades['net']:
        print(trade)
    print("*"*50)
    for order in orders:
        print(order)
    quotes = kite.ltp(["NFO:NIFTY2560525600CE","NFO:NIFTY2560525600PE"])
    print(quotes)
    print("*" * 150)
    print(kite.margins())
    # {'equity': {'enabled': True, 'net': 39510.8,
    #             'available': {'adhoc_margin': 0, 'cash': 36923.4, 'opening_balance': 36923.4, 'live_balance': 36923.4,
    #                           'collateral': 2587.4, 'intraday_payin': 0},
    #             'utilised': {'debits': 0, 'exposure': 0, 'm2m_realised': 0, 'm2m_unrealised': 0, 'option_premium': 0,
    #                          'payout': 0, 'span': 0, 'holding_sales': 0, 'turnover': 0, 'liquid_collateral': 0,
    #                          'stock_collateral': 2587.4, 'equity': 0, 'delivery': 0}},
    #  'commodity': {'enabled': True, 'net': 0,
    #                'available': {'adhoc_margin': 0, 'cash': 0, 'opening_balance': 0, 'live_balance': 0, 'collateral': 0,
    #                              'intraday_payin': 0},
    #                'utilised': {'debits': 0, 'exposure': 0, 'm2m_realised': 0, 'm2m_unrealised': 0, 'option_premium': 0,
    #                             'payout': 0, 'span': 0, 'holding_sales': 0, 'turnover': 0, 'liquid_collateral': 0,
    #                             'stock_collateral': 0, 'equity': 0, 'delivery': 0}}}

    # {'equity': {'enabled': True, 'net': 35689.700000000004,
    #             'available': {'adhoc_margin': 0, 'cash': 33115.9, 'opening_balance': 33115.9, 'live_balance': 33115.9,
    #                           'collateral': 2573.8, 'intraday_payin': 0},
    #             'utilised': {'debits': 0, 'exposure': 0, 'm2m_realised': 4426.5, 'm2m_unrealised': 0,
    #                          'option_premium': 0, 'payout': 0, 'span': 0, 'holding_sales': 0, 'turnover': 0,
    #                          'liquid_collateral': 0, 'stock_collateral': 2573.8, 'equity': 0, 'delivery': 0}},
    #  'commodity': {'enabled': True, 'net': 0,
    #                'available': {'adhoc_margin': 0, 'cash': 0, 'opening_balance': 0, 'live_balance': 0, 'collateral': 0,
    #                              'intraday_payin': 0},
    #                'utilised': {'debits': 0, 'exposure': 0, 'm2m_realised': 0, 'm2m_unrealised': 0, 'option_premium': 0,
    #                             'payout': 0, 'span': 0, 'holding_sales': 0, 'turnover': 0, 'liquid_collateral': 0,
    #                             'stock_collateral': 0, 'equity': 0, 'delivery': 0}}}
    # {'equity': {'enabled': True, 'net': 10794.200000000004,
    #             'available': {'adhoc_margin': 0, 'cash': 33115.9, 'opening_balance': 33115.9,
    #                           'live_balance': 8220.400000000001, 'collateral': 2573.8, 'intraday_payin': 0},
    #             'utilised': {'debits': 24895.5, 'exposure': 0, 'm2m_realised': 4426.5, 'm2m_unrealised': 0,
    #                          'option_premium': 24895.5, 'payout': 0, 'span': 0, 'holding_sales': 0, 'turnover': 0,
    #                          'liquid_collateral': 0, 'stock_collateral': 2573.8, 'equity': 0, 'delivery': 0}},
    #  'commodity': {'enabled': True, 'net': 0,
    #                'available': {'adhoc_margin': 0, 'cash': 0, 'opening_balance': 0, 'live_balance': 0, 'collateral': 0,
    #                              'intraday_payin': 0},
    #                'utilised': {'debits': 0, 'exposure': 0, 'm2m_realised': 0, 'm2m_unrealised': 0, 'option_premium': 0,
    #                             'payout': 0, 'span': 0, 'holding_sales': 0, 'turnover': 0, 'liquid_collateral': 0,
    #                             'stock_collateral': 0, 'equity': 0, 'delivery': 0}}}
    #
    # for symbol in strikes:
    #
    #     data = get_history(kite, symbol, fromdate, todate)
    #     print(f"📘 {symbol}: {len(data)} candles")
    #     print(data)

    # token = get_token(kite, "NIFTY2560524750PE")
    # print(f"placing order for symbol {'NIFTY2560524750PE'} token {token}")
    # symbol = "NIFTY2560524750PE"
    # try:
    #     response = kite.place_order(tradingsymbol=symbol,
    #                                 exchange=kite.EXCHANGE_NFO,
    #                                 transaction_type="BUY",
    #                                 quantity=75,
    #                                 order_type="SL",
    #                                 price=323.05,
    #                                 trigger_price=322.05,
    #                                 product="MIS",
    #                                 variety="regular",
    #                                 tag="AlgoOrder")
    #     print(response)
    # except Exception as e:
    #     print(f"Error placing order: {e}")
    # orders = pd.DataFrame(kite.orders())
    # print(orders)
    # positions = pd.DataFrame(kite.positions()['net'])
    # print(positions)
    # #
    # try:
    #     response = kite.place_order(tradingsymbol="NIFTYa2560525600CE",
    #                                 exchange="NFO",
    #                                 transaction_type="SELL",
    #                                 quantity=75,
    #                                 order_type="MARKET",
    #                                 # price=223.05,
    #                                 # trigger_price=222.05,
    #                                 product="MIS",
    #                                 variety="regular",
    #                                 tag = "AlgoOrder")
    #
    #
    #     print(f"Value of response: {response}. Type {type(response)}")
    # except Exception as error:
    #     print(f"error placing order . Error: {error}")
    # orderdetails = kite.order_history(250602500990951)
    # print(orderdetails[0].keys())
    # statuses = [d['status'] for d in orderdetails]
    # statuse_messages = [d['status_message'] for d in orderdetails]
    # statuse_messages_raw = [d['status_message_raw'] for d in orderdetails]
    # print(statuses[-1])
    # print(statuse_messages)
    # print(statuse_messages_raw)
    # quit()


if __name__ == "__main__":
    main()
