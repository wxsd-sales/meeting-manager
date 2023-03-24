import cachetools
import logging
import traceback
import wxcadm

import tornado.gen

from concurrent.futures import ThreadPoolExecutor
from lib.token_refresh import TokenRefresher

from tornado.options import options

logger = logging.getLogger(__name__)

class Calls(object):
    #This is basically a dict, where items will be expired after ttl seconds
    approved = cachetools.TTLCache(maxsize=512, ttl=10 * 60)

class MyQueue(object):
    """
    MyQueue handles events from XSI (the PSTN redirects from the WebexConnect Flow 
    are sent to a phone number associated with the WebexCalling Call Queue).
    """
    def __init__(self, channel_name='Advanced Call', webex=None):
        self.channel_name = channel_name
        self.webex = webex

    def put(self, message_dict):
        #This is the function wxcadm will call in wxcadm/wxcadm.py in a function called channel_daemon of the XSIEventsChannel class.
        #Currently you can see the .put function called around line 2535 (as of May 9, 2022).
        #Basically, wxcadm expects a Queue object, so we've made our own Queue.

        logger.debug("MyQueue message:")
        logger.debug(message_dict)
        logger.debug("Approved Calls:{}".format(Calls.approved))
        event = message_dict.get('xsi:Event', {})
        event_type = event.get('xsi:eventData',{}).get('@xsi1:type')
        if event_type == "xsi:CallHeldEvent":
            target_id = event.get('xsi:targetId')
            logger.debug('target_id object:{0}'.format(target_id))
            call = event.get('xsi:eventData',{}).get('xsi:call',{})
            logger.debug('call object:{0}'.format(call))
            remote_number = call.get('xsi:remoteParty',{}).get('xsi:address',{}).get('#text', '').replace('tel:','').replace('+','')
            logger.info('remote_number:{0}'.format(remote_number))
            if remote_number in Calls.approved:
                #TODO: Not here, but consider having the browser confirm after the user joins the meeting (and after unmuted if "host")
                #      Then, pop the entry from Call.approved? The ttl will expire it eventually anyway, so maybe that's just extra work.
                sip_destination = Calls.approved[remote_number]["sip"]
                logger.info('sip_destination:{0}'.format(sip_destination))
                xsi = wxcadm.XSICallQueue(target_id, org=self.webex.org)
                attached_call = xsi.attach_call(call.get('xsi:callId'))
                attached_call.transfer(address=sip_destination, type='blind')

class XSIConnector(object):
    #There is a huge problem with the People API if you ask for the callingData=true in the request, and it takes 10x as long. 
    #fast_mode=True shuts that param off so you get the People results back a lot quicker, especially in large orgs.
    def __init__(self, access_token):
        self.webex = wxcadm.Webex(access_token, get_xsi=True, get_locations=False, fast_mode=True)
        self.events = wxcadm.XSIEvents(self.webex.org)
        self.subscriptions = {}

    def subscribe(self, channel_name):
        red = MyQueue(channel_name, self.webex)
        xsi_event_channel = self.events.open_channel(red)
        result = xsi_event_channel.subscribe(channel_name)
        if result:
            self.subscriptions.update({channel_name:{"id":result.id, "channel":xsi_event_channel}})
            return True
        else:
            return False

    def unsubscribe(self, channel_name):
        id = self.subscriptions[channel_name]['id']
        result = self.subscriptions[channel_name]['channel'].unsubscribe(id)
        return result

    def unsubscribe_all(self):
        previously_subscribed_channels = []
        for channel_name in dict(self.subscriptions):
            self.unsubscribe(channel_name)
            previously_subscribed_channels.append(channel_name)
        return previously_subscribed_channels

class XSIManager(object):
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=10)
        self.token_refresher = TokenRefresher()
        self.access_token = None
        self.is_running = False
        self.connector = None

    @tornado.gen.coroutine
    def new_connector(self):
        try:
            self.access_token = yield self.token_refresher.refresh_token()
            channel_names = ['Advanced Call']
            if self.connector != None:
                channel_names = self.connector.unsubscribe_all()
            self.connector = XSIConnector(self.access_token)
            if not options.debug:
                for channel_name in channel_names:
                    self.connector.subscribe(channel_name)
            else:
                logger.warning("Server started in debug mode, not subscribing to channels.")
        except Exception as e:
            traceback.print_exc()

    """
    @tornado.gen.coroutine
    def refresh_loop(self):
        while True:
            self.is_running = True
            logger.info("XSIManager.refresh_loop - running")
            try:
                yield self.new_connector()
                next_refresh_seconds = get_next_refresh()
            except Exception as e:
                traceback.print_exc()
            logger.info("XSIManager.refresh_loop - done. Sleeping for {0} seconds.".format(next_refresh_seconds))
            self.is_running = False
            yield tornado.gen.sleep(next_refresh_seconds)
    """