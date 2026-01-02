import json
import pymysql
import os
import boto3
from datetime import datetime
from twilio.rest import Client

import re

import base64
from urllib.parse import parse_qs
import psycopg2
import psycopg2.extras


def get_connection():
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        dbname=os.environ["DB_NAME"],
        port=5432
    )


#dev
"https://pkqvk1zye7.execute-api.us-east-1.amazonaws.com/prod/"

websocket_url = os.environ.get("WEBSOCKET_URL")

gatewayapi = boto3.client(
    "apigatewaymanagementapi",
    endpoint_url="https://7mbg70wjz8.execute-api.us-east-1.amazonaws.com/prod/"
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


def get_sender_id_from_phone(author_number, cursor):
    """
    First match phone number with lead table.
    If not found, match with user table.
    Return the sender_id (lead_id or user_id) or None.
    """

    if not author_number:
        return None

    # 1. Check leads table
    cursor.execute(
        f"""
        
        SELECT id,name FROM leads
        WHERE phone = %s
        LIMIT 1
        """,
        (author_number)
    )
    lead = cursor.fetchone()

    if lead:
        return lead["id"]  # sender is a lead

    # 2. Check user table
    cursor.execute(
        f"""
        SELECT id,name FROM user
        WHERE phone = %s
        LIMIT 1
        """,
        (author_number,)
    )
    user = cursor.fetchone()

    if user:
        return user["name"]  # sender is a user (agent)

    # 3. Nothing matched
    return None


def json_serializer(obj):
    """Convert datetime/date objects to ISO format."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")

def send_websocket_message(connection_id, response):
    try:
        gatewayapi.post_to_connection(
            ConnectionId=connection_id,
            Data=json.dumps(response, default=json_serializer)
        )
    except Exception as e:
        print(f"Failed to send WebSocket message to {connection_id}: {e}")
        if "GoneException" in str(e):
            conn = get_connection()
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
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            cursor.execute(
                "SELECT connection_id FROM websocket_connections WHERE conversation_id = %s", 
                (conversation_id,)
            )
            rows = cursor.fetchall()
            for row in rows:
                cid = row["connection_id"]
                try:
                    gatewayapi.post_to_connection(
                        ConnectionId=cid,
                        Data=json.dumps(event_data, default=json_serializer)
                    )
                except Exception as e:
                    print(f"Failed to broadcast to {cid}: {e}")
                    cursor.execute(
                        "DELETE FROM websocket_connections WHERE connection_id = %s",
                        (cid,)
                    )
                    conn.commit()
                    CONNECTIONS.pop(cid, None)
    finally:
        conn.close()



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

        # persist connection -> conversation mapping in DB (PostgreSQL syntax)
        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO websocket_connections (connection_id, conversation_id)
                    VALUES (%s, %s)
                    ON CONFLICT (connection_id) 
                    DO UPDATE SET conversation_id = EXCLUDED.conversation_id
                """, (connection_id, conversation_id))
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





# Make sure this global dictionary exists somewhere in your code
# CONNECTIONS = {}

def handle_disconnect(event):
    connection_id = event["requestContext"]["connectionId"]
    
    # Remove from in-memory CONNECTIONS
    if connection_id in CONNECTIONS:
        del CONNECTIONS[connection_id]
        print(f"Removed {connection_id} from CONNECTIONS. Remaining: {len(CONNECTIONS)}")
    
    # Remove from database
    connection = get_connection()
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





