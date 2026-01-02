# workload_analytics/app.py
"""
Minimal robust Workload Distribution API (6.3) - manager view.

This version:
- Checks whether tables and columns exist before querying.
- If a table/column is missing it treats that aggregation as empty (count = 0).
- Does NOT assume a `status` column anywhere.
- Keeps the same response shape as before.
"""
import os
import json
import math
import psycopg2
import psycopg2.extras
from datetime import datetime, timezone, timedelta, date

# Config from ENV
DEFAULT_CAPACITY = int(os.environ.get("DEFAULT_CAPACITY", "8"))
ROLE_CAPACITIES = {
    "DEV": int(os.environ.get("CAP_DEV", "8")),
    "QA": int(os.environ.get("CAP_QA", "6")),
    "MANAGER": int(os.environ.get("CAP_MANAGER", "5")),
    "DEV_MANAGER": int(os.environ.get("CAP_DEV_MANAGER", "6"))
}
WEIGHT_ISSUE = float(os.environ.get("WEIGHT_ISSUE", "1.0"))
WEIGHT_SUBTASK = float(os.environ.get("WEIGHT_SUBTASK", "0.5"))
WEIGHT_PR = float(os.environ.get("WEIGHT_PR", "0.8"))
WEIGHT_COMMIT = float(os.environ.get("WEIGHT_COMMIT", "0.1"))
HIGH_PRIORITY_MULTIPLIER = float(os.environ.get("HIGH_PRIORITY_MULTIPLIER", "1.5"))
UNDERLOAD_THRESHOLD_PERCENT = float(os.environ.get("UNDERLOAD_THRESHOLD_PERCENT", "80.0"))
DEFAULT_COMMIT_DAYS = int(os.environ.get("DEFAULT_COMMIT_DAYS", "7"))

class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        return super().default(obj)

def get_connection():
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        dbname=os.environ["DB_NAME"],
        port=int(os.environ.get("DB_PORT", 5432))
    )

def iso_now_utc():
    return datetime.now(timezone.utc)

def percent(x, y):
    if y == 0:
        return 0.0
    return round((x / y) * 100.0, 1)

def success(data):
    return {"statusCode": 200, "body": json.dumps({"status": 200, "data": data}, cls=DateTimeEncoder, indent=2)}

def error(status, message):
    return {"statusCode": status, "body": json.dumps({"status": status, "message": message})}

# ---------------------------
# Introspection helpers
# ---------------------------
def table_exists(conn, table_name, schema='public'):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema=%s AND table_name=%s)",
            (schema, table_name)
        )
        return cur.fetchone()[0]

def get_table_columns(conn, table_name, schema='public'):
    if not table_exists(conn, table_name, schema):
        return set()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s",
            (schema, table_name)
        )
        return set(r[0].lower() for r in cur.fetchall())

# ---------------------------
# Data loaders (defensive)
# ---------------------------
def load_users(cur, org_id=None):
    params = []
    where = ""
    if org_id:
        where = "WHERE org_id = %s"
        params = [org_id]
    try:
        cur.execute(f"""
            SELECT id::text AS id, display_name, email, role, org_id, created_at
            FROM users
            {where}
        """, params)
    except Exception:
        return {}
    users = {}
    for r in cur.fetchall():
        uid = r['id']
        users[uid] = {
            "user_id": uid,
            "name": r.get('display_name') or r.get('email') or uid,
            "email": r.get('email'),
            "role": (r.get('role') or "DEV"),
            "org_id": r.get('org_id'),
            "open_issues": 0,
            "high_priority_count": 0,
            "open_subtasks": 0,
            "open_prs": 0,
            "recent_commits": 0,
            "total_load": 0.0,
            "capacity": None,
            "status": "offline",
            "avatar": None
        }
    return users

def load_jira_mapping(cur):
    try:
        cur.execute("SELECT internal_user_id::text AS internal_user_id, jira_account_id FROM users_jira_mapping")
    except Exception:
        return {}
    mapping = {}
    for r in cur.fetchall():
        jira_id = r.get('jira_account_id')
        if jira_id:
            mapping[str(jira_id)] = r.get('internal_user_id')
    return mapping

# Each aggregation will first check if table exists and required columns exist; if not, it returns empty list.

