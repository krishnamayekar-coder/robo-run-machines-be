import os
import json
import psycopg2
from datetime import datetime, date

ALLOWED_ROLES = ["DEV", "QA", "MANAGER", "DEV_MANAGER"]

# ==========================================================
# PostgreSQL Connection
# ==========================================================
def get_connection():
    try:
        return psycopg2.connect(
            host=os.environ["DB_HOST"],
            user=os.environ["DB_USER"],
            password=os.environ["DB_PASSWORD"],
            dbname=os.environ["DB_NAME"],
            port=5432
        )
    except Exception as e:
        print("DB Connection Error:", str(e))
        raise

# ==========================================================
# Lambda Handler
# ==========================================================
def lambda_handler(event, context):
    try:
        # Extract JWT claims
        claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
        user_email = claims.get("email")
        user_role = claims.get("custom:role")

        print("User Email:", user_email)
        print("User Role:", user_role)

        # Role-based access control
        if not user_role or user_role not in ALLOWED_ROLES:
            return {
                "statusCode": 403,
                "body": json.dumps({"error": "Access denied. Your role does not allow access."})
            }

        conn = get_connection()
        cur = conn.cursor()

        # ==========================================================
        # Determine filter: all tasks vs user tasks
        # ==========================================================
        if user_role == "DEV_MANAGER":
            # Fetch all tasks updated today
            issue_filter = ""
            subtask_filter = ""
            params = ()
        else:
            # Fetch only tasks assigned to current user
            issue_filter = "WHERE (assignee_user_id = %s OR assignee_name = %s) AND DATE(updated_at) = CURRENT_DATE"
            subtask_filter = "WHERE author_login = %s AND DATE(timestamp) = CURRENT_DATE"
            params = (user_email, user_email)

        # ==========================================================
        # Fetch Jira Issues
        # ==========================================================
        issue_query = f"""
            SELECT 
                id,
                issue_key,
                assignee_user_id,
                assignee_name,
                status,
                priority,
                component,
                updated_at,
                raw
            FROM jira_issues
            {issue_filter}
            ORDER BY updated_at DESC
        """
        cur.execute(issue_query, params)
        issues_today = cur.fetchall()

        # ==========================================================
        # Fetch Jira Subtasks
        # ==========================================================
        subtask_query = f"""
            SELECT 
                id,
                subtask_id,
                parent_issue_id,
                board_id,
                summary,
                status,
                event_type,
                author_login,
                timestamp,
                raw
            FROM jira_subtasks
            {subtask_filter}
            ORDER BY timestamp DESC
        """
        cur.execute(subtask_query, params if user_role != "DEV_MANAGER" else ())
        subtasks_today = cur.fetchall()

        cur.close()
        conn.close()

        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": "Today's Jira Tasks",
                "user": user_email,
                "issues_today": issues_today,
                "subtasks_today": subtasks_today
            }, default=str,indent=2)
        }

    except Exception as e:
        print("Error:", str(e))
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