def reset_conversation_unread(event, conversation_id):
    try:
        # print("reset_conversation_unread", connection_id)
        # body = json.loads(event["body"]) if "body" in event else {}
        body = event.get("body", {})
        if isinstance(body, str):
            body = json.loads(body)

        # Support both structures: top-level or nested under "body"
        inner_body = body.get("body", body)

        from_no = inner_body.get("from_no")
        to_no = inner_body.get("to_no")

        conversation_id = find_or_create_conversation(from_no, to_no)
        print("from_no===>", from_no)
        print("to_no===>", to_no)

        # conversation_id = body.get("conversationId")
        connection_id = event["requestContext"]["connectionId"]
        print("connection_id", connection_id)

        if not conversation_id:
            response = {"error": "Missing conversationId"}
            send_websocket_message(connection_id, response)
            return {"statusCode": 400, "body": json.dumps(response)}

        connection = get_connection()
        with connection.cursor() as cursor:
            # Reset unread count
            print("conversation_id--123-->", conversation_id)
            cursor.execute("""
                UPDATE conversations SET unread_count = 0 WHERE id = %s
            """, (conversation_id,))
            connection.commit()

            # Fetch updated count
            cursor.execute("SELECT unread_count FROM conversations WHERE id = %s", (conversation_id,))
            result = cursor.fetchone()

        connection.close()

        response_data = {
            "event": "resetConversationUnread",
            "conversationId": conversation_id,
            "from_no":from_no,
            "to_no":to_no,
            "unreadCount": result["unread_count"]
        }
        # Respond to the sender who triggered the reset
        send_websocket_message(connection_id, response_data)
        # Send to all clients connected to this conversation
        broadcast_to_all_clients(conversation_id, response_data)
        return {"statusCode": 200, "body": json.dumps({"message": "Unread count reset"})}

    except Exception as e:
        error_response = {"error": str(e), "type": type(e).__name__}
        send_websocket_message(connection_id, error_response)
        return {"statusCode": 500, "body": json.dumps(error_response)}




def is_valid_phone(number):
    """Validate phone numbers (basic check)."""
    if not number:
        return False

    number = number.strip()

    # Reject empty / undefined-like values
    if number in ["", "null", "undefined", None]:
        return False

    # Allow digits and leading +
    if not re.match(r"^\+?\d{10,15}$", number):
        return False

    return True


def find_or_create_conversation(from_no, to_no):
    if not from_no or not to_no or not re.match(r"^\+?\d{10,15}$", from_no) or not re.match(r"^\+?\d{10,15}$", to_no):
        return None

    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            cursor.execute(
                """
                SELECT id FROM conversations
                WHERE (from_no=%s AND to_no=%s) OR (from_no=%s AND to_no=%s)
                LIMIT 1
                """,
                (from_no, to_no, to_no, from_no)
            )
            conv = cursor.fetchone()
            if conv:
                return conv["id"]
            # create conversation
            cursor.execute(
                "INSERT INTO conversations (from_no, to_no, created_at) VALUES (%s, %s, NOW()) RETURNING id",
                (from_no, to_no)
            )
            conversation_id = cursor.fetchone()["id"]
            conn.commit()
            return conversation_id
    finally:
        conn.close()