def aggregate_open_issues(cur, conn, org_id=None):
    if not table_exists(conn, 'jira_issues'):
        return []
    cols = get_table_columns(conn, 'jira_issues')
    params = []
    where_org = ""
    if org_id:
        where_org = "AND org_id = %s"
        params.append(org_id)
    # Use priority if exists, otherwise NULL/default
    priority_col = "LOWER(priority) AS priority" if 'priority' in cols else "NULL AS priority"
    # If status exists, filter out done/closed/resolved; else count all rows
    if 'status' in cols:
        sql = f"""
            SELECT assignee_user_id, {priority_col}, COUNT(*) AS cnt
            FROM jira_issues
            WHERE assignee_user_id IS NOT NULL
              AND LOWER(status) NOT IN ('done', 'closed', 'resolved')
              {where_org}
            GROUP BY assignee_user_id, { 'LOWER(priority)' if 'priority' in cols else 'NULL' }
        """
    else:
        sql = f"""
            SELECT assignee_user_id, {priority_col}, COUNT(*) AS cnt
            FROM jira_issues
            WHERE assignee_user_id IS NOT NULL
              {where_org}
            GROUP BY assignee_user_id, { 'LOWER(priority)' if 'priority' in cols else 'NULL' }
        """
    try:
        cur.execute(sql, params)
        return cur.fetchall()
    except Exception:
        return []

def aggregate_subtasks(cur, conn):
    if not table_exists(conn, 'jira_subtasks'):
        return []
    cols = get_table_columns(conn, 'jira_subtasks')
    # If status exists we get status per author; else just author & count
    if 'status' in cols:
        try:
            cur.execute("SELECT author_login, status, COUNT(*) AS cnt FROM jira_subtasks GROUP BY author_login, status")
            return cur.fetchall()
        except Exception:
            return []
    else:
        try:
            cur.execute("SELECT author_login, COUNT(*) AS cnt FROM jira_subtasks GROUP BY author_login")
            # normalize rows to have author_login, status (None) and cnt to match code expectations
            return [{ 'author_login': r['author_login'], 'status': None, 'cnt': r['cnt'] } for r in cur.fetchall()]
        except Exception:
            return []

def aggregate_open_prs(cur, conn):
    if not table_exists(conn, 'pull_requests'):
        return []
    cols = get_table_columns(conn, 'pull_requests')
    if 'state' in cols:
        try:
            cur.execute("SELECT author_login, COUNT(*) AS cnt FROM pull_requests WHERE LOWER(state) = 'open' GROUP BY author_login")
            return cur.fetchall()
        except Exception:
            return []
    else:
        try:
            cur.execute("SELECT author_login, COUNT(*) AS cnt FROM pull_requests GROUP BY author_login")
            return cur.fetchall()
        except Exception:
            return []

def aggregate_commits(cur, conn, since_dt):
    if not table_exists(conn, 'github_events'):
        return []
    cols = get_table_columns(conn, 'github_events')
    if 'commit_sha' in cols and 'timestamp' in cols:
        try:
            cur.execute("""
                SELECT author_email, COUNT(*) AS cnt
                FROM github_events
                WHERE commit_sha IS NOT NULL AND timestamp >= %s
                GROUP BY author_email
            """, (since_dt,))
            return cur.fetchall()
        except Exception:
            return []
    else:
        return []

def load_presence(cur, conn, user_ids):
    # If realtime_connections table exists, mark user as 'online' if there is any row for them (we do NOT expect status column)
    if not user_ids:
        return {}
    if not table_exists(conn, 'realtime_connections'):
        return {}
    cols = get_table_columns(conn, 'realtime_connections')
    # Ensure user_id exists in the table
    if 'user_id' not in cols:
        return {}
    try:
        cur.execute("SELECT user_id::text AS user_id FROM realtime_connections WHERE user_id = ANY(%s) ORDER BY connected_at DESC", (list(user_ids),))
        result = {}
        for r in cur.fetchall():
            uid = r['user_id']
            if uid not in result:
                # There exists a connection row -> mark online (we avoid using 'status' column)
                result[uid] = 'online'
        return result
    except Exception:
        return {}

