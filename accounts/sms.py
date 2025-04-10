import http.client
import json

from django.conf import settings
from concurrent.futures import ThreadPoolExecutor


SMS_EXECUTOR = ThreadPoolExecutor(max_workers=2)
API_KEY = settings.SMS_KEY
LINE_NUMBER = settings.SMS_LINE_NUMBER

OTP_VALIDITY_PERIOD = 120
OTP_RESEND_DELAY = 60

def send_sms(mobiles, message_text):
    payload = json.dumps({
        "lineNumber": LINE_NUMBER,
        "messageText": message_text,
        "mobiles": mobiles,
        "sendDateTime": None
    })

    headers = {
        'X-API-KEY': API_KEY,
        'Content-Type': 'application/json'
    }

    try:
        conn = http.client.HTTPSConnection("api.sms.ir")
        conn.request("POST", "/v1/send/bulk", payload, headers)
        res = conn.getresponse()
        status, response = res.status, res.read()

        if status == 200:
            print(f"SMS successfully sent to {mobiles}: {response.decode('utf-8')}")
        else:
            print(f"Services failed to send SMS: {response.decode('utf-8')}")

    except Exception as e:
        print(f"Server failed to send SMS: {e}")