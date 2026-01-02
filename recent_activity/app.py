import os
import json
import psycopg2
import psycopg2.extras
from datetime import datetime, date, timezone
import pytz
import re

JIRA_REGEX = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")

def normalize_email_for_login(email: str) -> str:
    """
    krishna.mayekar@aithinkers.com → krishnamayekar
    """
    local = email.split("@")[0]
    return re.sub(r"[^a-z0-9]", "", local.lower())



def extract_jira_ticket(message):
    if not message:
        return None
    match = JIRA_REGEX.search(message)
    return match.group(0) if match else None


def infer_commit_type(message):
    if not message:
        return "Other"

    msg = message.lower()
    if any(k in msg for k in ["fix", "bug", "hotfix", "patch"]):
        return "Bugfix"
    if any(k in msg for k in ["feat", "feature", "add", "implement"]):
        return "Feature"
    if any(k in msg for k in ["refactor", "cleanup", "optimize"]):
        return "Refactor"
    if any(k in msg for k in ["test", "spec", "coverage"]):
        return "Test"

    return "Other"


def commit_message_quality(message):
    if not message or len(message.strip().split()) < 4 or message[0].islower():
        return "Needs Improvement"
    return "Clear"


def is_pr_linked(commit_sha, pull_requests):
    return any(
        pr.get("raw", {}).get("head", {}).get("sha") == commit_sha
        for pr in pull_requests
    )


def build_commit_cards(commits, pull_requests):
    cards = []

    for c in commits:
        msg = c.get("message")
        cards.append({
            "commit_id": c.get("commit_sha"),
            "timestamp": c.get("timestamp"),
            "author": c.get("author_email"),
            "commit_message": msg,
            "jira_ticket_id": extract_jira_ticket(msg),
            "branch_name": c.get("raw", {}).get("ref"),
            "pr_linked": is_pr_linked(c.get("commit_sha"), pull_requests),
            "ci_status": c.get("raw", {}).get("ci_status", "unknown"),
            "cd_status": c.get("raw", {}).get("cd_status", "unknown"),
            "derived_intelligence": {
                "commit_type": infer_commit_type(msg),
                "commit_message_quality": commit_message_quality(msg)
            }
        })

    return cards


def make_aware(dt):
    if dt and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def parse_date(date_str):
    if not date_str:
        raise ValueError("from_date and to_date are required")

    # Accept YYYY-MM-DD
    if len(date_str) == 10:
        date_str = date_str + "T00:00:00"

    dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(pytz.UTC)



def get_connection():
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        dbname=os.environ["DB_NAME"],
        port=5432
    )


# ==========================================================
# FETCHERS (EMAIL OPTIONAL)
# ==========================================================
def fetch_jira_issues(cursor, from_date, to_date, email=None):
    if email:
        cursor.execute("""
            SELECT id, issue_key AS issue_id, assignee_name AS assignee,
                   reporter_name AS reporter, status, priority,
                   updated_at AS timestamp, raw
            FROM jira_issues
            WHERE updated_at BETWEEN %s AND %s
              AND assignee_email = %s
            ORDER BY updated_at DESC
        """, (from_date, to_date, email))
    else:
        cursor.execute("""
            SELECT id, issue_key AS issue_id, assignee_name AS assignee,
                   reporter_name AS reporter, status, priority,
                   updated_at AS timestamp, raw
            FROM jira_issues
            WHERE updated_at BETWEEN %s AND %s
            ORDER BY updated_at DESC
        """, (from_date, to_date))

    return [{**dict(r), "timestamp": make_aware(r["timestamp"])} for r in cursor.fetchall()]


