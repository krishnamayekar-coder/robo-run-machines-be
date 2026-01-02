import os
import json
import psycopg2
from datetime import datetime, timedelta

# ==========================
# DB Connection
# ==========================
def get_connection():
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        dbname=os.environ["DB_NAME"],
        port=int(os.environ.get("DB_PORT", 5432))
    )

# ==========================
# Helpers
# ==========================
def trend_arrow(current, previous):
    if current > previous:
        return "up"
    elif current < previous:
        return "down"
    return "stable"

# ==========================
# Lambda Handler
# ==========================
def lambda_handler(event, context):

    # thresholds
    WINDOW_DAYS = int(os.environ.get("WINDOW_DAYS", 7))
    AT_RISK_DAYS = int(os.environ.get("AT_RISK_DAYS", 7))
    HIGH_PRIORITY_DAYS = int(os.environ.get("HIGH_PRIORITY_DAYS", 5))
    PR_STUCK_HOURS = int(os.environ.get("PR_STUCK_HOURS", 72))

    now = datetime.utcnow()

    current_start = now - timedelta(days=WINDOW_DAYS)
    previous_start = now - timedelta(days=WINDOW_DAYS * 2)

    conn = get_connection()
    cur = conn.cursor()

    # ==========================
    # CURRENT WINDOW
    # ==========================

    # At-Risk Jira
    cur.execute("""
        SELECT COUNT(*)
        FROM jira_issues
        WHERE status NOT IN ('Done','Closed','Resolved')
          AND updated_at < %s
    """, (now - timedelta(days=AT_RISK_DAYS),))
    at_risk_current = cur.fetchone()[0]

    # High Priority – Past Due
    cur.execute("""
        SELECT COUNT(*)
        FROM jira_issues
        WHERE priority IN ('High','Critical')
          AND status NOT IN ('Done','Closed','Resolved')
          AND updated_at < %s
    """, (now - timedelta(days=HIGH_PRIORITY_DAYS),))
    high_priority_current = cur.fetchone()[0]

    # PRs Stuck (USE timestamp, NOT updated_at)
    cur.execute("""
        SELECT COUNT(*)
        FROM pull_requests
        WHERE state = 'open'
          AND merged = false
          AND timestamp < %s
    """, (now - timedelta(hours=PR_STUCK_HOURS),))
    prs_stuck_current = cur.fetchone()[0]

    # Critical Incidents (current window)
    cur.execute("""
        SELECT COUNT(*)
        FROM servicenow_incidents
        WHERE severity IN ('High','Critical')
          AND state NOT IN ('Resolved','Closed')
          AND created_at >= %s
    """, (current_start,))
    incidents_current = cur.fetchone()[0]

    # ==========================
    # PREVIOUS WINDOW
    # ==========================

    cur.execute("""
        SELECT COUNT(*)
        FROM jira_issues
        WHERE status NOT IN ('Done','Closed','Resolved')
          AND updated_at < %s
    """, (current_start - timedelta(days=AT_RISK_DAYS),))
    at_risk_previous = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*)
        FROM jira_issues
        WHERE priority IN ('High','Critical')
          AND status NOT IN ('Done','Closed','Resolved')
          AND updated_at < %s
    """, (current_start - timedelta(days=HIGH_PRIORITY_DAYS),))
    high_priority_previous = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*)
        FROM pull_requests
        WHERE state = 'open'
          AND merged = false
          AND timestamp < %s
    """, (current_start - timedelta(hours=PR_STUCK_HOURS),))
    prs_stuck_previous = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*)
        FROM servicenow_incidents
        WHERE severity IN ('High','Critical')
          AND state NOT IN ('Resolved','Closed')
          AND created_at BETWEEN %s AND %s
    """, (previous_start, current_start))
    incidents_previous = cur.fetchone()[0]

    cur.close()
    conn.close()

    # ==========================
    # Response
    # ==========================
    response = {
        "at_risk_jira": {
            "count": at_risk_current,
            "trend": trend_arrow(at_risk_current, at_risk_previous)
        },
        "high_priority_delayed": {
            "count": high_priority_current,
            "trend": trend_arrow(high_priority_current, high_priority_previous)
        },
        "prs_stuck": {
            "count": prs_stuck_current,
            "trend": trend_arrow(prs_stuck_current, prs_stuck_previous)
        },
        "critical_incidents": {
            "count": incidents_current,
            "trend": trend_arrow(incidents_current, incidents_previous)
        }
    }

    return {
        "statusCode": 200,
        "body": json.dumps(response, indent=2)
    }