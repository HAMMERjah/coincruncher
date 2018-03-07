# app.signals
import logging
from pymongo import ReplaceOne, UpdateOne
from datetime import timedelta
import pandas as pd
import numpy as np
from app import get_db
from app.candles import db_get, last
from app.timer import Timer
from app.utils import utc_datetime as now, to_float
from docs.data import BINANCE
log = logging.getLogger('signals')

#------------------------------------------------------------------------------
def calculate_all():
    """Compute pair and aggregate signal data for Binance candles.
    """
    timer = Timer()
    _1m = timedelta(minutes=1)
    _1h = timedelta(hours=1)
    _1d = timedelta(hours=24)
    dfp = pd.DataFrame()

    # Generate signal scores for each (Pair,Freq,Period) tuple.
    for pair in BINANCE["CANDLES"]:
        c5m = last(pair,"5m")
        t5m = [c5m["open_date"] - (5*_1m), c5m["close_date"] - (5*_1m)]
        c1h = last(pair,"1h")
        t1h = [c1h["open_date"] - (1*_1h), c1h["close_date"] - (1*_1h)]
        c1d = last(pair,"1d")
        t1d = [c1d["open_date"] - (1*_1d), c1d["close_date"] - (1*_1d)]

        for n in range(1,4):
            dfp = dfp.append([
                calculate(pair, "5m", str(n*60)+"m", t5m[0]-(n*60*_1m), end=t5m[1]),
                calculate(pair, "1h", str(n*24)+"h", t1h[0]-(n*24*_1h), end=t1h[1]),
                calculate(pair, "1d", str(n*7)+"d",  t1d[0]-(n*7*_1d), end=t1d[1])
            ])

    # Sum signals in last column for each multi-index (Pair,Freq,Period,Prop)
    dfp = dfp.sort_index()
    aggr_list = [ [n[0:-1], dfp.loc[n[0:-1]]["Signal"].sum()] for n in dfp.index.values]
    aggr_dict = {}
    for n in aggr_list:
        aggr_dict[n[0]] = n[1]

    dfa = pd.DataFrame(
        list(aggr_dict.values()),
        index=pd.MultiIndex.from_tuples(list(aggr_dict.keys())),
        columns=["signal"]
    ).sort_index()

    save_db_pairs(dfp)
    save_db_aggregate(dfa)

    log.debug("calculate_all completed in %sms", timer)

#-----------------------------------------------------------------------------
def calculate(pair, freq, period, start, end):
    """Compare candle fields to historical averages. Measure magnitude in
    number of standard deviations from the mean.
    """
    dfc = db_get(pair, freq, None)
    dfc = dfc.to_dict('record')[0]
    dfh = db_get(pair, freq, start, end=end)
    havg = dfh.describe()[1::]
    data = []

    # Price diff in past hour
    #close_1h = dfc["close"] - dfh["close"].loc[-1]

    # Price vs hist. mean/std
    c_c = dfc["close"]
    h_c = havg["close"]
    cd = c_c - h_c["mean"]
    cs = cd / h_c["std"]
    data.append([c_c, h_c["mean"], cd, h_c["std"], cs])

    # Volume vs hist. mean/std
    c_v = dfc["volume"]
    h_v = havg["volume"]
    vd = c_v - h_v["mean"]
    vs = vd / h_v["std"]
    data.append([c_v, h_v["mean"], vd, h_v["std"], vs])

    # Buy volume vs hist. mean/std
    c_bv = dfc["buy_vol"]
    h_bv = havg["buy_vol"]
    bvd = c_bv - h_bv["mean"]
    bvs = bvd / h_bv["std"]
    data.append([c_bv, h_bv["mean"], bvd, h_bv["std"], bvs])

    # Buy/sell volume ratio vs hist. mean/std
    c_br = dfc["buy_ratio"]
    h_br = havg["buy_ratio"]
    brd = c_br - h_br["mean"]
    brs = brd / h_br["std"]
    data.append([c_br, h_br["mean"], brd, h_br["std"], brs])

    # Number trades vs hist. mean/std
    c_t = dfc["trades"]
    h_t = havg["trades"]
    td = c_t - h_t["mean"]
    ts = td / h_t["std"]
    data.append([c_t, h_t["mean"], td, h_t["std"], ts])

    score = cs + vs + bvs + brs + ts
    score = round(float(score), 2)

    fields = ["Close", "Volume", "BuyVol", "BuyRatio", "Trades"]
    cols = ["Candle", "HistMean", "Diff", "HistStd", "Signal"]

    # 4-level multi-index [5 x 5] dataframe
    # i.e. BTCUSDT->1H->24H->Volume
    from app.utils import parse_period as per_to_sec
    _freq = per_to_sec(freq)[2].total_seconds()
    _period = per_to_sec(period)[2].total_seconds()

    return pd.DataFrame(
        data,
        index=pd.MultiIndex.from_product([ [pair], [_freq], [_period], fields ]),
        columns=cols
    ).astype(float).round(7)