def send_sms(event, connection_id):
    try:
        print("Raw event:--->", event)
        print("connection_id:====>", connection_id)
        body = json.loads(event["body"]) if "body" in event else {}

        required_fields = ["from_no", "to_no", "body"]
        if not all(field in body for field in required_fields):
            response = {"error": "Missing required fields"}
            send_websocket_message(connection_id, response)
            return {"statusCode": 400, "body": json.dumps(response)}

        from_no = body["from_no"]
        to_no = body["to_no"]
        message_body = body["body"]

        # Twilio client setup
        account_sid = os.environ.get('TWILIO_ACCOUNT_SID')
        auth_token = os.environ.get('TWILIO_AUTH_TOKEN')
        client = Client(account_sid, auth_token)

        # ✅ Send message and include a status callback URL
        message = client.messages.create(
            body=message_body,
            from_=from_no,
            to=to_no,
            status_callback=twilio_callback_url
        )

        print(f"[Twilio] Sent message SID: {message.sid}, initial status: {message.status}")

        # Get or create conversation
        conversation_id = find_or_create_conversation(from_no, to_no)
        cursor = connection.cursor(pymysql.cursors.DictCursor)

        author_name = get_sender_id_from_phone(from_no, cursor)

        # ✅ Store message with SID and initial status
        connection = get_connection()
        with connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO messages (conversation_id, body, status,author_name, messages_service_id, created_at)
                VALUES (%s, %s,%s, %s, %s, NOW())
            """, (conversation_id, message_body, message.status,author_name, message.sid))
            connection.commit()
        connection.close()

        # Send back acknowledgment via WebSocket
        response_data = {
            "event": "sms_sent",
            "conversationId": conversation_id,
            "from_no": from_no,
            "to_no": to_no,
            "message": message_body,
            "status": message.status,
            "author_name":author_name
        }
        send_websocket_message(connection_id, response_data)

        # ✅ Broadcast to all connected clients in that conversation
        #(if want to broadcast to all the connections[like wtsapp])
        # event_data = {
        #     "event": "new_message",
        #     "message": {
        #         "conversationId": conversation_id,
        #         "from_no": from_no,
        #         "to_no": to_no,
        #         "body": message_body,
        #         "status": message.status,
        #     }
        # }
        # broadcast_message(conversation_id, event_data)

        return {"statusCode": 200, "body": json.dumps({"message": "SMS sent successfully"})}

    except Exception as e:
        print(f"[ERROR] Twilio SMS failed: {e}")
        error_response = {"error": str(e), "type": type(e).__name__}
        send_websocket_message(connection_id, error_response)
        return {"statusCode": 500, "body": json.dumps(error_response)}

def handle_incoming_sms(event, context):
    """Handle incoming SMS from Twilio and broadcast to the right clients"""
    from urllib.parse import parse_qs
    data = parse_qs(event.get("body", ""))
    print("Incoming SMS:", data)

    from_no = data.get("From", [""])[0]
    to_no = data.get("To", [""])[0]
    body = data.get("Body", [""])[0]

    if not from_no or not to_no or not body:
        return {"statusCode": 400, "body": "Missing fields"}

    # Find or create conversation
    conversation_id = find_or_create_conversation(from_no, to_no)

    # Insert into DB
    connection = get_connection()
    with connection.cursor(pymysql.cursors.DictCursor) as cursor:
        cursor.execute("""
            INSERT INTO messages (conversation_id, body, author, status, created_at)
            VALUES (%s, %s, %s, %s, NOW())
        """, (conversation_id, body, from_no, "received"))
        connection.commit()
        message_id = cursor.lastrowid
    connection.close()

    # Prepare message for WebSocket broadcast
    event_data = {
        "event": "new_message",
        "message": {
            "id": message_id,
            "conversationId": conversation_id,
            "from_no": from_no,
            "to_no": to_no,
            "body": body,
            "status": "received"
        }
    }

    # Send to all connected WebSocket clients in this conversation
    broadcast_message(conversation_id, event_data)

    return {"statusCode": 200, "body": "Inbound SMS processed"}



def handle_send_message(event):
    connection_id = event["requestContext"]["connectionId"]
    print("handle_send_message==>")

    try:
        body = json.loads(event.get("body", "{}"))
        from_no = body.get("from_no")
        to_no = body.get("to_no")
        message_body = body.get("body") or body.get("message")
        use_twilio = body.get("twilio", True)
        use_twilio =  True

        if not from_no or not to_no or not message_body:
            response = {"error": "Missing from_no, to_no, or body"}
            send_websocket_message(connection_id, response)
            return {"statusCode": 400, "body": json.dumps(response)}

        # Create or find conversation
        conversation_id = find_or_create_conversation(from_no, to_no)
        print("conversation_id==>", conversation_id)

        

        # Step 1: Insert a record with "sending" status and increment unread_count
        connection = get_connection()
        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            # Insert message
            # cursor.execute(
            #     """
            #     INSERT INTO messages (conversation_id, body, status, created_at)
            #     VALUES (%s, %s, %s, NOW())
            #     """,
            #     (conversation_id, message_body, "sending"),
            # )
            # message_id = cursor.lastrowid

            author_name = get_sender_id_from_phone(from_no, cursor)
            print("sender_id==>",author_name)

            cursor.execute(
                """
                INSERT INTO messages (conversation_id, body, status, author,author_name, created_at)
                VALUES (%s, %s, %s, %s,%s, NOW())
                """,
                (conversation_id, message_body, "sending", from_no,author_name),  # sender_id can be obtained from body if needed
            )
            message_id = cursor.lastrowid

            # Increment unread count
            cursor.execute("""
                UPDATE conversations
                SET unread_count = unread_count + 1
                WHERE id = %s
            """, (conversation_id,))

            # Fetch updated conversation for broadcasting
            cursor.execute("SELECT * FROM conversations WHERE id = %s", (conversation_id,))
            updated_conversation = cursor.fetchone()

            connection.commit()
        connection.close()

        message_service_id = None
        message_status = "sent"

        # Step 2: Send SMS via Twilio
        print("use_twilio-->",use_twilio)
        if use_twilio:
            print("use_twilio-->")
            try:
                account_sid = os.environ.get('TWILIO_ACCOUNT_SID')
                auth_token = os.environ.get('TWILIO_AUTH_TOKEN')
                client = Client(account_sid, auth_token)
                print("use_twilio_account_sid-->",account_sid)
                print("use_twilio_auth_token-->",auth_token)
                message = client.messages.create(
                    body=message_body,
                    from_=from_no,
                    to=to_no,
                    status_callback=twilio_callback_url
                )
                message_service_id = message.sid
                message_status = message.status

            except Exception as twilio_error:
                print(f"[Twilio Error] {twilio_error}")
                message_status = "failed"

        # Step 3: Update message record with SID + status
        connection = get_connection()
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE messages
                SET messages_service_id = %s,
                    status = %s,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (message_service_id, message_status, message_id),
            )
            connection.commit()
        connection.close()

        # Step 4: Broadcast new message
        event_data = {
            "event": "new_message",
            "message": {
                "id": message_id,
                "conversationId": conversation_id,
                "from_no": from_no,
                "to_no": to_no,
                "body": message_body,
                "status": message_status,
            },
        }
        broadcast_message(conversation_id, event_data)

        # Step 5: Broadcast updated conversation to reflect new unread_count
        broadcast_to_all_clients(conversation_id, {
            "event": "conversation_updated",
            "conversation": updated_conversation
        })

        # Step 6: Send response to sender
        response = {
            "message": "Message sent",
            "status": message_status,
            "sid": message_service_id,
        }
        send_websocket_message(connection_id, response)
        return {"statusCode": 200, "body": json.dumps(response)}

    except Exception as e:
        error_response = {"error": str(e), "type": type(e).__name__}
        print(f"[Error] {error_response}")
        send_websocket_message(connection_id, error_response)
        return {"statusCode": 500, "body": json.dumps(error_response)}

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
        connection = get_connection()
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
    try:
        print("Raw event:", event)
        body = json.loads(event["body"]) if "body" in event else {}
        from_no = body.get("from_no")
        to_no = body.get("to_no")

        if not from_no or not to_no:
            response = {"error": "Missing from_no or to_no"}
            send_websocket_message(connection_id, response)
            return {"statusCode": 400, "body": json.dumps(response)}

        connection = get_connection()
        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            # Step 1: find conversation
            cursor.execute(
                "SELECT id FROM conversations WHERE (from_no=%s AND to_no=%s) OR (from_no=%s AND to_no=%s) LIMIT 1",
                (from_no, to_no, to_no, from_no)
            )
            conv = cursor.fetchone()
            if not conv:
                response = {"error": "Conversation not found"}
                send_websocket_message(connection_id, response)
                return {"statusCode": 404, "body": json.dumps(response)}

            conversation_id = conv["id"]

            # Step 2: fetch messages for that conversation
            cursor.execute(
                "SELECT * FROM messages WHERE conversation_id=%s ORDER BY created_at ASC",
                (conversation_id,)
            )
            messages = cursor.fetchall()

        connection.close()

        # Convert datetime objects to ISO format
        for msg in messages:
            for key, value in msg.items():
                if isinstance(value, datetime):
                    msg[key] = value.isoformat()

        response_data = {
            "event": "fetchedMessages",
            "messages": messages
        }
        send_websocket_message(connection_id, response_data)

        return {"statusCode": 200, "body": json.dumps({"message": "Messages sent via WebSocket"})}

    except Exception as e:
        print(f"[ERROR] {type(e).__name__}: {e}")
        error_response = {"error": str(e), "type": type(e).__name__}
        send_websocket_message(connection_id, error_response)
        return {"statusCode": 500, "body": json.dumps(error_response)}


