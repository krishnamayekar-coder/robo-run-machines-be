import os
import requests
import json

COMPOSIO_API_KEY = os.environ.get("COMPOSIO_API_KEY1","ak_RrEItDCW4OALeSVKfe-A")
COMPOSIO_BASE_URL = os.environ.get("COMPOSIO_BASE_URL1","https://backend.composio.dev/v3/mcp")  # https://backend.composio.dev/v3/mcp

HEADERS = {
    "Authorization": f"Bearer {COMPOSIO_API_KEY}",
    "Content-Type": "application/json"
}

def fetch_user_mcp(mcp_id, user_id):
    url = f"{COMPOSIO_BASE_URL}/{mcp_id}/mcp?user_id={user_id}"
    response = requests.get(url, headers=HEADERS)
    response.raise_for_status()
    return response.json()

def lambda_handler(event, context):
    try:
        # Example: fetch MCP data for a given mcp_id and user_id
        mcp_id = "7cf19a24-4ab9-4a95-af28-3b7762ba5b5c"
        user_id = "pg-test-c6e1a797-3047-47fd-9efd-b9fcd9f75b3e"

        mcp_data = fetch_user_mcp(mcp_id, user_id)

        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": "MCP data fetched successfully",
                "mcp_data": mcp_data
            }, indent=2)
        }

    except requests.exceptions.HTTPError as http_err:
        return {
            "statusCode": http_err.response.status_code,
            "body": json.dumps({
                "error": str(http_err),
                "response": http_err.response.text
            })
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
