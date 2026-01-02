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
    if not email:
        return {
            "statusCode": 400,
            "body": json.dumps({"message": "Email is required"})
        }

    client_id = os.environ.get("APP_CLIENT_ID")  # No secret client
    if not client_id:
        return {
            "statusCode": 500,
            "body": json.dumps({"message": "Missing AppClientId in environment variables"})
        }

    try:
        cognito = boto3.client("cognito-idp")

        # This sends OTP to the user's registered email or phone
        response = cognito.forgot_password(
            ClientId=client_id,
            Username=email
        )

        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": "OTP sent to registered email or phone. Use it to confirm password reset.",
                "delivery_details": response.get("CodeDeliveryDetails", {})
            })
        }

    except cognito.exceptions.UserNotFoundException:
        return {
            "statusCode": 404,
            "body": json.dumps({"message": "User not found"})
        }

    except Exception as e:
        print(f"Error during password reset OTP: {e}")
        print(traceback.format_exc())
        return {
            "statusCode": 500,
            "body": json.dumps({"message": "Failed to initiate password reset", "error": str(e)})
        }
