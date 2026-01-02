import os
import json
import psycopg2
from datetime import datetime, timedelta
from dateutil import parser

ALLOWED_ROLES = ["DEV", "QA", "MANAGER", "DEV_MANAGER"]

def get_connection():
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        dbname=os.environ["DB_NAME"],
    )

def lambda_handler(event, context):
    try:
        # ------------------------------------------------------------
        # Auth Validation
        # ------------------------------------------------------------
        claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
        role = claims.get("custom:role")
        if role not in ALLOWED_ROLES:
            return {"statusCode": 403, "body": json.dumps({"error": "Unauthorized role"})}

        # ------------------------------------------------------------
        # Read query parameters
        # ------------------------------------------------------------
        params = event.get("queryStringParameters") or {}
        from_date_str = params.get("from_date")
        to_date_str = params.get("to_date")

        if not from_date_str or not to_date_str:
            return {"statusCode": 400, "body": json.dumps({"error": "from_date and to_date are required"})}

        # Parse dates
        from_date = parser.isoparse(from_date_str)
        to_date = parser.isoparse(to_date_str)

        conn = get_connection()
        cur = conn.cursor()

        # ------------------------------------------------------------
        # Daily Commits
        # ------------------------------------------------------------
        cur.execute("""
            SELECT DATE_TRUNC('day', timestamp) AS day, COUNT(*) AS commit_count
            FROM github_events
            WHERE timestamp BETWEEN %s AND %s AND commit_sha IS NOT NULL
            GROUP BY day
            ORDER BY day ASC;
        """, (from_date, to_date))

        commit_rows = cur.fetchall()
        # Map dates to ISO string
        commits_by_day = {r[0].date().isoformat(): r[1] for r in commit_rows}

        # Fill missing dates with 0
        day_cursor = from_date.date()
        daily_commits = {}
        while day_cursor <= to_date.date():
            daily_commits[str(day_cursor)] = commits_by_day.get(day_cursor.isoformat(), 0)
            day_cursor += timedelta(days=1)

        # ------------------------------------------------------------
        # Daily PRs
        # ------------------------------------------------------------
        cur.execute("""
            SELECT DATE_TRUNC('day', timestamp) AS day, COUNT(*) AS pr_count
            FROM pull_requests
            WHERE timestamp BETWEEN %s AND %s
            GROUP BY day
            ORDER BY day ASC;
        """, (from_date, to_date))

        pr_rows = cur.fetchall()
        prs_by_day = {r[0].date().isoformat(): r[1] for r in pr_rows}

        # Fill missing dates with 0
        day_cursor = from_date.date()
        daily_prs = {}
        while day_cursor <= to_date.date():
            daily_prs[str(day_cursor)] = prs_by_day.get(day_cursor.isoformat(), 0)
            day_cursor += timedelta(days=1)

        cur.close()
        conn.close()

        # ------------------------------------------------------------
        # Response
        # ------------------------------------------------------------
        return {
            "statusCode": 200,
            "body": json.dumps({
                "range": {"from": from_date.isoformat(), "to": to_date.isoformat()},
                "commits": daily_commits,
                "pull_requests": daily_prs
            }, indent=2)
        }

    except Exception as e:
        print("ERROR:", str(e))
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}
