import os
import json
import psycopg2
from datetime import datetime, timezone


def time_ago(ts):
    if not ts:
        return None

    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts)
        except ValueError:
            return None  # 👈 prevents crashes

    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    diff = now - ts

    seconds = int(diff.total_seconds())
    minutes = seconds // 60
    hours = minutes // 60
    days = hours // 24

    if seconds < 60:
        return "just now"
    elif minutes < 60:
        return f"{minutes} min ago"
    elif hours < 24:
        return f"{hours} h ago"
    else:
        return f"{days} d ago"


ALLOWED_ROLES = ["DEV", "QA", "MANAGER", "DEV_MANAGER"]

# ==========================================================
# PostgreSQL Connection
# ==========================================================
def get_connection():
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        dbname=os.environ["DB_NAME"],
        port=5432
    )

# ==========================================================
# Lambda Handler
# ==========================================================
def lambda_handler(event, context):
    try:
        claims = (
            event.get("requestContext", {})
            .get("authorizer", {})
            .get("jwt", {})
            .get("claims", {})
        )

        user_role = claims.get("custom:role")

        if not user_role or user_role not in ALLOWED_ROLES:
            return {
                "statusCode": 403,
                "body": json.dumps({"error": "Access denied"})
            }

        conn = get_connection()
        cur = conn.cursor()

        # ================================================================
        # RECENT JIRA TICKETS (Ticket-centric)
        # ================================================================
        cur.execute("""
            SELECT
                ji.issue_key                                   AS jira_ticket_id,
                ji.raw->'fields'->>'summary'                   AS jira_title,
                ji.status                                      AS jira_status,
                ji.assignee_name                               AS assignee,
                ji.priority                                    AS priority,
                ji.story_points                                AS story_points,

                COUNT(DISTINCT pr.id)                          AS pr_linked,
                COUNT(DISTINCT gc.id)                          AS commit_count,

                GREATEST(
                    ji.updated_at,
                    MAX(pr.timestamp),
                    MAX(gc.timestamp)
                )                                              AS last_activity_time

            FROM jira_issues ji

            /* 🔗 PRs linked via Jira key in PR title */
            LEFT JOIN pull_requests pr
                ON pr.title ILIKE '%' || ji.issue_key || '%'

            /* 🔗 Commits linked via Jira key in commit message */
            LEFT JOIN git_commits gc
                ON gc.message ILIKE '%' || ji.issue_key || '%'

            GROUP BY
                ji.issue_key,
                ji.raw->'fields'->>'summary',
                ji.status,
                ji.assignee_name,
                ji.priority,
                ji.story_points,
                ji.updated_at

            ORDER BY last_activity_time DESC
            LIMIT 30;



        """)


       
        rows = cur.fetchall()
        tickets = []

        for row in rows:
            last_ts = row[8]

            tickets.append({
                "jira_ticket_id": row[0],
                "jira_title": row[1],
                "jira_status": row[2],
                "assignee": row[3],
                "priority": row[4],
                "story_points": float(row[5]) if row[5] is not None else None,
                "pr_linked": row[6],
                "commit_count": row[7],
                "last_activity_time": last_ts,
                "time_ago": time_ago(last_ts) if last_ts else None
            })



        cur.close()
        conn.close()

        return {
            "statusCode": 200,
            "body": json.dumps(
                {"jira_recent_activities": tickets},
                default=str,
                indent=2
            )
        }

    except Exception as e:
        print("Error:", str(e))
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
