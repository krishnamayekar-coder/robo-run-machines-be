import os
import json
import psycopg2

ALLOWED_ROLES = ["DEV", "QA", "MANAGER", "DEV_MANAGER"]


def get_connection():
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        dbname=os.environ["DB_NAME"],
        port=int(os.environ.get("DB_PORT", 5432))
    )


def lambda_handler(event, context):
    try:
        # --------------------------------------------------
        # Auth / Role check (local DEV bypass)
        # --------------------------------------------------
        claims = (
            event.get("requestContext", {})
                 .get("authorizer", {})
                 .get("jwt", {})
                 .get("claims", {})
        )

    
        user_role = claims.get("custom:role")
        #user_role="DEV"

        if not user_role or user_role not in ALLOWED_ROLES:
            return {
                "statusCode": 403,
                "body": json.dumps({"error": "Access denied. Insufficient permissions."})
            }

        conn = get_connection()
        cur = conn.cursor()

        # --------------------------------------------------
        # Get ACTIVE Sprint
        # --------------------------------------------------
        cur.execute("""
            SELECT
                sprint_id,
                name,
                start_date,
                end_date
            FROM jira_sprints
            WHERE state = 'active'
            ORDER BY start_date DESC
            LIMIT 1
        """)

        sprint = cur.fetchone()

        if not sprint:
            return {
                "statusCode": 404,
                "body": json.dumps({"error": "No active sprint found"})
            }

        sprint_id, sprint_name, sprint_start, sprint_end = sprint

        # --------------------------------------------------
        # Commits during sprint (git_events)
        # --------------------------------------------------
        cur.execute("""
            SELECT
                COALESCE(author_email, 'unknown') AS developer,
                COUNT(*) AS commit_count
            FROM github_events
            WHERE timestamp BETWEEN %s AND %s
            GROUP BY author_email
            ORDER BY commit_count DESC
        """, (sprint_start, sprint_end))

        commit_rows = cur.fetchall()

        commits_by_dev = []
        total_commits = 0

        for dev, count in commit_rows:
            commits_by_dev.append({
                "developer": dev,
                "commit_count": count
            })
            total_commits += count

        # --------------------------------------------------
        # Jira issue status counts (overall)
        # --------------------------------------------------
        cur.execute("""
            SELECT
                status,
                COUNT(*) AS count
            FROM jira_issues
            WHERE updated_at BETWEEN %s AND %s
            GROUP BY status
        """, (sprint_start, sprint_end))

        status_rows = cur.fetchall()

        status_breakdown = {
            "To Do": 0,
            "In Progress": 0,
            "In Review": 0,
            "Done": 0
        }

        for status, count in status_rows:
            if status in status_breakdown:
                status_breakdown[status] = count

        total_issues = sum(status_breakdown.values())

        # --------------------------------------------------
        # Jira issues by assignee + status
        # --------------------------------------------------
        cur.execute("""
            SELECT
                assignee_name,
                status,
                COUNT(*) AS count
            FROM jira_issues
            WHERE updated_at BETWEEN %s AND %s
            GROUP BY assignee_name, status
        """, (sprint_start, sprint_end))

        assignee_rows = cur.fetchall()

        assignee_map = {}

        for assignee, status, count in assignee_rows:
            name = assignee or "Unassigned"

            if name not in assignee_map:
                assignee_map[name] = {
                    "To Do": 0,
                    "In Progress": 0,
                    "In Review": 0,
                    "Done": 0
                }

            if status in assignee_map[name]:
                assignee_map[name][status] += count

        jira_by_assignee = []

        for name, stats in assignee_map.items():
            jira_by_assignee.append({
                "name": name,
                **stats
            })

        cur.close()
        conn.close()

        # --------------------------------------------------
        # Final Response
        # --------------------------------------------------
        response = {
            "sprint": {
                "id": sprint_id,
                "name": sprint_name,
                "start_date": str(sprint_start),
                "end_date": str(sprint_end)
            },
            "commits": {
                "total": total_commits,
                "by_developer": commits_by_dev
            },
            "jira": {
                "total_issues": total_issues,
                "status_breakdown": status_breakdown,
                "by_assignee": jira_by_assignee
            }
        }

        return {
            "statusCode": 200,
            "body": json.dumps(response)
        }

    except Exception as e:
        print("Error:", str(e))
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
