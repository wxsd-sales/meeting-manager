import os
from dotenv import load_dotenv

load_dotenv()

class Settings(object):
    port = int(os.environ.get("MY_APP_PORT"))
    dev = os.environ.get("DEV_MODE") == "true"
    python_proc = os.environ.get("PYTHON_PROC_NAME")
    cookie_secret= os.environ.get("MY_COOKIE_SECRET")
    
    refresh_token = os.environ.get("WEBEX_INTEGRATION_REFRESH_TOKEN")
    client_id = os.environ.get("WEBEX_INTEGRATION_CLIENT_ID")
    client_secret = os.environ.get("WEBEX_INTEGRATION_CLIENT_SECRET")
    
    mongo_uri = os.environ.get("MY_MONGO_URI")
    mongo_db = os.environ.get("MY_MONGO_DB")
