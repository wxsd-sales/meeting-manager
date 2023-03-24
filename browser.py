import asyncio
import logging
import sys
#import time
import traceback
from playwright.async_api import async_playwright


logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logging.basicConfig()

url = sys.argv[1]
logger.info('loading url: {0}'.format(url))
playwright = async_playwright().start()
logger.info("browser.py starting...")

async def close_handler(event):
    logger.error(event)

async def log_handler(msg):
    logger.info(msg)
    #for arg in msg.args:
    #    val = await arg.json_value()
    #    logger.info(val)

async def run(playwright):
    while True:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        #self.browsers.update({ meeting["name"]: {
        #                        "browser":browser, 
        #                        "meeting_id":meeting["meeting_id"]
        #                     } })
        page.on("crash", close_handler)
        page.on("close", close_handler)
        page.on('console', log_handler)

        page.set_default_timeout(0)
        await page.goto(url)
        #print(page.title())
        
        logger.info("Browser Loaded Main Page")
        counter = 0
        while browser.is_connected() and not page.is_closed():
            await asyncio.sleep(5)
            counter += 1
            if counter >= 10:
                logger.debug("Browser is connected")
                counter = 0
        try:
            await browser.close()
        except Exception as e:
            traceback.print_exc()

async def main():
    async with async_playwright() as playwright:
        await run(playwright)
asyncio.run(main())

