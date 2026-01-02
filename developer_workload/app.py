import os
import json
import psycopg2
from datetime import datetime, timezone

# DB Config
DB_HOST = os.environ.get("DB_HOST")
DB_USER = os.environ.get("DB_USER")
DB_PASSWORD = os.environ.get("DB_PASSWORD")
DB_NAME = os.environ.get("DB_NAME")

def get_connection():
    return psycopg2.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        dbname=DB_NAME
    )


def is_high_priority(priority):
    if not priority:
        return False

    p = priority.strip().lower()
    return any(keyword in p for keyword in (
        "highest",
        "high",
        "critical",
        "blocker",
        "p0",
        "p1"
    ))


def lambda_handler(event, context):
    conn = get_connection()
    cur = conn.cursor()

    params = event.get("queryStringParameters") or {}

    email = params.get("email")
    sprint_id = params.get("sprint_id")



    # -------------------------
    # Fetch Jira Issues (Sprint Scoped)
    # -------------------------
    base_query = """
        SELECT assignee_user_id,
            assignee_name,
            assignee_email,
            status,
            priority,
            updated_at
        FROM jira_issues
        WHERE assignee_user_id IS NOT NULL
    """

    params = []

    if email:
        base_query += " AND assignee_email = %s"
        params.append(email)

    if sprint_id:
        base_query += """
            AND jsonb_typeof(raw->'fields'->'customfield_10020') = 'array'
            AND EXISTS (
                SELECT 1
                FROM jsonb_array_elements(raw->'fields'->'customfield_10020') sprint
                WHERE sprint->>'id' = %s
            )
        """
        params.append(sprint_id)

    cur.execute(base_query, tuple(params))
    issues = cur.fetchall()


    # -------------------------
    # Fetch Jira Subtasks (Sprint Scoped)
    # -------------------------
    if email:
        cur.execute("""
            SELECT assignee_user_id,
                assignee_name,
                assignee_email,
                status,
                priority,
                updated_at
            FROM jira_issues
            WHERE assignee_user_id IS NOT NULL
            AND assignee_email = %s
            AND jsonb_typeof(raw->'fields'->'customfield_10020') = 'array'
            AND EXISTS (
                SELECT 1
                FROM jsonb_array_elements(raw->'fields'->'customfield_10020') sprint
                WHERE sprint->>'id' = %s
            )
        """, (email, sprint_id))
    else:
        cur.execute("""
    SELECT assignee_user_id,
           assignee_name,
           assignee_email,
           status,
           priority,
           updated_at
    FROM jira_issues
    WHERE assignee_user_id IS NOT NULL
      AND jsonb_path_exists(
            raw,
            '$.fields.customfield_10020[*] ? (@.id == $sprint_id)',
            jsonb_build_object('sprint_id', to_jsonb(%s::int))
          )
""", (sprint_id,))



    subtasks = cur.fetchall()

    cur.close()
    conn.close()

    now = datetime.now(timezone.utc)
    workload = {}

    # -------------------------
    # Process Issues
    # -------------------------
    for assignee_id, name, assignee_email, status, priority, updated_at in issues:
        if assignee_id not in workload:
            workload[assignee_id] = {
                "name": name,
                "email": assignee_email,
                "open_issues": 0,
                "high_priority_issues": 0,
                "idle_days_max": 0,
                "subtasks": 0
            }

        if status.lower() not in ("done", "closed", "resolved"):
            workload[assignee_id]["open_issues"] += 1

            if is_high_priority(priority):
                workload[assignee_id]["high_priority_issues"] += 1

        if updated_at:
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=timezone.utc)

            idle_days = (now - updated_at).days
            workload[assignee_id]["idle_days_max"] = max(
                workload[assignee_id]["idle_days_max"],
                idle_days
            )

    # -------------------------
    # Process Subtasks
    # -------------------------
    # -------------------------
    # Process Subtasks
    # -------------------------
    for assignee_id, name, assignee_email, status, priority, updated_at in subtasks:
        if assignee_id not in workload:
            workload[assignee_id] = {
                "name": name,
                "email": assignee_email,
                "open_issues": 0,
                "high_priority_issues": 0,
                "idle_days_max": 0,
                "subtasks": 0
            }

        if status and status.lower() not in ("done", "closed", "resolved"):
            workload[assignee_id]["subtasks"] += 1


    # -------------------------
    # Prepare Response
    # -------------------------
    response = []
    for user_id, metrics in workload.items():
        response.append({
            "user_id": user_id,
            "name": metrics["name"],
            "email": metrics.get("email"),
            "open_issues": metrics["open_issues"],
            "high_priority_issues": metrics["high_priority_issues"],
            "subtasks": metrics["subtasks"],
            "max_idle_days": metrics["idle_days_max"]
        })

    return {
        "statusCode": 200,
        "body": json.dumps(response, indent=2)
    }
