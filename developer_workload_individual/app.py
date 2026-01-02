import os
import json
import psycopg2
from datetime import datetime, timezone, timedelta

def to_utc(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


DB_HOST = os.environ.get("DB_HOST")
DB_USER = os.environ.get("DB_USER")
DB_PASSWORD = os.environ.get("DB_PASSWORD")
DB_NAME = os.environ.get("DB_NAME")

DONE_STATUSES = ("done", "closed", "resolved")
STORY_POINTS_FIELD = "customfield_10016"

SPRINT_DAYS = 14
HISTORICAL_SPRINTS = 3

def get_connection():
    return psycopg2.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        dbname=DB_NAME
    )

def calculate_load_label(assigned, avg):
    if avg == 0:
        return "🟢 Balanced"

    ratio = assigned / avg
    if ratio <= 1.10:
        return "🟢 Balanced"
    elif ratio <= 1.30:
        return "🟡 High"
    else:
        return "🔴 Overloaded"

def empty_github_event():
    return {
        "commits_today": 0,
        "commits_7d": 0,
        "prs_open": 0,
        "prs_created_7d": 0,
        "prs_merged_7d": 0,
        "last_github_activity_days": None
    }

def lambda_handler(event, context):
    conn = get_connection()
    cur = conn.cursor()

    now = datetime.now(timezone.utc)
    current_sprint_start = now - timedelta(days=SPRINT_DAYS)
    historical_start = now - timedelta(days=SPRINT_DAYS * HISTORICAL_SPRINTS)

    # ---------------------------
    # Historical averages
    # ---------------------------
    cur.execute(f"""
        SELECT
            assignee_user_id,
            assignee_name,
            MAX(raw->'fields'->'assignee'->>'emailAddress') AS assignee_email,
            COALESCE(
                AVG(NULLIF((raw->'fields'->>'{STORY_POINTS_FIELD}'), '')::int),
                0
            ) AS avg_points
        FROM jira_issues
        WHERE updated_at >= %s AND updated_at < %s
        GROUP BY assignee_user_id, assignee_name
    """, (historical_start, current_sprint_start))

    avg_map = {
        row[0]: {
            "name": row[1],
            "email": row[2],
            "avg_points": float(row[3])
        }
        for row in cur.fetchall()
    }

    # ---------------------------
    # Current sprint Jira data
    # ---------------------------
    cur.execute(f"""
        SELECT
            assignee_user_id,
            assignee_name,
            MAX(assignee_email) AS assignee_email,
            COALESCE(
                SUM(NULLIF((raw->'fields'->>'{STORY_POINTS_FIELD}'), '')::int),
                0
            ) AS assigned_points,
            COUNT(*) FILTER (WHERE status NOT IN %s) AS open_issues,
            COUNT(*) FILTER (WHERE priority IN ('High', 'Critical')) AS high_priority,
            COUNT(*) FILTER (WHERE status = 'IN_REVIEW') AS prs_review
        FROM jira_issues
        WHERE updated_at >= %s
        GROUP BY assignee_user_id, assignee_name
    """, (DONE_STATUSES, current_sprint_start))

    sprint_data = cur.fetchall()

    # ---------------------------
    # Subtasks
    # ---------------------------
    cur.execute("""
        SELECT author_login, COUNT(*)
        FROM jira_subtasks
        WHERE status NOT IN %s
        GROUP BY author_login
    """, (DONE_STATUSES,))
    subtasks = dict(cur.fetchall())

    # ---------------------------
    # GitHub Commits
    # ---------------------------
    cur.execute("""
        SELECT
            LOWER(author_email) AS user_key,
            COUNT(*) FILTER (WHERE timestamp::date = CURRENT_DATE) AS commits_today,
            COUNT(*) FILTER (WHERE timestamp >= NOW() - INTERVAL '7 days') AS commits_7d,
            MAX(timestamp) AS last_commit_at
            FROM git_commits
            WHERE author_email IS NOT NULL
            GROUP BY LOWER(author_email);

    """)
    commits = cur.fetchall()

    # ---------------------------
    # GitHub Pull Requests
    # ---------------------------
    cur.execute("""
        SELECT
            author_login AS user_key,
            COUNT(*) FILTER (WHERE state = 'open') AS prs_open,
            COUNT(*) FILTER (WHERE timestamp >= NOW() - INTERVAL '7 days') AS prs_created_7d,
            COUNT(*) FILTER (WHERE merged = true AND timestamp >= NOW() - INTERVAL '7 days') AS prs_merged_7d,
            MAX(timestamp) AS last_pr_at
        FROM pull_requests
        GROUP BY author_login
    """)
    prs = cur.fetchall()

    cur.close()
    conn.close()

    # ---------------------------
    # Build response
    # ---------------------------
    people = []
    overloaded_count = 0

    github_map = {}

    for user_key, ct, c7, last in commits:
        github_map.setdefault(user_key, empty_github_event())
        github_map[user_key]["commits_today"] += ct
        github_map[user_key]["commits_7d"] += c7
        last = to_utc(last)
        if last:
            github_map[user_key]["last_github_activity_days"] = (now - last).days


    for user_key, open_prs, created_7d, merged_7d, last in prs:
        github_map.setdefault(user_key, empty_github_event())
        github_map[user_key]["prs_open"] += open_prs
        github_map[user_key]["prs_created_7d"] += created_7d
        github_map[user_key]["prs_merged_7d"] += merged_7d
        last = to_utc(last)
        if last:
            days = (now - last).days
            prev = github_map[user_key]["last_github_activity_days"]
            github_map[user_key]["last_github_activity_days"] = (
                days if prev is None else min(prev, days)
            )


    for user_id, name, email, assigned, open_issues, high_priority, prs_review in sprint_data:
        avg_points = avg_map.get(user_id, {}).get("avg_points", 0)
        load_label = calculate_load_label(assigned, avg_points)

        if load_label == "🔴 Overloaded":
            overloaded_count += 1

        people.append({
            "name": name,
            "email": email,
            "role": "Developer",
            "assigned_story_points": assigned,
            "avg_story_points_last_3_sprints": round(avg_points, 1),
            "load_label": load_label,
            "tooltip": "Load is based on assigned story points compared to historical sprint averages.",
            "focus_today": {
                "active_jira_tickets": open_issues,
                "high_priority_tickets": high_priority,
                "prs_awaiting_review": prs_review,
                "subtasks": subtasks.get(user_id, 0),
                "github_event": github_map.get(email.lower() if email else None, empty_github_event())

            }
        })

    response = {
        "sprint_load_overview": people,
        "summary": {
            "overloaded_count": f"{overloaded_count} overloaded" if overloaded_count > 0 else None
        },
        "ai_suggestion": "Consider redistributing 2 tasks from Mike to Emily to balance the team workload."
    }

    return {
        "statusCode": 200,
        "body": json.dumps(response, indent=2)
    }
