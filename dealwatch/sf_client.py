import os
from dotenv import load_dotenv
from simple_salesforce import Salesforce

load_dotenv()

def get_sf():
    return Salesforce(
        consumer_key=os.getenv("SF_CONSUMER_KEY"),
        consumer_secret=os.getenv("SF_CONSUMER_SECRET"),
        domain=os.getenv("SF_DOMAIN"),
    )
    