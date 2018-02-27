# app.candles
import logging, time
import pandas as pd
from pymongo import ReplaceOne
from binance.client import Client
from app import get_db
from app.timer import Timer
from app.utils import utc_datetime, to_float, to_dt, intrvl_to_ms, date_to_ms
log = logging.getLogger('candles')

#------------------------------------------------------------------------------
def resample(df):
    """dfsum = df[["buy_vol", "trades", "volume"]
    #    ].resample(freq).sum()
    #dfmean = df[["close","high","low","open"]
    #    ].resample(freq).mean()
    #dfres = dfsum.join(dfmean).dropna().round(5)
    dfres = df.resample(freq).mean()
    dfres = dfres.ix[:, sorted(dfres.columns)]
    log.debug("%s [%sx%s] dataframe created",
        pair, len(dfres), len(df.columns))

    return dfres
    """
    pass

#------------------------------------------------------------------------------
def db_get(pair, start, end=None):
    """Return historical average candle data from DB as dataframe.
    """
    _end = end if end else utc_datetime()

    cursor = get_db().candles_5t.find(
        {"pair":pair, "close_date":{"$gte":start, "$lt":_end}},
        {"_id":0} #"pair":0}
    ).sort("close_date",1)

    log.debug("%s candle db records found", cursor.count())

    df = pd.DataFrame(list(cursor))
    df.index = df["close_date"]
    df.index.name="date"
    return df

#------------------------------------------------------------------------------
def api_get(pair, interval, start_str, end_str=None):
    """Get Historical Klines (candles) from Binance.
    @interval: Binance kline values: [1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 8h,
    12h, 1d, 3d, 1w, 1M]
    Return: list of OHLCV value
    """
    limit = 500
    idx = 0
    results = []
    timeframe = intrvl_to_ms(interval)
    start_ts = date_to_ms(start_str)
    end_ts = date_to_ms(end_str) if end_str else None
    client = Client("", "")
    log.debug('start_ts=%s', start_ts)

    while True:
        data = client.get_klines(
            symbol=pair,
            interval=interval,
            limit=limit,
            startTime=start_ts,
            endTime=end_ts
        )
        if len(data) > 0:
            results += data
            start_ts = data[len(data) - 1][0] + timeframe
        else:
            start_ts += timeframe
        idx += 1

        # Test limits/prevent API spamming
        if len(data) < limit:
            break
        if idx % 3 == 0:
            time.sleep(1)

    log.debug("%s %s candles retrieved (binance api)",
        len(results) if len(results) > 0 else 0, pair.lower())
    return results

#------------------------------------------------------------------------------
def store(candles_df):
    tmr = Timer()
    pair = candles_df.ix[0]["pair"]
    bulk=[]

    for idx, row in candles_df.iterrows():
        record = row.to_dict()
        bulk.append(ReplaceOne(
            {"close_date":record["close_date"], "pair":pair},
            record,
            upsert=True))

    if len(bulk) < 1:
        return log.info("No candles to store in DB")

    result = (get_db().candles_5t.bulk_write(bulk)).bulk_api_result
    del result["upserted"], result["writeErrors"], result["writeConcernErrors"]

    log.debug("bulk_write completed (%sms)", tmr)
    log.debug(result)

    return result

#------------------------------------------------------------------------------
def to_df(pair, rawdata, store_db=False):
    """Convert candle data to pandas DataFrame.
    """
    columns=["open_date","open","high","low","close","volume","close_date",
        "quote_vol", "trades", "buy_vol", "sell_vol", "ignore"]

    df = pd.DataFrame(
        index = [pd.to_datetime(x[6], unit='ms', utc=True) for x in rawdata],
        data = [x for x in rawdata],
        columns = columns
    )[columns].astype(float)

    df.index.name="date"
    del df["ignore"]
    df["pair"] = pair
    df["close_date"] = pd.to_datetime(df["close_date"],unit='ms',utc=True)
    df["open_date"] = pd.to_datetime(df["open_date"],unit='ms',utc=True)
    df["buy_ratio"] = (df["buy_vol"] / df["volume"]).round(5)
    df = df[sorted(df.columns)]

    if store_db:
        store(df)

    return df
