import os
import json
import requests
from requests.auth import HTTPBasicAuth

# -------------------------
# Jira credentials
# -------------------------
JIRA_INSTANCE_URL = os.environ.get("JIRA_INSTANCE_URL")
JIRA_EMAIL = os.environ.get("JIRA_EMAIL")
JIRA_API_TOKEN = os.environ.get("JIRA_API_TOKEN")

# -------------------------
# Lambda handler
# -------------------------
def lambda_handler(event, context):
    """
    Example event:
    {
        "action": "fetch_projects",   # "fetch_users", "fetch_issues", "create_issue"
        "project_key": "PROJ",        # required for "fetch_issues" and "create_issue"
        "issue_summary": "New bug",   # required for "create_issue"
        "issue_description": "Details about the bug"  # optional for "create_issue"
    }
    """
    auth = HTTPBasicAuth(JIRA_EMAIL, JIRA_API_TOKEN)
    headers = {"Accept": "application/json", "Content-Type": "application/json"}

    try:
        body = json.loads(event.get("body", "{}"))
        action = body.get("action")
        if not action:
            return {"statusCode": 400, "body": json.dumps({"error": "Missing field: action", "intent": 2})}

        result = {}

        # -------------------------
        # Fetch all projects
        # -------------------------
        if action == "fetch_projects":
            url = f"{JIRA_INSTANCE_URL}/rest/api/3/project/search"
            response = requests.get(url, headers=headers, auth=auth)
            response.raise_for_status()
            result = response.json()

        # -------------------------
        # Fetch all users
        # -------------------------
        elif action == "fetch_users":
            url = f"{JIRA_INSTANCE_URL}/rest/api/3/users/search"
            response = requests.get(url, headers=headers, auth=auth, params={"maxResults": 1000})
            response.raise_for_status()
            result = response.json()

        # -------------------------
        # Fetch issues from a project
        # -------------------------
        elif action == "fetch_issues":
            project_key = body.get("project_key")
            if not project_key:
                return {"statusCode": 400, "body": json.dumps({"error": "Missing field: project_key", "intent": 2})}
            url = f"{JIRA_INSTANCE_URL}/rest/api/3/search"
            jql = f"project={project_key}"
            response = requests.get(url, headers=headers, auth=auth, params={"jql": jql, "maxResults": 100})
            response.raise_for_status()
            result = response.json()

        # -------------------------
        # Create a new Jira issue
        # -------------------------
        elif action == "create_issue":
            project_key = body.get("project_key")
            summary = body.get("issue_summary")
            description = body.get("issue_description", "")
            issuetype_name = body.get("issue_type", "Bug")  # default to Bug

            if not project_key or not summary:
                return {
                    "statusCode": 400,
                    "body": json.dumps({
                        "error": "Missing fields for create_issue: project_key or issue_summary",
                        "intent": 2
                    })
                }

            url = f"{JIRA_INSTANCE_URL}/rest/api/3/issue"
            payload = {
                "fields": {
                    "project": {"key": project_key},
                    "summary": summary,
                    "description": description,
                    "issuetype": {"name": issuetype_name}
                }
            }

            # Use json=payload for correct JSON formatting
            response = requests.post(url, headers=headers, auth=auth, json=payload)
            response.raise_for_status()
            result = response.json()


        else:
            return {"statusCode": 400, "body": json.dumps({"error": f"Unknown action: {action}", "intent": 2})}

        # Add intent = 2 in the response
        return {"statusCode": 200, "body": json.dumps({"action": action, "result": result, "intent": 2})}

    except requests.exceptions.RequestException as e:
        return {"statusCode": 500, "body": json.dumps({"error": str(e), "intent": 2})}
