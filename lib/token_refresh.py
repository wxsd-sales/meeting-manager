import json
import logging
import traceback

import tornado.gen
import tornado.web

from tornado.httpclient import AsyncHTTPClient, HTTPRequest, HTTPError

from lib.settings import Settings

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

class TokenRefresher(object):
    def __init__(self):
        self._refresh_token = Settings.refresh_token

    def build_access_token_payload(self):
        payload = "grant_type=refresh_token&"
        payload += "client_id={0}&".format(Settings.client_id)
        payload += "client_secret={0}&".format(Settings.client_secret)
        payload += "refresh_token={0}".format(self._refresh_token)
        return payload

    @tornado.gen.coroutine
    def refresh_token(self, state=""):
        logger.info('TokenRefresher.refresh_token called')
        url = "https://webexapis.com/v1/access_token"
        headers = {
            'cache-control': "no-cache",
            'content-type': "application/x-www-form-urlencoded"
            }
        ret_val = None
        payload = self.build_access_token_payload()
        logger.info("refresh token payload:{0}".format(payload))
        try:
            request = HTTPRequest(url, method="POST", headers=headers, body=payload, request_timeout=30)
            http_client = AsyncHTTPClient()
            response = yield http_client.fetch(request)
            resp = json.loads(response.body.decode("utf-8"))
            logger.info("TokenRefresher.refresh_token /access_token Response: {0}".format(resp))
            ret_val = resp["access_token"]
        except HTTPError as he:
            logger.info("TokenRefresher.refresh_token HTTPError:{0}".format(he))
            logger.debug(dir(he))
            logger.info(he.code)
            logger.info(he.response.body)
            traceback.print_exc()
        except Exception as e:
            logger.info("TokenRefresher.refresh_token Exception:{0}".format(e))
            traceback.print_exc()
        raise tornado.gen.Return(ret_val)