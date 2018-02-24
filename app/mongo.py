import logging, os, pymongo
from config import DB
import db_auth
from app.timer import Timer
log = logging.getLogger('mongodb')

#-------------------------------------------------------------------------------
def create_client(host=None, port=None, connect=True, auth=True):
    tmr = Timer()
    log.debug("connecting to \"%s:%s\"...", host, port)

    client = pymongo.MongoClient(
        host = host,
        port = port,
        tz_aware = True,
        connect = connect)

    if auth:
        authenticate(client)

    log.debug("connection established (%sms)", tmr)
    return client

#-------------------------------------------------------------------------------
def authenticate(client, user=None, pw=None):
    try:
        client.admin.authenticate(
            user or db_auth.user,
            pw or db_auth.password,
            mechanism='SCRAM-SHA-1')
    except Exception as e:
        log.exception("mongodb authentication error. host=%s, port=%s",
            client.HOST, client.PORT)
        raise

#-------------------------------------------------------------------------------
def dump(path):
    import os
    os.system("mongodump -o %s" % path)

#-------------------------------------------------------------------------------
def restore(path):
    import os
    os.system("mongorestore -d simbot %s" % path)

