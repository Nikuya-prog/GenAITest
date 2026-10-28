import os
from dotenv import load_dotenv
from simple_salesforce import Salesforce

load_dotenv()

sf = Salesforce(
    consumer_key=os.getenv("SF_CONSUMER_KEY"),
    consumer_secret=os.getenv("SF_CONSUMER_SECRET"),
    domain=os.getenv("SF_DOMAIN"),
)

print("Connected!\n")

opps = sf.query(
    "SELECT Name, StageName, Amount, CloseDate, Last_Contact_Date_c IsClosed "
    "FROM Opportunity"

)
print(f"Opportunities ({opps['totalSize']}):")
for o in opps["records"]:
    print(
        f"Name: {o['Name']}, Stage: {o['StageName']}, Amount: {o['Amount']}, "
        f"Close Date: {o['CloseDate']}, Last Contact Date: {o['Last_Contact_Date_c']}, "
        f"Is Closed: {o['IsClosed']}"
    )

    leads = sf.query
        "SELECT Name, Company, Status, Lead_Received_Date__c FROM Lead"
    )
    