def fetch_jira_subtasks(cursor, from_date, to_date, email=None):
    if email:
        login_key = normalize_email_for_login(email)
        cursor.execute("""
            SELECT id, subtask_id, parent_issue_id, summary,
                   status, timestamp, raw
            FROM jira_subtasks
            WHERE timestamp BETWEEN %s AND %s
              AND lower(author_login) LIKE %s
            ORDER BY timestamp DESC
        """, (from_date, to_date, f"%{login_key}%"))
    else:
        cursor.execute("""
            SELECT id, subtask_id, parent_issue_id, summary,
                   status, timestamp, raw
            FROM jira_subtasks
            WHERE timestamp BETWEEN %s AND %s
            ORDER BY timestamp DESC
        """, (from_date, to_date))

    return [
        {**dict(r), "timestamp": make_aware(r["timestamp"])}
        for r in cursor.fetchall()
    ]


def fetch_github_events(cursor, from_date, to_date, email=None):
    if email:
        cursor.execute("""
            SELECT id, github_id, repo, commit_sha,
                   author_email, message, timestamp, raw
            FROM github_events
            WHERE timestamp BETWEEN %s AND %s
              AND author_email = %s
            ORDER BY timestamp DESC
        """, (from_date, to_date, email))
    else:
        cursor.execute("""
            SELECT id, github_id, repo, commit_sha,
                   author_email, message, timestamp, raw
            FROM github_events
            WHERE timestamp BETWEEN %s AND %s
            ORDER BY timestamp DESC
        """, (from_date, to_date))

    return [{**dict(r), "timestamp": make_aware(r["timestamp"])} for r in cursor.fetchall()]

def fetch_github_issues(cursor, from_date, to_date, email=None):
    if email:
        login_key = normalize_email_for_login(email)
        cursor.execute("""
            SELECT id, github_id, repo, issue_number,
                   title, body, action, author_login,
                   timestamp, raw
            FROM issues
            WHERE timestamp BETWEEN %s AND %s
              AND lower(author_login) LIKE %s
            ORDER BY timestamp DESC
        """, (from_date, to_date, f"%{login_key}%"))
    else:
        cursor.execute("""
            SELECT id, github_id, repo, issue_number,
                   title, body, action, author_login,
                   timestamp, raw
            FROM issues
            WHERE timestamp BETWEEN %s AND %s
            ORDER BY timestamp DESC
        """, (from_date, to_date))  # ✅ FIX

    return [
        {**dict(r), "timestamp": make_aware(r["timestamp"])}
        for r in cursor.fetchall()
    ]


def fetch_pull_requests(cursor, from_date, to_date, email=None):
    if email:
        login_key = normalize_email_for_login(email)
        cursor.execute("""
            SELECT id, github_id, repo, pr_number,
                   title, action, state, author_login,
                   timestamp, raw
            FROM pull_requests
            WHERE timestamp BETWEEN %s AND %s
              AND lower(author_login) LIKE %s
            ORDER BY timestamp DESC
        """, (from_date, to_date, f"%{login_key}%"))
    else:
        cursor.execute("""
            SELECT id, github_id, repo, pr_number,
                   title, action, state, author_login,
                   timestamp, raw
            FROM pull_requests
            WHERE timestamp BETWEEN %s AND %s
            ORDER BY timestamp DESC
        """, (from_date, to_date))  # ✅ FIX

    return [
        {**dict(r), "timestamp": make_aware(r["timestamp"])}
        for r in cursor.fetchall()
    ]


# ==========================================================
# MAIN LAMBDA
# ==========================================================
def lambda_handler(event, context):
    try:
        query = event.get("queryStringParameters") or {}
        from_date = parse_date(query.get("from_date"))
        to_date = parse_date(query.get("to_date"))
        email = query.get("email")  # 👈 OPTIONAL

        conn = get_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        commits = fetch_github_events(cursor, from_date, to_date, email)
        prs = fetch_pull_requests(cursor, from_date, to_date, email)

        commit_cards = build_commit_cards(commits, prs)

        cursor.close()
        conn.close()

        return {
            "statusCode": 200,
            "body": json.dumps({
                "status": 200,
                "message": "Current work snapshot",
                "data": commit_cards
            }, indent=2, default=str)
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