# ---------------------------
# Main handler
# ---------------------------
def lambda_handler(event, context):
    try:
        q = (event.get("queryStringParameters") or {}) or {}
        org_id = q.get("org_id")
        capacity_override = q.get("capacity_override")
        commits_days = int(q.get("commits_days") or os.environ.get("DEFAULT_COMMIT_DAYS", DEFAULT_COMMIT_DAYS))

        if capacity_override:
            try:
                capacity_override = int(capacity_override)
            except Exception:
                capacity_override = None

        now = iso_now_utc()
        commit_since = now - timedelta(days=commits_days)

        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        users = load_users(cur, org_id=org_id)
        email_to_user = {u['email']: uid for uid, u in users.items() if u.get('email')}
        name_to_user = {u['name']: uid for uid, u in users.items() if u.get('name')}
        jira_map = load_jira_mapping(cur)

        # 1) Issues
        rows_issues = aggregate_open_issues(cur, conn, org_id=org_id)
        for r in rows_issues:
            assignee = r.get('assignee_user_id')
            cnt = int(r.get('cnt') or 0)
            priority_raw = r.get('priority') if 'priority' in r else None
            priority = (priority_raw or "").lower()
            # mapping
            mapped_uid = None
            if assignee in users:
                mapped_uid = assignee
            elif assignee and assignee in jira_map:
                mapped_uid = jira_map.get(assignee)
            if not mapped_uid and assignee in name_to_user:
                mapped_uid = name_to_user.get(assignee)
            if not mapped_uid and assignee in email_to_user:
                mapped_uid = email_to_user.get(assignee)
            if not mapped_uid:
                mapped_uid = f"external:issue:{assignee}"
                if mapped_uid not in users:
                    users[mapped_uid] = {
                        "user_id": mapped_uid, "name": assignee, "email": None, "role": "DEV", "org_id": org_id,
                        "open_issues": 0, "high_priority_count": 0, "open_subtasks": 0, "open_prs": 0,
                        "recent_commits": 0, "total_load": 0.0, "capacity": None, "status": "offline", "avatar": None
                    }
            if priority in ("high", "critical"):
                users[mapped_uid]['open_issues'] = users[mapped_uid].get('open_issues', 0) + cnt
                users[mapped_uid]['high_priority_count'] = users[mapped_uid].get('high_priority_count', 0) + cnt
            else:
                users[mapped_uid]['open_issues'] = users[mapped_uid].get('open_issues', 0) + cnt

        # 2) Subtasks
        rows_subtasks = aggregate_subtasks(cur, conn)
        for r in rows_subtasks:
            author = r.get('author_login')
            status = (r.get('status') or "").lower() if 'status' in r else None
            cnt = int(r.get('cnt') or 0)
            # treat as open unless status explicitly done/closed/resolved
            if status and status in ('done', 'closed', 'resolved'):
                continue
            mapped_uid = None
            if author and author in jira_map:
                mapped_uid = jira_map.get(author)
            if not mapped_uid and author in name_to_user:
                mapped_uid = name_to_user.get(author)
            if not mapped_uid and author in email_to_user:
                mapped_uid = email_to_user.get(author)
            if not mapped_uid:
                mapped_uid = f"external:subtask:{author}"
                if mapped_uid not in users:
                    users[mapped_uid] = {
                        "user_id": mapped_uid, "name": author, "email": None, "role": "DEV", "org_id": org_id,
                        "open_issues": 0, "high_priority_count": 0, "open_subtasks": 0, "open_prs": 0,
                        "recent_commits": 0, "total_load": 0.0, "capacity": None, "status": "offline", "avatar": None
                    }
            users[mapped_uid]['open_subtasks'] = users[mapped_uid].get('open_subtasks', 0) + cnt

        # 3) PRs
        rows_prs = aggregate_open_prs(cur, conn)
        for r in rows_prs:
            author = r.get('author_login')
            cnt = int(r.get('cnt') or 0)
            mapped_uid = None
            if author in name_to_user:
                mapped_uid = name_to_user.get(author)
            if not mapped_uid and author in email_to_user:
                mapped_uid = email_to_user.get(author)
            if not mapped_uid:
                mapped_uid = f"external:pr:{author}"
                if mapped_uid not in users:
                    users[mapped_uid] = {
                        "user_id": mapped_uid, "name": author, "email": None, "role": "DEV", "org_id": org_id,
                        "open_issues": 0, "high_priority_count": 0, "open_subtasks": 0, "open_prs": 0,
                        "recent_commits": 0, "total_load": 0.0, "capacity": None, "status": "offline", "avatar": None
                    }
            users[mapped_uid]['open_prs'] = users[mapped_uid].get('open_prs', 0) + cnt

        # 4) Commits
        rows_commits = aggregate_commits(cur, conn, commit_since)
        for r in rows_commits:
            email = r.get('author_email')
            cnt = int(r.get('cnt') or 0)
            mapped_uid = None
            if email and email in email_to_user:
                mapped_uid = email_to_user.get(email)
            if not mapped_uid:
                mapped_uid = f"external:commit:{email}"
                if mapped_uid not in users:
                    users[mapped_uid] = {
                        "user_id": mapped_uid, "name": email, "email": email, "role": "DEV", "org_id": org_id,
                        "open_issues": 0, "high_priority_count": 0, "open_subtasks": 0, "open_prs": 0,
                        "recent_commits": 0, "total_load": 0.0, "capacity": None, "status": "offline", "avatar": None
                    }
            users[mapped_uid]['recent_commits'] = users[mapped_uid].get('recent_commits', 0) + cnt

        # 5) Presence - mark online if a row exists in realtime_connections for that user (NO status column used)
        internal_user_ids = [uid for uid in users.keys() if not uid.startswith("external:")]
        presence_map = load_presence(cur, conn, internal_user_ids)
        for uid, status in presence_map.items():
            if uid in users:
                users[uid]['status'] = status

        # 6) compute loads
        for uid, u in users.items():
            role = (u.get('role') or "DEV")
            capacity = ROLE_CAPACITIES.get(role, DEFAULT_CAPACITY)
            if capacity_override:
                capacity = capacity_override
            u['capacity'] = capacity

            issues = u.get('open_issues', 0)
            high_priority = u.get('high_priority_count', 0)
            subtasks = u.get('open_subtasks', 0)
            prs = u.get('open_prs', 0)
            commits = u.get('recent_commits', 0)

            base_issue_component = issues * WEIGHT_ISSUE
            high_priority_boost = high_priority * WEIGHT_ISSUE * (HIGH_PRIORITY_MULTIPLIER - 1)

            total_load = (base_issue_component + high_priority_boost +
                          subtasks * WEIGHT_SUBTASK +
                          prs * WEIGHT_PR +
                          commits * WEIGHT_COMMIT)

            u['total_load'] = round(total_load, 2)
            u['utilization_percent'] = percent(u['total_load'], capacity)
            u['overloaded'] = True if u['total_load'] > capacity else False

        # 7) suggestions as original logic
        sorted_over = sorted([ (uid, users[uid]) for uid in users if users[uid]['overloaded'] ],
                             key=lambda x: x[1]['total_load'], reverse=True)
        underloaded = sorted([ (uid, users[uid]) for uid in users if not users[uid]['overloaded'] and users[uid]['utilization_percent'] < UNDERLOAD_THRESHOLD_PERCENT ],
                             key=lambda x: x[1]['utilization_percent'])
        suggestions = []
        for uid, udata in sorted_over:
            need = int(math.ceil(max(0.0, udata['total_load'] - udata['capacity'])))
            recs = []
            if need <= 0:
                continue
            for rec_uid, rec_u in underloaded:
                if rec_uid == uid:
                    continue
                capacity_left = max(0, rec_u['capacity'] - rec_u['total_load'])
                if capacity_left <= 0:
                    continue
                allocate = min(need, int(max(1, round(capacity_left))))
                recs.append({
                    "to_user_id": rec_uid,
                    "to_name": rec_u['name'],
                    "assign_suggested": allocate
                })
                need -= allocate
                rec_u['total_load'] += allocate
                rec_u['utilization_percent'] = percent(rec_u['total_load'], rec_u['capacity'])
                if need <= 0:
                    break
            suggestions.append({
                "from_user_id": uid,
                "from_name": udata['name'],
                "tasks_to_move": int(math.ceil(max(0.0, udata['total_load'] - udata['capacity']))),
                "recommendations": recs
            })

        developers = []
        for uid, u in sorted(users.items(), key=lambda x: ( -x[1]['utilization_percent'], x[1]['name'] )):
            developers.append({
                "user_id": u['user_id'],
                "name": u['name'],
                "email": u.get('email'),
                "avatar": u.get('avatar'),
                "role": u.get('role'),
                "status": u.get('status'),
                "open_issues": u.get('open_issues', 0),
                "high_priority_issues": u.get('high_priority_count', 0),
                "open_subtasks": u.get('open_subtasks', 0),
                "open_prs": u.get('open_prs', 0),
                "recent_commits": u.get('recent_commits', 0),
                "total_load": u.get('total_load'),
                "capacity": u.get('capacity'),
                "utilization_percent": u.get('utilization_percent'),
                "overloaded": u.get('overloaded')
            })

        meta = {
            "generated_at": iso_now_utc(),
            "global_capacity_effective": capacity_override or ROLE_CAPACITIES.get("DEV", DEFAULT_CAPACITY),
            "redistribution_suggestions": suggestions
        }

        cur.close()
        conn.close()
        return success({"developers": developers, "meta": meta})

    except Exception as exc:
        try:
            cur.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass
        print("ERROR in workload lambda:", str(exc))
        return error(500, f"Internal server error: {str(exc)}")