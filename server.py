
import os
import json
import logging
import subprocess
import traceback
import urllib.parse

import tornado.gen
import tornado.httpserver
import tornado.ioloop
import tornado.web

from datetime import datetime, timedelta
from tornado.options import define, options, parse_command_line
#from tornado.httpclient import HTTPError

from lib.settings import Settings
from lib.spark import Spark
from lib.mongo_controller import MongoController
from lib.xsi_manager import Calls, XSIManager

define("debug", default=False, help="run in debug mode")
define("nobrowser", default=False, help="don't spin up any browser subprocesses")
define("verbose", default=False, help="set log level to debug (default is info)")
#wxcadm.console_logging('info')

"""
def get_next_refresh():
    now = datetime.utcnow()
    logger.info("get_next_refresh - utc now:{0}".format(now))
    next_refresh = now + timedelta(days=1)
    next_refresh = next_refresh.replace(hour=7, minute=0, second=0, microsecond=0)
    logger.info("get_next_refresh - next_refresh:{0}".format(next_refresh))
    return (next_refresh - now).seconds
"""


class MeetingManager(object):
    def __init__(self, db, xsi_manager):
        self.db = db
        self.xsi_manager = xsi_manager
        self.meetings = {}
        self.procs = {}

    def start_browser_proc(self, meeting):
        url = "http://localhost:10031?meeting_id={0}&access_token={1}".format(meeting['meeting_id'], self.xsi_manager.access_token)
        p = subprocess.Popen([Settings.python_proc,'browser.py',url], stdout=subprocess.PIPE)
        self.procs.update({meeting["name"]: {
                            "proc":p,
                            "meeting_id":meeting["meeting_id"]
                          } })
    
    @tornado.gen.coroutine
    def refresh_loop(self):
        next_check_seconds = 15 #how often we check the browser is running, and whether the meeting has ended and needs to be started again
        reset_hour = 0

        meeting_cache = []
        meeting_cache_freq = 60 #how often we pull from Mongo in seconds
        last_meeting_cache = None
        
        last_daily_reset = None
        while True:
            logger.info("MeetingManager.refresh_loop - running")
            try:
                #get current scheduled meetings?
                now = datetime.utcnow()
                if last_daily_reset == None or (last_daily_reset < (now - timedelta(minutes=75)) and now.hour == reset_hour):
                    #if last_daily_reset == None or (last_daily_reset < (now - timedelta(minutes=1)) and now.minute == 32):
                    """
                    last_daily_reset is None only the first time this loop spins up
                    Otherwise, this condition is true iff:
                    last_daily_reset occurred more than 75 minutes ago, and the current hour is the hour we're supposed to reset (reset_hour.)
                    """
                    for meeting_name in self.procs:
                        logger.info('Killing Proc for Reset:')
                        logger.info(self.procs[meeting_name])
                        self.procs[meeting_name]["proc"].terminate()
                    logger.info("MeetingManager.refresh_loop - Refreshing XSI Connector.")
                    yield self.xsi_manager.new_connector()
                    last_daily_reset = now
                    logger.debug('Daily Reset Portion Complete.')
                if last_meeting_cache == None or last_meeting_cache < (now - timedelta(seconds=meeting_cache_freq)):
                    logger.info('Retrieving meeting config from Mongo.')
                    meeting_cache = list(self.db.meetings.find({"dev":Settings.dev}))
                    last_meeting_cache = now
                for meeting in meeting_cache:
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
                        meeting_changes = {"end": end_date, 
                                           "meeting_id":resp.body.get('id'), 
                                           "sip":resp.body.get('sipAddress')}
                        meeting.update(meeting_changes)
                        logger.info('MeetingManager.refresh_loop - Updating Meeting:')
                        logger.info(meeting)
                        #we're only updating meeting_changes, instead of the whole meeting
                        #This way, if we want to change a value in the DB like name or phone number,
                        #we don't risk overwriting because of the meething_cache
                        self.db.meetings.update_one({"_id":meeting["_id"]}, {"$set": meeting_changes})
                    logger.debug(self.procs)
                    if not options.nobrowser:
                        if meeting["name"] not in self.procs:
                            self.start_browser_proc(meeting)
                        elif meeting["name"] in self.procs:
                            if self.procs[meeting["name"]]["proc"].poll() != None or meeting["meeting_id"] != self.procs[meeting["name"]]["meeting_id"]:
                                try:
                                    self.procs[meeting["name"]]["proc"].terminate()
                                except Exception as e:
                                    traceback.print_exc()
                                logger.info("Process for {0} has terminated, restarting.".format(meeting["name"]))
                                self.start_browser_proc(meeting)

            except Exception as e:
                traceback.print_exc()
            logger.info("MeetingManager.refresh_loop - done. Sleeping for {0} seconds.".format(next_check_seconds))
            yield tornado.gen.sleep(next_check_seconds)


