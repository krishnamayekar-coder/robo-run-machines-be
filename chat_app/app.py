
import json
import pymysql
import os
import boto3
from datetime import datetime
from twilio.rest import Client


import commons as cm
import re
#connection = cm.cm.get_connection()
#test commit

import base64
from urllib.parse import parse_qs

# WebSocket API Gateway client
gatewayapi = boto3.client(
    "apigatewaymanagementapi",
    endpoint_url="https://pkqvk1zye7.execute-api.us-east-1.amazonaws.com/prod/"
)

CONNECTIONS = {}

def broadcast_to_all_clients(conversation_id, conversation):
    """
    Send updated conversation only to clients connected to this conversation.
    """
    for connection_id, conv_id in CONNECTIONS.items():
        if conv_id == conversation_id:
            try:
                send_websocket_message(connection_id, {
                    "event": "conversation_updated",
                    "conversation": conversation
                })
            except Exception as e:
                print(f"Failed to send to {connection_id}: {e}")
                CONNECTIONS.pop(connection_id, None)




import json
from datetime import datetime, date


def json_serializer(obj):
    """Convert datetime/date objects to ISO format."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")

def send_websocket_message(connection_id, response):
    print("send_websocket_message:====>", connection_id)
    print("response:====>", response)
    try:
        gatewayapi.post_to_connection(
            ConnectionId=connection_id,
            Data=json.dumps(response, default=json_serializer)
        )
    except Exception as e:
        print(f"Failed to send WebSocket message to {connection_id}: {e}")
        if "GoneException" in str(e):
            conn = cm.get_connection()
            try:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM websocket_connections WHERE connection_id = %s",
                        (connection_id,)
                    )
                    conn.commit()
            finally:
                conn.close()


def broadcast_message(conversation_id, event_data):
    return

# Store active connections per conversation
active_connections = {}  # Dictionary { conversation_id: set(connection_ids) }


# Global dictionary to track connections
# Format: {connection_id: conversation_id} or you can store more info if needed
def handle_connect(event):
    """
    On $connect: use query params from_no & to_no to find/create conversation,
    store the connection mapping both in-memory and in DB so broadcasts work.
    """
    try:
        connection_id = event["requestContext"]["connectionId"]
        query_params = event.get("queryStringParameters", {}) or {}

        # Preferred: frontend sends from_no & to_no in the connect URL
        from_no = query_params.get("from_no")
        to_no = query_params.get("to_no")

        # If user provided conversationId directly, allow that too (backwards compat)
        conversation_id = query_params.get("conversationId")

        if not conversation_id:
            if not from_no or not to_no:
                # still register connection but mark as 'unknown'
                print("handle_connect: missing from_no/to_no and conversationId")
                CONNECTIONS[connection_id] = None
                return {"statusCode": 200, "body": "Connected (no conversation)"}
            # create or find conversation from phone numbers
            conversation_id = find_or_create_conversation(from_no, to_no)

        # store in-memory map
        CONNECTIONS[connection_id] = conversation_id
        print(f"WebSocket connected: {connection_id} for conversation {conversation_id} (from_no={from_no} to_no={to_no})")
        print(f"Total connections: {len(CONNECTIONS)}")

        # persist connection -> conversation mapping in DB (so broadcast_message can query)
        try:
            conn = cm.get_connection()
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO websocket_connections (connection_id, conversation_id) VALUES (%s, %s) "
                    "ON DUPLICATE KEY UPDATE conversation_id = %s",
                    (connection_id, conversation_id, conversation_id)
                )
                conn.commit()
        finally:
            try:
                conn.close()
            except Exception:
                pass

        return {"statusCode": 200, "body": "Connected"}

    except Exception as e:
        print(f"Connection error: {str(e)}")
        return {"statusCode": 400, "body": "Bad Request"}




# ----------------------- JIRA EVENT HANDLERS -----------------------
def handle_jira_issue_created(event, body):
    print("handle_jira_issue_created", body)
    return {"statusCode": 200, "body": "Jira issue.created processed"}


def handle_jira_issue_updated(event, body):
    print("handle_jira_issue_updated", body)
    return {"statusCode": 200, "body": "Jira issue.updated processed"}


def handle_jira_project_updated(event, body):
    print("handle_jira_project_updated", body)
    return {"statusCode": 200, "body": "Jira project.updated processed"}


# ----------------------- GITHUB EVENT HANDLERS -----------------------
def handle_github_push(event, body):
    print("handle_github_push", body)
    return {"statusCode": 200, "body": "GitHub push event processed"}


def handle_github_pr_opened(event, body):
    print("handle_github_pr_opened", body)
    return {"statusCode": 200, "body": "GitHub pullrequest.opened processed"}


def handle_github_pr_merged(event, body):
    print("handle_github_pr_merged", body)
    return {"statusCode": 200, "body": "GitHub pullrequest.merged processed"}


def handle_github_workflow_status(event, body):
    print("handle_github_workflow_status", body)
    return {"statusCode": 200,
            "body": "GitHub workflow.status processed"}


# ----------------------- SYSTEM EVENTS -----------------------
def handle_system_broadcast(event):
    print("system.broadcast", event.get("body"))
    return {"statusCode": 200, "body": "system.broadcast processed"}


def handle_user_online(event):
    print("system.user.online")
    return {"statusCode": 200, "body": "system.user.online processed"}


def handle_user_offline(event):
    print("system.user.offline")
    return {"statusCode": 200, "body": "system.user.offline processed"}


# ----------------------- CHAT EVENTS -----------------------
def chat_send(event, connection_id):
    print("chat.send", event.get("body"))
    return {"statusCode": 200, "body": "chat.send processed"}


def chat_receive(event, connection_id):
    print("chat.receive", event.get("body"))
    return {"statusCode": 200, "body": "chat.receive processed"}


def chat_typing(event, connection_id):
    print("chat.typing")
    return {"statusCode": 200, "body": "chat.typing processed"}


def chat_history(event, connection_id):
    print("chat.history")
    return {"statusCode": 200, "body": "chat.history processed"}


def chat_bot_reply(event):
    print("chat.bot.reply")
    return {"statusCode": 200, "body": "chat.bot.reply processed"}


def chat_user_join(event, connection_id):
    print("chat.user.join")
    return {"statusCode": 200, "body": "chat.user.join processed"}


def chat_user_leave(event, connection_id):
    print("chat.user.leave")
    return {"statusCode": 200, "body": "chat.user.leave processed"}


def chat_presence_update(event):
    print("chat.presence.update")
    return {"statusCode": 200, "body": "chat.presence.update processed"}


def chat_group_send(event):
    print("chat.group.send")
    return {"statusCode": 200, "body": "chat.group.send processed"}


def chat_group_notify(event):
    print("chat.group.notify")
    return {"statusCode": 200, "body": "chat.group.notify processed"}



def handle_incoming_sms(event, context):
    print("handle_incoming_sms")
    return {"statusCode": 200, "body": "incoming_sms processed"}


def twilio_status_callback(event, context):
    print("twilio_status_callback")
    return {"statusCode": 200, "body": "twilio callback processed"}


def find_or_create_conversation(from_no, to_no):
    print("find_or_create_conversation", from_no, to_no)
    return f"{from_no}_{to_no}"   # mock conversationId




# Make sure this global dictionary exists somewhere in your code
# CONNECTIONS = {}

def handle_disconnect(event):
    connection_id = event["requestContext"]["connectionId"]
    
    # Remove from in-memory CONNECTIONS
    if connection_id in CONNECTIONS:
        del CONNECTIONS[connection_id]
        print(f"Removed {connection_id} from CONNECTIONS. Remaining: {len(CONNECTIONS)}")
    
    # Remove from database
    connection = cm.get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM websocket_connections WHERE connection_id = %s",
                (connection_id,)
            )
            connection.commit()
            print(f"Deleted {connection_id} from websocket_connections table")
    finally:
        connection.close()
    
    print(f"WebSocket disconnected: {connection_id}")
    return {"statusCode": 200, "body": "Disconnected"}



def handle_send_message(event):
    return "handle_send_message"


def handle_init(event):
    """Stores WebSocket connection with the given conversationId."""
    try:
        connection_id = event["requestContext"]["connectionId"]
        data = json.loads(event["body"]) if "body" in event else {}
        from_no = data.get("from_no")
        to_no = data.get("to_no")

        if not from_no or not to_no:
            return {"statusCode": 400, "body": json.dumps({"error": "Missing from_no or to_no"})}

        # Retrieve or create conversation ID
        conversation_id = find_or_create_conversation(from_no, to_no)

        if not conversation_id:
            return {"statusCode": 400, "body": json.dumps({"error": "Missing conversationId"})}

        print(f"WebSocket {connection_id} initialized for conversation {conversation_id}")

        # Store connection in DB
        connection = cm.get_connection()
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO websocket_connections (connection_id, conversation_id) VALUES (%s, %s) ON DUPLICATE KEY UPDATE conversation_id = %s",
                (connection_id, conversation_id, conversation_id)
            )
            connection.commit()
        connection.close()

        return {"statusCode": 200, "body": "Initialization successful"}

    except Exception as e:
        print(f"Error handling WebSocket initialization: {e}")
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}


def handle_fetch_messages(event, connection_id):
    return 

def handle_send_sms(event):
    return 'handle_send_sms'




def lambda_handler(event, context):
    request_context = event.get("requestContext", {})
    route_key = request_context.get("routeKey")
    connection_id = request_context.get("connectionId")

    http_info = request_context.get("http", {})
    http_method = http_info.get("method")
    path = event.get("rawPath") or event.get("path")

    # ---------------------------------------------------
    #               WEBSOCKET ROUTES
    # ---------------------------------------------------
    if route_key:

        # ------------------- SYSTEM ROUTES -------------------
        if route_key == "$connect":
            return handle_connect(event)

        elif route_key == "$disconnect":
            return handle_disconnect(event)

        # ---------------------------------------------------
        #               UNIFIED JIRA EVENTS
        # ---------------------------------------------------
        elif route_key == "jira.events":
            print("JIRA EVENT RECEIVED")

            body = event.get("body", "{}")
            if isinstance(body, str):
                body = json.loads(body)

            event_type = body.get("eventType")

            if event_type == "issue.created":
                return handle_jira_issue_created(event, body)

            elif event_type == "issue.updated":
                return handle_jira_issue_updated(event, body)

            elif event_type == "project.updated":
                return handle_jira_project_updated(event, body)

            else:
                print("Unknown JIRA eventType:", event_type)
                return {"statusCode": 400, "body": json.dumps({"error": "Unknown JIRA eventType"})}

        # ---------------------------------------------------
        #               UNIFIED GITHUB EVENTS
        # ---------------------------------------------------
        elif route_key == "github.events":
            print("GITHUB EVENT RECEIVED")

            body = event.get("body", "{}")
            if isinstance(body, str):
                body = json.loads(body)

            event_type = body.get("eventType")

            # GitHub event dispatch table
            if event_type == "push":
                return handle_github_push(event, body)

            elif event_type == "pullrequest.opened":
                return handle_github_pr_opened(event, body)

            elif event_type == "pullrequest.merged":
                return handle_github_pr_merged(event, body)

            elif event_type == "workflow.status":
                return handle_github_workflow_status(event, body)

            else:
                print("Unknown GitHub eventType:", event_type)
                return {"statusCode": 400, "body": json.dumps({"error": "Unknown GitHub eventType"})}

        # ---------------------------------------------------
        #                EXISTING ROUTES
        # ---------------------------------------------------
        elif route_key == "sendMessage":
            return handle_send_message(event)

        elif route_key == "fetchMessages":
            return handle_fetch_messages(event, connection_id)


        # ---------------------- SYSTEM BROADCAST / PRESENCE ----------------------
        elif route_key == "system.broadcast":
            return handle_system_broadcast(event)

        elif route_key == "system.user.online":
            return handle_user_online(event)

        elif route_key == "system.user.offline":
            return handle_user_offline(event)

        # ---------------------- CHAT EVENTS ----------------------
        elif route_key == "chat.send":
            return chat_send(event, connection_id)

        elif route_key == "chat.receive":
            return chat_receive(event, connection_id)

        elif route_key == "chat.typing":
            return chat_typing(event, connection_id)

        elif route_key == "chat.history":
            return chat_history(event, connection_id)

        elif route_key == "chat.bot.reply":
            return chat_bot_reply(event)

        elif route_key == "chat.user.join":
            return chat_user_join(event, connection_id)

        elif route_key == "chat.user.leave":
            return chat_user_leave(event, connection_id)

        elif route_key == "chat.presence.update":
            return chat_presence_update(event)

        elif route_key == "chat.group.send":
            return chat_group_send(event)

        elif route_key == "chat.group.notify":
            return chat_group_notify(event)

        else:
            print("Invalid routeKey:", route_key)
            return {"statusCode": 400, "body": json.dumps({"error": "Invalid route"})}

    else:
        return {"statusCode": 400, "body": json.dumps({"error": "Unknown event type"})}
