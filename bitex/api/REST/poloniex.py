"""Bitstamp REST API backend.

Documentation available here:
    https://www.bitstamp.net/api/
"""
# Import Built-ins
import logging
import hashlib
import hmac
import urllib
import urllib.parse


# Import Third-Party

# Import Homebrew
from bitex.api.REST import RESTAPI

# Init Logging Facilities
log = logging.getLogger(__name__)


class PoloniexREST(RESTAPI):
    """Poloniex REST API class."""

    def __init__(self, key=None, secret=None, version=None, config=None,
                 addr=None, timeout=5):
        """Initialize the class instance."""
        addr = 'https://poloniex.com' if not addr else addr
        super(PoloniexREST, self).__init__(addr=addr, version=version,
                                           key=key, secret=secret,
                                           timeout=timeout, config=config)

    def sign_request_kwargs(self, endpoint, **kwargs):
        """Sign the request."""
        req_kwargs = super(PoloniexREST, self).sign_request_kwargs(endpoint,
                                                                   **kwargs)

        # Prepare Payload arguments
        try:
            params = kwargs['params']
        except KeyError:
            params = {}
        nonce = self.nonce()
        cmd = endpoint

        payload = params

        # generate signature
        msg = 'command=' + cmd + '&nonce=' + nonce + '&' + urllib.parse.urlencode(payload)
        sig = hmac.new(self.secret.encode('utf-8'), msg.encode('utf-8'),
                       hashlib.sha512).hexdigest()

        # update req_kwargs keys
        req_kwargs['headers'] = {'Key': self.key, 'Sign': sig}
        req_kwargs['data'] = params
        req_kwargs['url'] = self.addr + '/tradingApi'

        return req_kwargs
