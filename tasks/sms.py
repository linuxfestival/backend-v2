import aiohttp
from django.conf import settings

API_KEY = settings.SMS_KEY
LINE_NUMBER = settings.SMS_LINE_NUMBER

OTP_VALIDITY_PERIOD = 120
OTP_RESEND_DELAY = 60

async def send_sms(mobiles, message_text):
    payload = {
        "lineNumber": LINE_NUMBER,
        "messageText": message_text,
        "mobiles": mobiles,
        "sendDateTime": None
    }

    headers = {
        'X-API-KEY': API_KEY,
        'Content-Type': 'application/json'
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.sms.ir/v1/send/bulk", json=payload, headers=headers
            ) as response:
                if response.status == 200:
                    response_text = await response.text()
                    print(f"SMS successfully sent to {mobiles}: {response_text}")
                else:
                    response_text = await response.text()
                    print(f"Services failed to send SMS: {response_text}")

    except Exception as e:
        print(f"Server failed to send SMS: {e}")