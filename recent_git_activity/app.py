import os
import json
import psycopg2

ALLOWED_ROLES = ["DEV", "QA", "MANAGER", "DEV_MANAGER"]

def rows_to_dicts(cursor, rows):
    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row)) for row in rows]


# ==========================================================
# PostgreSQL Connection test
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
        sub = claims.get("sub")

        print("User Email:", user_email)
        print("User Role:", user_role)
        print("User sub:", sub)

        # Role-based access control
        if not user_role or user_role not in ALLOWED_ROLES:
            return {
                "statusCode": 403,
                "body": json.dumps({"error": "Access denied. Your role does not allow access."})
            }

        conn = get_connection()
        cur = conn.cursor()

        # Fetch user record
        cur.execute("SELECT id, email, role, created_at FROM users WHERE email=%s", (user_email,))
        user_row = cur.fetchone()
        user_record = {
            "id": user_row[0],
            "email": user_row[1],
            "role": user_row[2],
            "created_at": user_row[3]
        } if user_row else None


        # ================================================================
        # FETCH RECENT COMMITS (last 20)
        # ================================================================
                # ================================================================
        # FETCH RECENT COMMITS (last 20) – DERIVED FIELDS
        # ================================================================
        cur.execute("""
            SELECT
                gc.id,
                gc.repo,
                gc.commit_sha,
                gc.author_email AS author,
                gc.message,
                gc.timestamp,

                -- Jira Ticket ID (derived from message)
                substring(gc.message FROM '([A-Z]+-[0-9]+)') AS jira_ticket_id,

                -- PR linked or not
                CASE
                    WHEN pr.id IS NOT NULL THEN true
                    ELSE false
                END AS pr_linked,

                -- Branch (not stored yet)
                'UNKNOWN' AS branch,

                -- CI & Deployment (not implemented yet)
                'UNKNOWN' AS ci_status,
                'NOT_DEPLOYED' AS deployment_status,

                -- Commit Type (RULE-BASED, DERIVED)
                CASE
                    WHEN gc.message ILIKE '%fix%' THEN 'Bugfix'
                    WHEN gc.message ILIKE '%refactor%' THEN 'Refactor'
                    WHEN gc.message ILIKE '%test%' THEN 'Test'
                    ELSE 'Feature'
                END AS commit_type,

                -- Commit Message Quality Badge
                CASE
                    WHEN length(gc.message) >= 20
                         AND gc.message ~ '[A-Z]+-[0-9]+'
                    THEN 'Clear'
                    ELSE 'Needs Improvement'
                END AS message_quality

            FROM git_commits gc
            LEFT JOIN pull_requests pr
                ON pr.head_sha = gc.commit_sha

            ORDER BY gc.timestamp DESC
        """)
        rows = cur.fetchall()
        recent_commits = rows_to_dicts(cur, rows)


        # ================================================================
        # FETCH RECENT PULL REQUESTS (last 20)
        # ================================================================
        cur.execute("""
SELECT
    pr.id,
    pr.github_id,
    pr.repo,
    pr.pr_number,
    pr.title,

    -- PR action (webhook action)
    pr.action AS pr_action,

    -- GitHub state
    pr.state,

    pr.author_login,
    pr.head_sha,
    pr.merged,
    pr.timestamp,

    -- Reviewers (requested reviewers from GitHub payload)
    -- Reviewers (requested reviewers from GitHub payload)
    COALESCE(
        (
            SELECT jsonb_agg(r->>'login')
            FROM jsonb_array_elements(
                pr.raw->'requested_reviewers'
            ) r
        ),
        '[]'::jsonb
    ) AS reviewers,


    -- PR STATUS (overall lifecycle)
    CASE
        WHEN pr.merged = true THEN 'MERGED'
        WHEN pr.state = 'open'
             AND (pr.raw->'pull_request'->>'draft')::boolean = true
            THEN 'DRAFT'
        WHEN pr.state = 'open'
             AND jsonb_array_length(
                 COALESCE(pr.raw->'pull_request'->'requested_reviewers', '[]'::jsonb)
             ) > 0
            THEN 'IN_REVIEW'
        WHEN pr.state = 'open' THEN 'OPEN'
        ELSE 'CLOSED'
    END AS pr_status,

    -- REVIEW STATUS (explicit & honest)
    CASE
        WHEN pr.merged = true THEN 'APPROVED_AND_MERGED'
        WHEN pr.state = 'closed' AND pr.merged = false THEN 'CLOSED_WITHOUT_MERGE'
        WHEN jsonb_array_length(
                 COALESCE(pr.raw->'pull_request'->'requested_reviewers', '[]'::jsonb)
             ) = 0 THEN 'NOT_REQUESTED'
        ELSE 'PENDING_REVIEW'
    END AS review_status

FROM pull_requests pr
ORDER BY pr.timestamp DESC
LIMIT 20;



""")


        rows = cur.fetchall()
        recent_pull_requests = rows_to_dicts(cur, rows)


        cur.close()
        conn.close()

        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": f"Hello {user_email}, you have access.",
                "user_role": user_role,
                "user_record": user_record,
                "recent_commits": recent_commits,
                "recent_pull_requests": recent_pull_requests
            }, default=str,indent=2)
        }

    except Exception as e:
        print("Error:", str(e))
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
