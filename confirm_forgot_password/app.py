import json
import boto3
import os
import traceback

def lambda_handler(event, context):
    print("Received event:", event)

    try:
        body = json.loads(event.get('body', event))
    except Exception as e:
        print("Error parsing event body:", e)
        body = event

    email = body.get("email")
    code = body.get("otp")  
    new_password = body.get("new_password")

    if not email or not code or not new_password:
        return {
            "statusCode": 400,
            "body": json.dumps({"message": "Email, code, and new_password are required"})
        }

    client_id = os.environ.get("APP_CLIENT_ID")  
    if not client_id:
        return {
            "statusCode": 500,
            "body": json.dumps({"message": "Missing AppClientId in environment variables"})
        }

    cognito = boto3.client('cognito-idp')

    try:
        cognito.confirm_forgot_password(
            ClientId=client_id,
            Username=email,
            ConfirmationCode=code,
            Password=new_password
        )

        return {
            "statusCode": 200,
            "body": json.dumps({"message": "Password reset successful"})
        }

    except cognito.exceptions.UserNotFoundException:
        return {
            "statusCode": 404,
            "body": json.dumps({"message": "User not found"})
        }
    except cognito.exceptions.CodeMismatchException:
        return {
            "statusCode": 400,
            "body": json.dumps({"message": "Invalid confirmation code"})
        }
    except cognito.exceptions.ExpiredCodeException:
        return {
            "statusCode": 400,
            "body": json.dumps({"message": "Confirmation code expired"})
        }
    except Exception as e:
        print("Unexpected error:", e)
        print(traceback.format_exc())
        return {
            "statusCode": 500,
            "body": json.dumps({"message": "Failed to reset password", "error": str(e)})
        }
