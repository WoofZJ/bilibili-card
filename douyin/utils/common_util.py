import os
# from loguru import logger
from dotenv import load_dotenv

dy_auth = None
dy_live_auth = None
def load_env():
    global dy_auth, dy_live_auth
    load_dotenv()
    cookies_dy = os.getenv('DY_COOKIES')
    cookies_live = os.getenv('DY_LIVE_COOKIES')
    from builder.auth import DouyinAuth
    dy_auth = DouyinAuth()
    dy_auth.perepare_auth(cookies_dy, "", "")
    dy_live_auth = DouyinAuth()
    dy_live_auth.perepare_auth(cookies_live, "", "")
    return dy_auth

def init():
    cookies = load_env()
    return cookies
