import os
import json
import psycopg2
from datetime import datetime, timezone

# DB config
DB_HOST = os.environ.get("DB_HOST")
DB_USER = os.environ.get("DB_USER")
DB_PASSWORD = os.environ.get("DB_PASSWORD")
DB_NAME = os.environ.get("DB_NAME")
PR_IDLE_THRESHOLD_DAYS = int(os.environ.get("PR_IDLE_THRESHOLD_DAYS", 2))  # define bottleneck threshold

def get_connection():
    return psycopg2.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        dbname=DB_NAME
    )

def lambda_handler(event, context):
    conn = get_connection()
    cur = conn.cursor()
    
    # Fetch all PRs from the table
    cur.execute("""
        SELECT pr_number, title, state, author_login, timestamp, raw
        FROM pull_requests
    """)
    
    rows = cur.fetchall()
    cur.close()
    conn.close()
    
    bottlenecks = []
    now = datetime.now(timezone.utc)
    
    for row in rows:
        pr_number, title, state, author, updated_at, raw_json = row
        
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        
        idle_days = (now - updated_at).days
        
        # Bottleneck if PR is open/closed but idle for more than threshold
        if state in ("open", "closed") and idle_days >= PR_IDLE_THRESHOLD_DAYS:
            bottlenecks.append({
                "pr_number": pr_number,
                "title": title,
                "state": state,
                "author": author,

                # Time
                "idle_days": idle_days,
                "last_updated": updated_at.isoformat(),
                "last_updated_ago": f"{idle_days} days ago" if idle_days > 0 else "few hours ago",

                # GitHub stats
                "commits": raw_json.get("commits"),
                "files_changed": raw_json.get("changed_files"),
                "additions": raw_json.get("additions"),
                "deletions": raw_json.get("deletions"),
                "total_changes": (raw_json.get("additions", 0) + raw_json.get("deletions", 0)),

                # Branch info
                "base_branch": raw_json.get("base", {}).get("ref"),
                "head_branch": raw_json.get("head", {}).get("ref"),

                # URLs
                "url": raw_json.get("html_url")
            })

    
    return {
        "statusCode": 200,
        "body": json.dumps({"bottlenecks": bottlenecks}, indent=2)
    }
