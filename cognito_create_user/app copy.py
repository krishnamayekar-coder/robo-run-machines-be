import json
import boto3
import os
from datetime import datetime, date
import psycopg2


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

        if not email or not password or not role:
            return {
                "statusCode": 400,
                "body": json.dumps(
                    {"error": "email, password and role are required"}
                )
            }

        # Allowed roles
        allowed_roles = ["DEV", "QA", "MANAGER", "DEV_MANAGER"]
        if role not in allowed_roles:
            return {
                "statusCode": 400,
                "body": json.dumps(
                    {"error": f"Invalid role. Allowed: {allowed_roles}"}
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

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "message": "User created and assigned to role successfully",
                    "assigned_role": role,
                    "user": response
                },
                cls=DateTimeEncoder  # <-- serialize safely
            )
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
