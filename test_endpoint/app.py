import os
import json
import psycopg2

ALLOWED_ROLES = ["DEV", "QA", "MANAGER", "DEV_MANAGER"]

# ==========================================================
# PostgreSQL Connection
# ==========================================================
def get_connection():
    try:
        conn = psycopg2.connect(
            host=os.environ["DB_HOST"],
            user=os.environ["DB_USER"],
            password=os.environ["DB_PASSWORD"],
            dbname=os.environ["DB_NAME"],
            port=5432
        )
        return conn
    except Exception as e:
        print("DB Connection Error:", str(e))
        raise

def lambda_handler(event, context):
    try:
        # Extract JWT claims
        claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
        user_email = claims.get("email")
        user_role = claims.get("custom:role")  # Cognito custom role
        sub = claims.get("sub")

        print("User Email:", user_email)
        print("User Role:", user_role)
        print("sub:", sub)

        # Role-based access control
        if not user_role or user_role not in ALLOWED_ROLES:
            return {
                "statusCode": 403,
                "body": json.dumps({"error": "Access denied. Your role does not allow access."})
            }

        # Connect to PostgreSQL
        conn = get_connection()
        cur = conn.cursor()

        # Example query: fetch user info
        cur.execute("SELECT id, email, role, created_at FROM users WHERE email=%s", (user_email,))
        user_record = cur.fetchone()

        cur.close()
        conn.close()

        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": f"Hello {user_email}, you have access.",
                "user_role": user_role,
                "user_record": user_record
            }, default=str)
        }

    except Exception as e:
        print("Error:", str(e))
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