class BrowserHandler(tornado.web.RequestHandler):
    @tornado.web.asynchronous
    @tornado.gen.coroutine
    def get(self):
        logger.debug("GET BrowserHandler")
        self.render("meeting.html")

    @tornado.web.asynchronous
    @tornado.gen.coroutine
    def post(self):
        logger.info("POST BrowserHandler request.body:{0}".format(self.request.body))
        jbody = json.loads(self.request.body)
        logger.debug("jbody:{}".format(jbody))
        user = jbody.get('user')
        resp = {'join_as':'none'}
        if user and user in Calls.approved:
            resp = {'join_as':Calls.approved[user]['join_as']}
        self.set_header('Content-Type', 'application/json')
        self.set_status(200)
        self.write(json.dumps(resp))

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
        Expecting SIP calls to be of the format:
        meeting.NUMBER.PIN@cb193.dc-01.com
        Where NUMBER is the phone_number of the meeting in the Mongo DB, and PIN is either the host or guest pin.

        the first part of the string "meeting." is simply used as a filter
        to avoid making a find_one() request to Mongo for every spam call that comes in.
        """
        res_val = ""
        status_code = 200
        #logger.debug("ProxyHandler request.body:{0}".format(self.request.body))
        try:
            str_body = self.request.body.decode('utf-8')
            query = urllib.parse.parse_qs(str_body)
            #logger.debug(query)
            dest = query['DESTINATION_ALIAS'][0]
            if dest.startswith('meeting.') and status_code == 200:
                meeting_keyword, phone_number, remainder = dest.split('.',2)
                pin, remainder = remainder.split('@',1)
                meeting = self.application.settings['db'].meetings.find_one({"phone_number":phone_number, "dev":Settings.dev})
                caller = query['AUTHENTICATED_SOURCE_ALIAS'][0]
                approved_call = None
                if pin == meeting["host_pin"]:
                    approved_call = {caller : {"sip": meeting["sip"], "join_as":"host"}}
                elif pin == meeting["guest_pin"]:
                    approved_call = {caller : {"sip": meeting["sip"], "join_as":"guest"}}
                else:
                    status_code = 502 #This is returned to expressway, next server on the list will be tried.  We use this as a workaround for Prod/Dev
                    #i.e. if host/guest pins don't match prod, try dev server.
                if approved_call:
                    Calls.approved.update(approved_call)
                    logger.info("approved_call:{}".format(approved_call))
            
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
        self.set_status(status_code)
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
            meeting = self.application.settings['db'].meetings.find_one({"phone_number":dialed_number, "dev":Settings.dev})
            if meeting:
                approved_call = None
                if jbody["pin"] == meeting["host_pin"]:
                    approved_call = {caller_number : {"sip": meeting["sip"], "join_as":"host"}}
                elif jbody["pin"] == meeting["guest_pin"]:
                    approved_call = {caller_number : {"sip": meeting["sip"], "join_as":"guest"}}
                if approved_call:
                    Calls.approved.update(approved_call)
                    logger.info("approved_call:{}".format(approved_call))
                    if options.debug:
                        logger.warning('Running in Debug Mode. Call will NOT be received by XSI!')
        self.set_header('Content-Type', 'application/text')
        self.set_status(200)
        self.write('true')


@tornado.gen.coroutine
def main():
    try:        
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
        xsi_manager = XSIManager(options.verbose)
        app.settings['xsi_manager'] = xsi_manager
        meeting_manager = MeetingManager(db, xsi_manager)
        app.settings['meeting_manager'] = meeting_manager
        
        server = tornado.httpserver.HTTPServer(app)
        server.bind(Settings.port)
        logger.info("main - Serving... on port {0}".format(Settings.port))
        server.start()
        tornado.ioloop.IOLoop.instance().spawn_callback(meeting_manager.refresh_loop)
        tornado.ioloop.IOLoop.instance().start()
    except Exception as e:
        traceback.print_exc()

if __name__ == "__main__":
    parse_command_line()
    logger = logging.getLogger(__name__)
    if options.verbose:
        logger.setLevel(logging.DEBUG)
        logging.getLogger('xsi_manager').setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)
        logging.getLogger('xsi_manager').setLevel(logging.INFO)
    logging.getLogger('wxcadm').setLevel(logging.INFO)
    main()
    