def handle_route1(event, body, connection_id):
    """
    Fetch the last 100 conversations along with related lead details
    and send them via WebSocket to the client
    """
    try:
        connection = get_connection()
        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            # Fetch last 100 conversations
            cursor.execute("""
                SELECT * 
                FROM conversations
                ORDER BY unread_count DESC, updated_at DESC
                LIMIT 100
            """)
            conversations = cursor.fetchall()

            # For each conversation, fetch the matching lead (based on from_no)
            for conv in conversations:
                from_no = conv.get("from_no")
                to_no = conv.get("to_no")

                cursor.execute("""
                    SELECT id, name, email, phone, address, zipcode, source, nurse_id, showroom_id, dob, gender
                    FROM leads
                    WHERE phone = %s 
                    OR twilio_num = %s
                    OR phone = %s
                    OR twilio_num = %s
                """, (from_no, from_no, to_no, to_no))

                leads = cursor.fetchall()
                conv["lead_details"] = leads if leads else []

        connection.close()

        # Convert datetime fields to ISO strings
        for conv in conversations:
            for key, value in conv.items():
                if isinstance(value, datetime):
                    conv[key] = value.isoformat()
                if isinstance(value, dict):  # handle lead_details datetimes too
                    for k2, v2 in value.items():
                        if isinstance(v2, (datetime, date)):
                            value[k2] = v2.isoformat()

        response_data = {
            "event": "all_conversations",
            "conversations": conversations
        }

        print("Fetch last 100 conversations with lead details ==> ", response_data)

        send_websocket_message(connection_id, response_data)

        return {
            "statusCode": 200,
            "body": json.dumps({"message": "Last 100 conversations with lead details sent"})
        }

    except Exception as e:
        print(f"[ERROR] handle_route1: {e}")
        error_response = {"error": str(e), "type": type(e).__name__}
        send_websocket_message(connection_id, error_response)
        return {"statusCode": 500, "body": json.dumps(error_response)}

