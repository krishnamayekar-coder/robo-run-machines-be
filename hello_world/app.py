import json
from json import JSONEncoder
import datetime
import pymysql
import requests
from collections import deque




def lambda_handler(event, context):
    return {
        "statusCode": 200,
        "body": json.dumps({
            "message":"Robo run machine",
        }),
    }
