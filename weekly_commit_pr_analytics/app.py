import os
import json
import psycopg2
import psycopg2.extras
from datetime import datetime, timedelta, timezone
import pytz

# ==========================
# JSON Encoder
# ==========================
class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (datetime,)):
            return obj.isoformat()
        return super().default(obj)

def make_aware(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt

def parse_date(date_str):
    dt = datetime.fromisoformat(date_str)
    return dt.astimezone(pytz.UTC)

# ==========================
# DB Connection
# ==========================
def get_connection():
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        dbname=os.environ["DB_NAME"],
        port=5432
    )

# ==========================
# Response helpers
# ==========================
def success(message, data):
    return {
        "statusCode": 200,
        "body": json.dumps({"status": 200, "message": message, "data": data}, cls=DateTimeEncoder, indent=2),
    }

def error(status, message):
    return {
        "statusCode": status,
        "body": json.dumps({"status": status, "message": message}),
    }

# ==========================
# Helper to map results to Mon-Sun
# ==========================
def map_to_weekdays(results, value_key):
    weekday_map = {0:'Mon',1:'Tue',2:'Wed',3:'Thu',4:'Fri',5:'Sat',6:'Sun'}
    daily_counts = {name:0 for name in weekday_map.values()}
    for r in results:
        day = make_aware(r['day'])
        weekday_name = weekday_map[day.weekday()]
        daily_counts[weekday_name] = r[value_key]
    return daily_counts

# ==========================
# Fetch daily commits
# ==========================
def fetch_daily_commits(cursor, from_date, to_date):
    cursor.execute("""
        SELECT
            DATE_TRUNC('day', timestamp) AS day,
            COUNT(*) AS total_commits
        FROM git_commits
        WHERE timestamp BETWEEN %s AND %s
        GROUP BY day
        ORDER BY day ASC;
    """, (from_date, to_date))
    results = cursor.fetchall()
    return map_to_weekdays(results, 'total_commits')

# ==========================
# Fetch daily PRs
# ==========================
def fetch_daily_prs(cursor, from_date, to_date):
    cursor.execute("""
        SELECT
            DATE_TRUNC('day', timestamp) AS day,
            COUNT(*) AS total_prs
        FROM pull_requests
        WHERE timestamp BETWEEN %s AND %s
        GROUP BY day
        ORDER BY day ASC;
    """, (from_date, to_date))
    results = cursor.fetchall()
    return map_to_weekdays(results, 'total_prs')

# ==========================
# Lambda handler
# ==========================
def lambda_handler(event, context):
    try:
        query = event.get("queryStringParameters") or {}
        from_date_str = query.get("from_date")
        to_date_str = query.get("to_date")

        if not from_date_str or not to_date_str:
            return error(400, "from_date and to_date query params are required")

        from_date = parse_date(from_date_str)
        to_date = parse_date(to_date_str)

        conn = get_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        commits_by_day = fetch_daily_commits(cursor, from_date, to_date)
        prs_by_day = fetch_daily_prs(cursor, from_date, to_date)

        cursor.close()
        conn.close()

        return success("Weekly Commit & PR Analytics fetched successfully", {
            "commits": commits_by_day,
            "pull_requests": prs_by_day
        })

    except Exception as e:
        print("ERROR:", str(e))
        return error(500, f"Internal server error: {str(e)}")