def handle_send_sms(event):
    """Handles WebSocket, HTTP API, or Twilio sendMessage events"""
    try:
        body = event.get("body")
        print("body-->", body)

        if not body:
            return {"statusCode": 400, "body": json.dumps({"error": "Empty request body"})}

        if event.get("isBase64Encoded", False):
            body = base64.b64decode(body).decode("utf-8")

        content_type = event.get("headers", {}).get("content-type", "")
        if "application/json" in content_type:
            data = json.loads(body) if isinstance(body, str) else body
        else:
            parsed = parse_qs(body)
            data = {k: v[0] for k, v in parsed.items()}
            if "Body" in data: data["body"] = data.pop("Body")
            if "From" in data: data["from_no"] = data.pop("From")
            if "To" in data: data["to"] = data.pop("To")
            if "SmsSid" in data: data["MessageSid"] = data.get("SmsSid")

        # Set author as sender
        data["author"] = data.get("from_no")

        # Required fields
        required_fields = ["body", "from_no", "to"]
        if not all(field in data for field in required_fields):
            return {"statusCode": 400, "body": json.dumps({"error": "Missing required fields"})}

        # Defaults
        data.setdefault("senderId", 1)
        data.setdefault("internal", False)
        data.setdefault("secure", False)
        data.setdefault("siteId", 1)
        data.setdefault("tempMessageId", None)

        messages_service_id = data.get("MessageSid") or data.get("SmsSid")
        sms_status = "received"

        connection = get_connection()
        with connection.cursor() as cursor:
            # Find conversation ID
            cursor.execute("""
                SELECT id FROM conversations 
                WHERE (from_no=%s AND to_no=%s) OR (from_no=%s AND to_no=%s)
                LIMIT 1
            """, (data["from_no"], data["to"], data["to"], data["from_no"]))
            convo = cursor.fetchone()
            if not convo:
                return {"statusCode": 400, "body": json.dumps({"error": "Conversation not found"})}

            conversation_id = convo["id"]

            # Prevent duplicates using messages_service_id
            cursor.execute("SELECT id FROM messages WHERE messages_service_id=%s", (messages_service_id,))
            existing = cursor.fetchone()
            if existing:
                print("⚠️ Duplicate message, skipping insert")
                message_id = existing["id"]
            else:
                # Insert message
                sql = """
                    INSERT INTO messages 
                    (messages_service_id, body, author, status, conversation_id, sender_id, internal, secure, site_id, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                """
                cursor.execute(sql, (
                    messages_service_id, data["body"], data["author"], sms_status,
                    conversation_id, int(data["senderId"]), data["internal"],
                    data["secure"], int(data["siteId"])
                ))
                connection.commit()
                message_id = cursor.lastrowid

            cursor.execute("UPDATE conversations SET last_message_received_at = NOW() WHERE id=%s", (conversation_id,))
            connection.commit()
        connection.close()

        # Broadcast
        event_data = {
            "event": "new_message",
            "message": {
                "id": message_id,
                "conversationId": conversation_id,
                "body": data["body"],
                "author": data["author"],
                "status": sms_status,
                "createdAt": datetime.now().isoformat(),
                "senderId": data["senderId"],
                "internal": data["internal"],
                "secure": data["secure"],
                "tempMessageId": data["tempMessageId"]
            },
            "timestamp": datetime.now().isoformat()
        }
        try:
            print("broadcast_message(SMS)")
            broadcast_message(conversation_id, event_data)
        except Exception as e:
            print(f"⚠️ Broadcast failed: {e}")

        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": "Processed successfully",
                "messageId": message_id,
                "smsStatus": sms_status,
                "messagesServiceId": messages_service_id,
                "data": event_data
            })
        }

    except Exception as e:
        print(f"❌ Error in handle_send_message: {e}")
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}



