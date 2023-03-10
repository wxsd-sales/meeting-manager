
import cachetools
import os
import json
import logging
import subprocess
import traceback
import urllib.parse
import wxcadm

import tornado.gen
import tornado.httpserver
import tornado.ioloop
import tornado.web

from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from tornado.options import define, options, parse_command_line
#from tornado.httpclient import HTTPError

from lib.settings import Settings
from lib.spark import Spark
from lib.mongo_controller import MongoController
from lib.token_refresh import TokenRefresher

define("debug", default=False, help="run in debug mode")
define("nobrowser", default=False, help="don't spin up any browser subprocesses")
#wxcadm.console_logging('info')

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logging.getLogger('wxcadm').setLevel(logging.INFO)

def get_next_refresh():
    now = datetime.utcnow()
    logger.info("get_next_refresh - utc now:{0}".format(now))
    next_refresh = now + timedelta(days=1)
    next_refresh = next_refresh.replace(hour=7, minute=0, second=0, microsecond=0)
    logger.info("get_next_refresh - next_refresh:{0}".format(next_refresh))
    return (next_refresh - now).seconds

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
            logger.debug('remote_number:{0}'.format(remote_number))
            if remote_number in Calls.approved:
                #TODO: Not here, but consider having the browser confirm after the user joins the meeting (and after unmuted if "host")
                #      Then, pop the entry from Call.approved? The ttl will expire it eventually anyway, so maybe that's just extra work.
                sip_destination = Calls.approved[remote_number]["sip"]
                logger.debug('sip_destination:{0}'.format(sip_destination))
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
            #TODO: access_token shouldn't be managed in the XSI Manager - it will need to be reset once per day when (right before) all of the meetings reboot
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



class MeetingManager(object):
    def __init__(self, db, xsi_manager):
        self.db = db
        self.xsi_manager = xsi_manager
        self.meetings = {}
        self.procs = {}

    def start_browser_proc(self, meeting):
        url = "http://localhost:10031?meeting_id={0}&access_token={1}".format(meeting['meeting_id'], self.xsi_manager.access_token)
        p = subprocess.Popen(['python','browser.py',url], stdout=subprocess.PIPE)
        self.procs.update({meeting["name"]: {
                            "proc":p,
                            "meeting_id":meeting["meeting_id"]
                          } })
    
    @tornado.gen.coroutine
    def refresh_loop(self):
        while True:
            logger.info("MeetingManager.refresh_loop - running")
            try:
                #get current scheduled meetings?
                if self.xsi_manager.is_running:
                    logger.info("MeetingManager.refresh_loop - XSI Manager loop is running.  Pausing...")
                    while self.xsi_manager.is_running:
                        yield tornado.gen.sleep(5)
                    logger.info("MeetingManager.refresh_loop - Resuming.")
                for meeting in self.db.meetings.find():
                    logger.debug(meeting)
                    now = datetime.utcnow()
                    logger.debug(now)
                    if meeting.get('end') == None or meeting['end'] < (now - timedelta(seconds=1)):
                        spark = Spark(self.xsi_manager.access_token)
                        start_date = now + timedelta(minutes=1)
                        end_date = start_date.replace(hour=23).replace(minute=59).replace(second=59)
                        data = {
                            "title": meeting["name"],
                            "start": start_date.strftime('%Y-%m-%dT%H:%M:%S-00:00'),
                            "end": end_date.strftime('%Y-%m-%dT%H:%M:%S-00:00'),
                            "audioConnectionOptions":{"allowHostToUnmuteParticipants": True,
                                                      "allowAttendeeToUnmuteSelf": False,
                                                      "muteAttendeeUponEntry":True}
                            #"recurrence":"FREQ=DAILY;"
                        }
                        resp = yield spark.post_with_retries('https://webexapis.com/v1/meetings', data)
                        meeting["end"] = end_date
                        meeting["meeting_id"] = resp.body.get('id')
                        meeting["sip"] = resp.body.get('sipAddress')
                        logger.info('MeetingManager.refresh_loop - Updating Meeting:')
                        logger.info(meeting)
                        self.db.meetings.update_one({"_id":meeting["_id"]}, {"$set": meeting})
                    logger.debug(self.procs)
                    if not options.nobrowser:
                        if meeting["name"] not in self.procs:
                            self.start_browser_proc(meeting)
                        elif meeting["name"] in self.procs and meeting["meeting_id"] != self.procs[meeting["name"]]["meeting_id"]:
                            #elif meeting["name"] in self.procs:
                            if self.procs[meeting["name"]]["proc"].poll() == None:
                                self.procs[meeting["name"]]["proc"].terminate()
                                logger.info("Process for {0} terminated.".format(meeting["name"]))
                            self.start_browser_proc(meeting)

                #TODO: change below to go to sleep until endtime of soonest meeting to end from now?
                #TODO: at 23:59, kill all browsers? generate new token? start browsers again at 00:00:00?
                #next_refresh_seconds = get_next_refresh()
            except Exception as e:
                traceback.print_exc()
            next_refresh_seconds = 15
            logger.info("MeetingManager.refresh_loop - done. Sleeping for {0} seconds.".format(next_refresh_seconds))
            yield tornado.gen.sleep(next_refresh_seconds)


class BrowserHandler(tornado.web.RequestHandler):
    @tornado.web.asynchronous
    @tornado.gen.coroutine
    def get(self):
        logger.debug("GET BrowserHandler")
        self.render("meeting.html")