#-----------------------------------------------------------------------------
def save_db_pairs(dfp):
    timer = Timer()
    db = get_db()
    ops=[]

    # Save signal data
    for key in dfp.index.values:
        k = key[0:-1]
        values = dfp.loc[k].values.tolist()
        ops.append(ReplaceOne(
            {"pair":k[0], "freq":k[1], "period":k[2]},
            {"pair":k[0], "freq":k[1], "period":k[2], "data":values},
            upsert=True))

    res = db.pair_signals.bulk_write(ops)
    log.debug("%s pair signals saved to db in %sms", res.modified_count, timer)

#-----------------------------------------------------------------------------
def load_db_pairs():
    """Load pair signal data from DB as multi-index dataframe.
    Returns:
        aggregate signals dataframe
            multi-index levels:
                0:"Pair"
                1:"Freq"
                2:"Period"
                3:"Prop"   # Candle property
            columns:
                ["Candle", "HistMean", "Diff", "HistStd", "Signal"]
    """
    # Fill w/ index values, use to build multi-index df
    idx_values=[]
    # Candle properties for "Prop" index
    cndl_prop=["Close", "Volume", "BuyVol", "BuyRatio", "Trades"]
    # Fill each sublist w/ column data
    data=[[],[],[],[],[]]

    for item in get_db().pair_signals.find():
        for i in range(0,5):
            idx_values.append(
                (item["pair"], item["freq"], item["period"], cndl_prop[i])
            )
            for j in range(0,5):
                data[i].append(item["data"][j][i])

    col_names=["Candle", "HistMean", "Diff", "HistStd", "Signal"]

    dfp = pd.DataFrame(
        data = { col_names[n]:data[n] for n in range(0,5) },
        index = pd.MultiIndex.from_tuples(idx_values),
        columns = col_names
    ).sort_index()

    dfp.Signal = dfp.Signal.round(2)

    log.debug("loaded df with %s indices from db.pair_signals", len(dfp))
    return dfp

#-----------------------------------------------------------------------------
def save_db_aggregate(dfa):
    timer = Timer()
    db = get_db()
    ops=[]

    # Save signal sum data
    for key in list(dfa.to_dict()["signal"].keys()):
        sigval = float(dfa.loc[key]["signal"])
        update = {"$set":{
            "pair":key[0],
            "freq":key[1],
            "period":key[2],
            "signal":sigval
        }}

        # Do nothing if positive signal already has datetime tracking
        # Delete datetime tracking for negativ3e signal (if exists)
        if sigval > 0:
            doc = db.aggr_signals.find_one(
                {"pair":key[0],"freq":key[1],"period":key[2]})
            if doc is None or not doc.get("since"):
                update["$set"]["since"] = now()
        else:
            update["$set"]["since"] = False

        ops.append(UpdateOne(
            {"pair":key[0], "freq":key[1], "period":key[2]},
            update,
            upsert=True))

    res = db.aggr_signals.bulk_write(ops)
    log.debug("%s aggr. signals saved to db in %sms", res.modified_count, timer)

#-----------------------------------------------------------------------------
def load_db_aggregate():
    """Load aggregate signal data from DB as multi-index dataframe.
    Returns:
        pair signals dataframe
            multi-index levels:
                0:"Pair",
                1:"Freq",
                2:"Period",
            columns:
                ["signal", "since"]
    """
    df = pd.DataFrame(list(get_db().aggr_signals.find()))
    df.index = list(zip(df.pair, df.freq, df.period))
    df.since = df.since.replace(0,np.nan)

    dfa = pd.DataFrame(
        df[["signal", "since"]],
        index = pd.MultiIndex.from_tuples(df.index),
        columns = ["signal", "since"],
    ).sort_index(level=[0, 1, 2]
    ).sort_index(level=[1], ascending=False, sort_remaining=False)

    log.debug("loaded df with %s indices from db.aggr_signals", len(dfa))
    return dfa