def handle_github(event):
    route_key = event.get("requestContext", {}).get("routeKey")
    body = json.loads(event.get("body", "{}"))
    print(f"[GitHub Event] {route_key}: {body}")
    return {"statusCode": 200}

def handle_jira(event):
    route_key = event.get("requestContext", {}).get("routeKey")
    body = json.loads(event.get("body", "{}"))
    print(f"[Jira Event] {route_key}: {body}")
    return {"statusCode": 200}

def lambda_handler(event, context):
    route_key = event.get("requestContext", {}).get("routeKey")
    connection_id = event.get("requestContext", {}).get("connectionId")
    http_info = event.get("requestContext", {}).get("http", {})
    http_method = http_info.get("method")
    path = event.get("rawPath") or event.get("path")

    if route_key:
        # ===== WEBSOCKET ROUTES =====
        if route_key == "$connect":
            return handle_connect(event)

        elif route_key == "$disconnect":
            return handle_disconnect(event)

        # Chat events
        elif route_key in [
            "chat.send", "chat.receive", "chat.history",
            "system.user.online", "system.user.offline", "system.broadcast",
            "sendMessage", "fetchMessages"
        ]:
            print(f"Chat/System Event: {route_key}")
            return handle_github(event)

        # GitHub events
        elif route_key in [
            "github.events", "github.push",
            "github.pullrequest.opened", "github.pullrequest.merged"
        ]:
            print(f"GitHub Event: {route_key}")
            return handle_github(event)

        # Jira events
        elif route_key in [
            "jira.events", "jira.project.updated",
            "jira.issue.created", "jira.issue.updated"
        ]:
            print(f"Jira Event: {route_key}")
            return handle_jira(event)

        else:
            print("Invalid routeKey:", route_key)
            return {"statusCode": 400, "body": json.dumps({"error": "Invalid route"})}

    # ===== HTTP POST ENDPOINTS =====
    elif http_method == "POST" and path == "/conversation":
        print("HTTP POST received — possible Twilio webhook")
        return handle_send_sms(event, context)

    else:
        print("Unknown event:", event)
        return {"statusCode": 400, "body": json.dumps({"error": "Unknown event type"})}
