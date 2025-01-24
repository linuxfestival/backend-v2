import requests
import json

from backend.settings import PAYPING_AUTH

PAYPING_STATUS_OK = 200
PAYPING_STATUS_201 = 201
PAYPING_STATUS_202 = 202
PAYPING_STATUS_CLIENT_ERROR = 400
PAYPING_STATUS_SERVER_ERROR = 500
PAYPING_STATUS_503 = 503
PAYPING_STATUS_AUTH_ERROR = 401
PAYPING_STATUS_403 = 403
PAYPING_STATUS_404 = 404
PAYPING_STATUS_500 = 500

PayPing_PAYMENT_DESCRIPTION = 'register workshops or talks'
PayPing_CALL_BACK = 'https://autgamecraft.ir/api/v2/service/verify/'

PayPing_URL = "https://api.payping.ir/v2/pay"
PayPing_URL_VERIFY = "https://api.payping.ir/v2/pay/verify"


def generatePayPingLink(code):
    return f'https://api.payping.ir/v2/pay/gotoipg/{code}'


class PayPingRequest:
    def __init__(self):
        self.__headers = {
            'Content-Type': 'application/json',
            "Authorization": "Bearer " + PAYPING_AUTH
        }

    def create_payment(self, order_id, amount, name, phone, email):
        payerIdentity = phone or email
        body = {
            "payerName": name,
            "amount": amount,
            "payerIdentity": payerIdentity,
            "returnURL": PayPing_CALL_BACK,
            "description": PayPing_PAYMENT_DESCRIPTION,
            "clientRefId": order_id,
        }

        response = requests.request(method='POST', headers=self.__headers, url=PayPing_URL, data=json.dumps(body))
        json_response = json.loads(response.text)
        if 'status' not in json_response:
            json_response['status'] = response.status_code
        return json_response

    def verify_payment(self, refId, amount):
        body = {"refId": refId, "amount": amount}
        response = requests.request(method='POST', headers=self.__headers, url=PayPing_URL_VERIFY, data=json.dumps(body))

        json_response = json.loads(response.text)
        if 'status' not in json_response:
            json_response['status'] = response.status_code
        return json_response
