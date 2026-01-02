import json
import hmac
import hashlib
import os

# System Web Services → Outbound → REST Message


def verify_signature(event_body, headers):
    """
    Validates ServiceNow webhook using:
    X-Signature: sha256=xxxx
    """
    secret = os.environ.get("SERVICENOW_WEBHOOK_SECRET", "")
    signature = headers.get("X-Signature", "")

    if not secret or not signature:
        return True  # Allow if no secret configured

    mac = hmac.new(secret.encode(), event_body.encode(), hashlib.sha256)
    expected = f"sha256={mac.hexdigest()}"

    return hmac.compare_digest(expected, signature)


def lambda_handler(event, context):
    headers = event.get("headers", {})
    body = event.get("body", "")

    # Validate Signature
    if not verify_signature(body, headers):
        return {
            "statusCode": 401,
            "body": json.dumps({"error": "Invalid ServiceNow signature"})
        }

    # Parse payload
    payload = json.loads(body)
    event_type = payload.get("event", "unknown")
    sys_class = payload.get("sys_class_name", "unknown")
    sys_id = payload.get("sys_id", "unknown")

    print(f"Received ServiceNow event = {event_type}")
    print(f"Object Type = {sys_class}, Sys ID = {sys_id}")

    # ------------------------------------------------------------------
    # Event Routing
    # ------------------------------------------------------------------
    if sys_class == "incident":
        print(f"Incident event: {event_type}")
        print(f"Short Description: {payload.get('short_description')}")

    elif sys_class == "change_request":
        print(f"Change Request event: {event_type}")
        print(f"Number: {payload.get('number')}")

    elif sys_class == "problem":
        print(f"Problem event: {event_type}")
        print(f"Problem Number: {payload.get('number')}")

    elif sys_class == "task":
        print(f"Task event: {event_type}")
        print(f"Task Number: {payload.get('number')}")

    elif sys_class == "cmdb_ci":
        print(f"CMDB CI Updated: {event_type}")
        print(f"CI Name: {payload.get('name')}")

    else:
        print("Unhandled ServiceNow class:", sys_class)

    # ------------------------------------------------------------------
    # Save to DB (implement your INSERT logic here)
    # ------------------------------------------------------------------
    # save_event_to_db(sys_class, event_type, payload)

    return {
        "statusCode": 200,
        "body": json.dumps({"message": f"Received ServiceNow {sys_class} event: {event_type}"})
    }
