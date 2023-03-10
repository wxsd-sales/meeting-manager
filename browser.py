import logging
import sys
import time
import traceback
from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logging.basicConfig()

url = sys.argv[1]
logger.info('loading url: {0}'.format(url))
playwright = sync_playwright().start()
logger.info("browser.py starting...")

def close_handler(event):
    logger.warning(event)

while True:
    browser = playwright.chromium.launch(headless=False)
    page = browser.new_page()
    #self.browsers.update({ meeting["name"]: {
    #                        "browser":browser, 
    #                        "meeting_id":meeting["meeting_id"]
    #                     } })
    page.set_default_timeout(0)
    page.goto(url)
    #print(page.title())
    logger.info("Browser Loaded Main Page")

    page.on("crash", close_handler)
    page.on("close", close_handler)

    while browser.is_connected and not page.is_closed():
        time.sleep(5)
        logger.debug("Browser is connected")
    try:
        browser.close()
    except Exception as e:
        traceback.print_exc()