class StatusHandler(tornado.web.RequestHandler):
    @tornado.web.asynchronous
    @tornado.gen.coroutine
    def get(self):
        """
        Used to confirm Proxy Service is up and running from Expressway
        """
        self.set_status(200)
        self.write('OK')

class ProxyHandler(tornado.web.RequestHandler):
    @tornado.web.asynchronous
    @tornado.gen.coroutine
    def post(self):
        """
        Excepting SIP calls to be of the format:
        meeting.NUMBER.PIN@cb193.dc-01.com
        Where NUMBER is the phone_number of the meeting in the Mongo DB, and PIN is either the host or guest pin.

        the first part of the string "meeting." is simply used as a filter
        to avoid making a find_one() request to Mongo for every spam call that comes in.
        """
        res_val = ""
        logger.info("ProxyHandler request.body:{0}".format(self.request.body))
        try:
            str_body = self.request.body.decode('utf-8')
            query = urllib.parse.parse_qs(str_body)
            #logger.debug(query)
            dest = query['DESTINATION_ALIAS'][0]
            if dest.startswith('meeting.'):
                meeting_keyword, phone_number, remainder = dest.split('.',2)
                pin, remainder = remainder.split('@',1)
                meeting = self.application.settings['db'].meetings.find_one({"phone_number":phone_number})
                caller = query['AUTHENTICATED_SOURCE_ALIAS'][0]
                approved_call = None
                if pin == meeting["host_pin"]:
                    approved_call = {caller : {"sip": meeting["sip"], "join_as":"host"}}
                elif pin == meeting["guest_pin"]:
                    approved_call = {caller : {"sip": meeting["sip"], "join_as":"guest"}}
                if approved_call:
                    Calls.approved.update(approved_call)
                    logger.debug("approved_call:{}".format(approved_call))
            
                    res_val = '<cpl xmlns="urn:ietf:params:xml:ns:cpl" xmlns:taa="http://www.tandberg.net/cpl-extensions" '
                    res_val += 'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="urn:ietf:params:xml:ns:cpl cpl.xsd">'
                    res_val += '<taa:routed>'
                    #<!--Redirect the call to alice@example.com by clearing the current list of destination aliases through (clear=yes)
                    #and adding a new alias (url=alice@example.com)-->
                    res_val += '<taa:location clear="yes" url="{}">'.format(meeting["sip"])
                    res_val += '<proxy/>'
                    res_val += '</taa:location>'
                    res_val += '</taa:routed>'
                    res_val += '</cpl>'
                    logger.debug(res_val)
            
        except Exception as e:
            #TODO: we're probably gonna want to change the print below to avoid filling logs with spam call exceptions
            traceback.print_exc()
        self.set_header('Content-Type', 'application/xml')
        self.set_status(200)
        self.write(res_val)

    
class WebexConnectHandler(tornado.web.RequestHandler):
    @tornado.web.asynchronous
    @tornado.gen.coroutine
    def post(self):
        logger.info("WebexConnectHandler request.body:{0}".format(self.request.body))
        jbody = json.loads(self.request.body).get('data')
        logger.debug("jbody:{}".format(jbody))
        if jbody:
            dialed_number = jbody["dialed_number"].replace("+","")
            caller_number = jbody["caller_number"].replace("+","")
            meeting = self.application.settings['db'].meetings.find_one({"phone_number":dialed_number})
            if meeting:
                approved_call = None
                if jbody["pin"] == meeting["host_pin"]:
                    approved_call = {caller_number : {"sip": meeting["sip"], "join_as":"host"}}
                elif jbody["pin"] == meeting["guest_pin"]:
                    approved_call = {caller_number : {"sip": meeting["sip"], "join_as":"guest"}}
                if approved_call:
                    Calls.approved.update(approved_call)
                    logger.debug("approved_call:{}".format(approved_call))
        self.set_header('Content-Type', 'application/text')
        self.set_status(200)
        self.write('true')


@tornado.gen.coroutine
def main():
    try:
        parse_command_line()
        app = tornado.web.Application([
                (r"/", BrowserHandler),
                (r"/proxy", ProxyHandler),
                (r"/status", StatusHandler),
                (r"/webexconnect", WebexConnectHandler),
              ],
            template_path=os.path.join(os.path.dirname(__file__), "html_templates"),
            static_path=os.path.join(os.path.dirname(__file__), "static"),
            cookie_secret=Settings.cookie_secret,
            xsrf_cookies=False,
            debug=options.debug,
            )
        db = MongoController()
        app.settings['db'] = db
        xsi_manager = XSIManager()
        app.settings['xsi_manager'] = xsi_manager
        meeting_manager = MeetingManager(db, xsi_manager)
        app.settings['meeting_manager'] = meeting_manager
        
        server = tornado.httpserver.HTTPServer(app)
        server.bind(Settings.port)
        logger.info("main - Serving... on port {0}".format(Settings.port))
        server.start()
        tornado.ioloop.IOLoop.instance().spawn_callback(xsi_manager.refresh_loop)
        tornado.ioloop.IOLoop.instance().spawn_callback(meeting_manager.refresh_loop)
        tornado.ioloop.IOLoop.instance().start()
    except Exception as e:
        traceback.print_exc()

if __name__ == "__main__":
    main()
    