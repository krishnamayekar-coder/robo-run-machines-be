import json
import boto3
import os
from datetime import datetime, date
import psycopg2
import psycopg2.extras

cognito = boto3.client("cognito-idp")
USER_POOL_ID = os.environ["USER_POOL_ID"]

ADMIN_ROLES = ["MANAGER", "DEV_MANAGER"]

# ==========================================================
# PostgreSQL Connection
# ==========================================================
def get_connection():
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        dbname=os.environ["DB_NAME"],
        port=5432
    )

# -------------------------------
# Custom Serializer
# -------------------------------
class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        return super().default(obj)

# ==========================================================
# Lambda Handler
# ==========================================================
def lambda_handler(event, context):
    try:
        # ------------------------------
        # Auth / RBAC
        # ------------------------------
        claims = event.get("requestContext", {}) \
                      .get("authorizer", {}) \
                      .get("jwt", {}) \
                      .get("claims", {})

        requester_role = claims.get("custom:role")

        if requester_role not in ADMIN_ROLES:
            return {
                "statusCode": 403,
                "body": json.dumps({"error": "Only managers can view user details"})
            }

        # ------------------------------
        # Input
        # ------------------------------
        email = (
            event.get("queryStringParameters", {}) or {}
        ).get("email")

        if not email:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "email query parameter is required"})
            }

        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # ------------------------------
        # Fetch User + Organization
        # ------------------------------
        cur.execute("""
            SELECT
                u.id,
                u.email,
                u.display_name,
                u.role,
                u.created_at,
                o.id AS org_id,
                o.name AS org_name,
                o.settings AS org_settings
            FROM users u
            LEFT JOIN organizations o ON o.id = u.org_id
            WHERE u.email = %s
        """, (email,))

        user = cur.fetchone()

        if not user:
            return {
                "statusCode": 404,
                "body": json.dumps({"error": "User not found"})
            }

        user_id = user["id"]

        # ------------------------------
        # Fetch Skills
        # ------------------------------
        cur.execute("""
            SELECT
                s.id,
                s.name,
                us.proficiency
            FROM user_skills us
            JOIN skills s ON s.id = us.skill_id
            WHERE us.user_id = %s
            ORDER BY s.name
        """, (user_id,))

        skills = cur.fetchall()

        # ------------------------------
        # Fetch Projects (if used)
        # ------------------------------
        cur.execute("""
            SELECT
                p.id,
                p.name,
                up.assigned_at
            FROM user_projects up
            JOIN projects p ON p.id = up.project_id
            WHERE up.user_id = %s
            ORDER BY p.name
        """, (user_id,))

        projects = cur.fetchall()

        # ------------------------------
        # Fetch Cognito (Read-only)
        # ------------------------------
        cognito_user = None
        try:
            resp = cognito.admin_get_user(
                UserPoolId=USER_POOL_ID,
                Username=email
            )

            cognito_user = {
                "username": resp.get("Username"),
                "enabled": resp.get("Enabled"),
                "user_status": resp.get("UserStatus"),
                "created_at": resp.get("UserCreateDate"),
                "last_modified": resp.get("UserLastModifiedDate")
            }
        except Exception:
            cognito_user = None

        cur.close()
        conn.close()

        # ------------------------------
        # Response
        # ------------------------------
        return {
            "statusCode": 200,
            "body": json.dumps({
                "user": user,
                "skills": skills,
                "projects": projects,
                "cognito": cognito_user
            }, cls=DateTimeEncoder)
        }

    except Exception as e:
        print("ERROR:", str(e))
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)}, cls=DateTimeEncoder)
        }
