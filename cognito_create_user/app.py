import json
import boto3
import os
from datetime import datetime, date
import psycopg2
import uuid

cognito = boto3.client("cognito-idp")
USER_POOL_ID = os.environ["USER_POOL_ID"]

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

# -------------------------------
# Custom Serializer for DateTime
# -------------------------------
class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.strftime('%Y-%m-%d %H:%M:%S')
        return super().default(obj)


def lambda_handler(event, context):
    try:
        body = json.loads(event.get("body", "{}"))

        email = body.get("email")
        password = body.get("password")
        role = body.get("role")  # new
        org_id = body.get("org_id")  # optional org_id

        if not email or not password or not role:
            return {
                "statusCode": 400,
                "body": json.dumps(
                    {"error": "email, password and role are required"},
                    cls=DateTimeEncoder
                )
            }

        # Allowed roles
        allowed_roles = ["DEV", "QA", "MANAGER", "DEV_MANAGER"]
        if role not in allowed_roles:
            return {
                "statusCode": 400,
                "body": json.dumps(
                    {"error": f"Invalid role. Allowed: {allowed_roles}"},
                    cls=DateTimeEncoder
                )
            }

        # ----------------------------
        # 1️⃣ Create Cognito User
        # ----------------------------
        response = cognito.admin_create_user(
            UserPoolId=USER_POOL_ID,
            Username=email,
            UserAttributes=[
                {"Name": "email", "Value": email},
                {"Name": "email_verified", "Value": "true"},
                {"Name": "custom:role", "Value": role}
            ],
            MessageAction="SUPPRESS"
        )

        # ----------------------------
        # 2️⃣ Set permanent password
        # ----------------------------
        cognito.admin_set_user_password(
            UserPoolId=USER_POOL_ID,
            Username=email,
            Password=password,
            Permanent=True
        )

        # ----------------------------
        # 3️⃣ Assign user to role group
        # ----------------------------
        cognito.admin_add_user_to_group(
            UserPoolId=USER_POOL_ID,
            Username=email,
            GroupName=role
        )

        # ----------------------------
        # 4️⃣ Insert user into PostgreSQL users table
        # ----------------------------
        conn = None
        cur = None
        try:
            conn = get_connection()
            cur = conn.cursor()
            insert_sql = """
                INSERT INTO users (
                    id, org_id, email, display_name, sso_id, role, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """
            user_id = str(uuid.uuid4())
            display_name = email.split("@")[0]  # optional: derive display name
            sso_id = None  # assuming SSO id is None initially
            created_at = datetime.utcnow()

            cur.execute(insert_sql, (
                user_id,
                org_id,
                email,
                display_name,
                sso_id,
                role,
                created_at
            ))
            conn.commit()
        except Exception as db_e:
            print("DB Insert Error:", str(db_e))
            return {
                "statusCode": 500,
                "body": json.dumps(
                    {"error": f"Cognito created but failed to insert user in DB: {str(db_e)}"},
                    cls=DateTimeEncoder
                )
            }
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "message": "User created, assigned to role, and saved in DB successfully",
                    "assigned_role": role,
                    "user": response
                },
                cls=DateTimeEncoder
            )
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)}, cls=DateTimeEncoder)
        }
