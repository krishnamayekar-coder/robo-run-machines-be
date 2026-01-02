# composio_user/app.py

import json
import os
import requests
from urllib.parse import urljoin, urlparse

# Fix cache BEFORE import
os.environ["COMPOSIO_CACHE_DIR"] = "/tmp/.composio"

from composio import Composio, App

COMPOSIO_API_KEY = os.environ["COMPOSIO_API_KEY"]
client = Composio(api_key=COMPOSIO_API_KEY)

# Working base for raw calls
WORKING_BASE = "https://backend.composio.dev"

# 🔧 FIXED MONKEY PATCH: Use **kwargs only (no positional args) to avoid signature clashes
original_request = requests.request

def patched_request(*args, **kwargs):
    # Extract URL from kwargs (SDK always passes it as kwarg)
    url = kwargs.get('url')
    if url and 'api.composio.dev' in url:
        # Rewrite to working host, preserving path/query
        parsed = urlparse(url)
        new_url = f"{WORKING_BASE}{parsed.path}"
        if parsed.query:
            new_url += f"?{parsed.query}"
        kwargs['url'] = new_url
    # Call original with original args/kwargs
    return original_request(*args, **kwargs)

# Apply safely
requests.request = patched_request
if hasattr(requests.Session, 'request'):
    original_session_request = requests.Session.request
    requests.Session.request = lambda self, *args, **kwargs: patched_request(*args, **kwargs)

# Helper: Raw HTTP to get connected accounts (bypasses SDK auth bug)
def get_connected_accounts(entity_id, app_name):
    """Fetch connected accounts via raw API (uses working backend host)"""
    headers = {
        "Authorization": f"Bearer {COMPOSIO_API_KEY}",
        "Content-Type": "application/json"
    }
    url = f"{WORKING_BASE}/api/v3/connected_accounts"
    params = {"entity_id": entity_id, "app_name": app_name}
    try:
        res = requests.get(url, headers=headers, params=params)
        res.raise_for_status()
        accounts = res.json().get('data', [])
        return accounts[0] if accounts else None  # Return first (or None)
    except Exception as e:
        raise Exception(f"Failed to fetch connections: {str(e)}")

def execute_action_raw(connected_account_id, action, params):
    """Execute action via raw API (avoids SDK execute bug)"""
    headers = {
        "Authorization": f"Bearer {COMPOSIO_API_KEY}",
        "Content-Type": "application/json"
    }
    url = f"{WORKING_BASE}/api/v3/actions/{action.replace('.', '/')}"  # e.g., github.list_pull_requests
    body = {"connected_account_id": connected_account_id, **params}
    res = requests.post(url, headers=headers, json=body)
    res.raise_for_status()
    return res.json().get('data', {})


def lambda_handler(event, context):
    try:
        body = json.loads(event.get("body", "{}")) if event.get("body") else {}

        # Entity ID logic
        claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
        entity_id = (
            body.get("entity_id")
            or claims.get("sub") if body.get("use_cognito_sub_as_entity") else None
            or "default"
        )

        entity = client.get_entity(id=entity_id)

        # Profile (basic)
        profile = {
            "entity_id": entity_id,
            "note": "Profile via entity (patch + raw fallback applied)"
        }

        # GitHub PRs (with fallback)
        prs = {"error": "GitHub not connected"}
        try:
            gh_account = get_connected_accounts(entity_id, "github")
            if gh_account:
                prs_data = execute_action_raw(
                    gh_account['id'],
                    "github.list_pull_requests",
                    body.get("github_filters", {"state": "open", "per_page": 30})
                )
                prs = prs_data if isinstance(prs_data, list) else prs_data.get('pull_requests', [])
                profile["github_username"] = gh_account.get('metadata', {}).get('username')
        except Exception as e:
            prs["details"] = str(e)

        # Jira Issues (same fallback)
        issues = {"error": "Jira not connected"}
        try:
            jira_account = get_connected_accounts(entity_id, "jira")
            if jira_account:
                issues_data = execute_action_raw(
                    jira_account['id'],
                    "jira.search_issues",
                    {
                        "jql": body.get("jira_jql", "assignee = currentUser() AND resolution = Unresolved"),
                        "maxResults": 30
                    }
                )
                issues = issues_data if isinstance(issues_data, list) else issues_data.get('issues', [])
        except Exception as e:
            issues["details"] = str(e)

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "message": "Composio data fetched (fixed patch + raw fallback!)",
                "entity_id": entity_id,
                "profile": profile,
                "github_prs": prs,
                "jira_issues": issues
            }, indent=2, default=str)
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "error": "Failed to fetch Composio data",
                "details": str(e),
                "debug": "Check connections at app.composio.dev; raw API used for auth bypass"
            }, indent=2)
        }