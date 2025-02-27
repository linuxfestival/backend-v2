from kavenegar import *
from django.conf import settings
from concurrent.futures import ThreadPoolExecutor


SMS_EXECUTOR = ThreadPoolExecutor(max_workers=10)
API_KEY = settings.SMS_KEY
LINE_NUMBER = settings.SMS_LINE_NUMBER
OTP_VALIDITY_PERIOD = 120 # 2 minutes
OTP_RESEND_DELAY = 60  # 1 minute

def send_sms(mobiles, message_text):
    try:
        api = KavenegarAPI(API_KEY)

        receptor = ''
        for mobile in mobiles: receptor += mobile + ', '
        receptor = receptor[:-2]

        params = {
            'sender': str(LINE_NUMBER),  # optional
            'receptor': receptor,
            'message': message_text,
        }
        response = api.sms_send(params)
        print(response)
    except APIException as e:
        print(e)
    except HTTPException as e:
        print(e)

    except Exception as e:
        print(f"Server failed to send SMS: {e}")
