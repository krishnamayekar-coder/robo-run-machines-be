import os
import json
import psycopg2
from datetime import datetime, date, timezone
import pytz  # pip install pytz

ALLOWED_ROLES = ["DEV", "QA", "MANAGER", "DEV_MANAGER"]

# ==========================================================
# DB Connection
# ==========================================================
def get_connection():
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        dbname=os.environ["DB_NAME"]
    )


# ==========================================================
# JSON Encoder
# ==========================================================
class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        return super().default(obj)


# ==========================================================
# Response Helpers
# ==========================================================
def success(status, message, data=None):
    return {
        "statusCode": status,
        "body": json.dumps(
            {"status": status, "message": message, "data": data},
            cls=DateTimeEncoder
        )
    }


def error(status, message):
    return {
        "statusCode": status,
        "body": json.dumps({"status": status, "message": message})
    }


# ==========================================================
# Helper to parse query param dates
# ==========================================================
def parse_date(date_str):
    """Parse ISO date string to UTC-aware datetime"""
    dt = datetime.fromisoformat(date_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(pytz.UTC)


# ==========================================================
# Helper to make DB timestamps UTC-aware
# ==========================================================
def make_aware(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(pytz.UTC)


# ==========================================================
# Fetch Jira Issues
# ==========================================================
def fetch_jira_issues(cursor, from_date, to_date):
    cursor.execute(
        """
        SELECT id,
               issue_key,
               status,
               priority,
               component,
               assignee_name,
               reporter_name,
               assignee_email,
               reporter_email,
               updated_at
        FROM jira_issues
        WHERE updated_at >= %s::timestamptz
          AND updated_at <= %s::timestamptz
        ORDER BY updated_at DESC;
        """,
        (from_date, to_date),
    )
    return cursor.fetchall()



# ==========================================================
# Fetch GitHub PRs (including merges)
# ==========================================================
def fetch_github_prs(cursor, from_date, to_date):
    cursor.execute(
        """
        SELECT id,
               github_id,
               repo,
               pr_number,
               title,
               action,
               state,
               author_login,
               head_sha,
               merged,
               timestamp
               
        FROM pull_requests
        WHERE timestamp >= %s::timestamptz
          AND timestamp <= %s::timestamptz
        ORDER BY timestamp DESC;
        """,
        (from_date, to_date),
    )
    return cursor.fetchall()



# ==========================================================
# Fetch Sprint Progress
# ==========================================================
def fetch_sprint_progress(cursor, team, from_date, to_date):
    cursor.execute(
        """
        SELECT id, sprint_id, repo_or_board_id, name, state,
               start_date, end_date, goal, event_type,
               author_login, timestamp
        FROM jira_sprints
        WHERE timestamp >= %s
          AND timestamp <= %s
        ORDER BY timestamp DESC;
        """,
        (from_date, to_date),
    )
    return cursor.fetchall()


# ==========================================================
# Fetch Jira Subtasks
# ==========================================================
def fetch_jira_subtasks(cursor, team, from_date, to_date):
    cursor.execute(
        """
        SELECT id, subtask_id, parent_issue_id, board_id,
               summary, status, event_type, author_login,
               timestamp
        FROM jira_subtasks
        WHERE timestamp >= %s
          AND timestamp <= %s
        ORDER BY timestamp DESC;
        """,
        (from_date, to_date),
    )
    return cursor.fetchall()


# ==========================================================
# Fetch Activity Logs
# ==========================================================
def fetch_activity_logs(cursor, team, from_date, to_date):
    cursor.execute(
        """
        SELECT id,
               user_id,
               org_id,
               type,
               source_id,
               source_ref,
               payload,
               occurred_at
        FROM activity_events
        WHERE org_id = %s
          AND occurred_at >= %s
          AND occurred_at <= %s
        ORDER BY occurred_at DESC;
        """,
        (team, from_date, to_date),
    )
    return cursor.fetchall()



# ==========================================================
# Main Lambda
# ==========================================================
def lambda_handler(event, context):
    print("EVENT:", json.dumps(event))

    try:
        query = event.get("queryStringParameters") or {}

        team = query.get("team")
        from_date_str = query.get("from_date")
        to_date_str = query.get("to_date")
        report_type = query.get("type", "full")  # jira|github|sprints|subtasks|logs|full

        if not from_date_str or not to_date_str:
         return error(400, "from_date and to_date are required")


        # Parse query params as UTC-aware datetimes
        from_date = parse_date(from_date_str)
        to_date = parse_date(to_date_str)

        conn = get_connection()
        cursor = conn.cursor()

        response_data = {}

        if report_type in ["jira", "full"]:
            response_data["jira_issues"] = fetch_jira_issues(cursor, from_date, to_date)


        if report_type in ["github", "full"]:
            response_data["github_pull_requests"] = fetch_github_prs(cursor, from_date, to_date)

        if report_type in ["sprints", "full"]:
            response_data["jira_sprint_progress"] = fetch_sprint_progress(cursor, team, from_date, to_date)

        if report_type in ["subtasks", "full"]:
            response_data["jira_subtasks"] = fetch_jira_subtasks(cursor, team, from_date, to_date)

        # if report_type in ["logs", "full"]:
        #     response_data["activity_logs"] = fetch_activity_logs(cursor, team, from_date, to_date)

        cursor.close()
        conn.close()

        return success(200, "Report generated successfully", response_data)

    except Exception as e:
        print("ERROR:", str(e))
        return error(500, f"Internal error: {str(e)}")
