import json
import hmac
import hashlib
import os
import base64
import uuid
from datetime import datetime
import psycopg2
import psycopg2.extras
import boto3

def notify_and_broadcast(*, notification_args, ws_payload):
    try:
        insert_notification(**notification_args)
    except Exception as e:
        print("Notification failed:", e)

    try:
        broadcast_to_all(ws_payload)
    except Exception as e:
        print("WebSocket broadcast failed:", e)


def insert_notification(
    *,
    source,
    event_name,
    action=None,
    org_id=None,
    project_id=None,
    project_name=None,
    board_id=None,
    board_name=None,
    entity_type=None,
    entity_id=None,
    entity_key=None,
    parent_entity_id=None,
    actor_email=None,
    actor_login=None,
    title=None,
    message,
    extra=None,
    raw
):
    try:
        conn = get_connection()
        cur = conn.cursor()

        sql = """
            INSERT INTO notifications (
                source,
                event_name,
                action,
                org_id,
                project_id,
                project_name,
                board_id,
                board_name,
                entity_type,
                entity_id,
                entity_key,
                parent_entity_id,
                actor_login,
                actor_email,
                title,
                message,
                extra,
                raw
            )
            VALUES (
                %s, %s, %s,
                %s, %s, %s,
                %s, %s,
                %s, %s, %s, %s,
                %s, %s,
                %s, %s,
                %s, %s
            )
            ON CONFLICT (source, event_name, entity_id, action)
            DO NOTHING
        """

        cur.execute(sql, (
            source,
            event_name,
            action,
            org_id,
            project_id,
            project_name,
            board_id,
            board_name,
            entity_type,
            entity_id,
            entity_key,
            parent_entity_id,
            actor_login,
            actor_email,
            title,
            message,
            json.dumps(extra) if extra else None,
            json.dumps(raw)
        ))

        conn.commit()
        cur.close()
        conn.close()

    except Exception as e:
        print("❌ Notification insert failed:", str(e))


# ==========================================================
# 1. PostgreSQL Connection.     
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


def send_ws_message(connection_id, data):
    """
    Send JSON message to a specific WebSocket connection via API Gateway
    """
    ws_client = boto3.client("apigatewaymanagementapi",
                             endpoint_url="https://7mbg70wjz8.execute-api.us-east-1.amazonaws.com/prod/")  # e.g., https://<id>.execute-api.us-east-1.amazonaws.com/prod
    try:
        ws_client.post_to_connection(
            ConnectionId=connection_id,
            Data=json.dumps(data).encode("utf-8")
        )
        print(f"Sent message to connection {connection_id}")
    except ws_client.exceptions.GoneException:
        print(f"Connection {connection_id} no longer exists")
    except Exception as e:
        print(f"Error sending WS message: {str(e)}")

def broadcast_to_all(payload):
    """
    Fetch all connection IDs and send the payload to each.
    """
    print("broadcast_to_all==>")
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT connection_id FROM websocket_connections")
        rows = cur.fetchall()
        for (connection_id,) in rows:
            send_ws_message(connection_id, payload)
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error broadcasting WS event: {str(e)}")
# ==========================================================
# 2. GitHub Signature Validation
# ==========================================================
def verify_signature(event_body, headers):
    secret = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
    signature = headers.get("x-hub-signature-256", "")

    if not signature:
        print("❌ Missing signature header x-hub-signature-256")
        return False

    mac = hmac.new(secret.encode(), msg=event_body.encode(), digestmod=hashlib.sha256)
    expected = f"sha256={mac.hexdigest()}"
    print("Expected signature:", expected)
    print("Received signature:", signature)
    return hmac.compare_digest(expected, signature)

# ==========================================================
# 3. Lambda Handler with Upserts
# ==========================================================
def lambda_handler(event, context):
    headers = {k.lower(): v for k, v in event.get("headers", {}).items()}
    body = event.get("body", "")
    if event.get("isBase64Encoded", False):
        body = base64.b64decode(body).decode("utf-8")

    print("Body preview:", body[:300])
    if not verify_signature(body, headers):
        return {"statusCode": 401, "body": json.dumps({"error": "Invalid GitHub signature"})}

    github_event = headers.get("x-github-event", "unknown")
    print("GitHub Event:", github_event)
    payload = json.loads(body)

    try:
        conn = get_connection()
        cur = conn.cursor()

        try:
            repo = payload["repository"]["full_name"]
            timestamp = datetime.utcnow()

            # Helper function to upsert
            def upsert_record(github_id, author_email, message, commit_sha=None, files=[]):
                event_uuid = str(uuid.uuid4())
                sql = """
                    INSERT INTO github_events
                    (id, github_id, repo, commit_sha, author_email, message, files, timestamp, raw)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (github_id, repo)
                    DO UPDATE SET
                        commit_sha = EXCLUDED.commit_sha,
                        author_email = EXCLUDED.author_email,
                        message = EXCLUDED.message,
                        files = EXCLUDED.files,
                        timestamp = EXCLUDED.timestamp,
                        raw = EXCLUDED.raw
                """
                cur.execute(sql, (
                    event_uuid,
                    github_id,
                    repo,
                    commit_sha,
                    author_email,
                    message,
                    json.dumps(files),
                    timestamp,
                    json.dumps(payload)
                ))


            if github_event == "push":
                print("push===>")
                for c in payload.get("commits", []):
                    commit_id = str(uuid.uuid4())
                    commit_sha = c["id"]
                    author_email = c["author"]["email"]
                    author_user_id = c["author"].get("id")
                    message = c["message"]
                    files = c.get("modified", []) + c.get("added", []) + c.get("removed", [])
                    timestamp = datetime.utcnow()

                    sql = """
                        INSERT INTO git_commits
                        (id, repo, commit_sha, author_email, author_user_id, message, files, timestamp)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (commit_sha, repo) DO NOTHING
                    """
                    cur.execute(sql, (
                        commit_id,
                        repo,
                        commit_sha,
                        author_email,
                        author_user_id,
                        message,
                        files,
                        timestamp
                    ))

                # 🔔 Broadcast commit event to all websocket connections
                payload_ws = {
                    "event": "github:push",
                    "repo": repo,
                    "commit_sha": commit_sha,
                    "message": message,
                    "author_email": author_email,
                    "files": files,
                    "timestamp": timestamp.isoformat(),
                    "raw": c
                }

                broadcast_to_all(payload_ws)
                notify_and_broadcast(
                    notification_args={
                        "source": "github",
                        "event_name": "github:push",
                        "action": "push",
                        "entity_type": "commit",
                        "entity_id": commit_sha,
                        "actor_email": author_email,
                        "title": f"Push to {repo}",
                        "message": message,
                        "extra": {"files": files},
                        "raw": payload
                    },
                    ws_payload=payload_ws
                )

            elif github_event == "pull_request":
                pr = payload["pull_request"]
                github_id = pr["id"]
                pr_number = pr["number"]
                author_login = pr["user"]["login"]
                title = pr["title"]
                action = payload["action"]
                state = pr["state"]
                head_sha = pr["head"]["sha"]
                merged = pr.get("merged", False)
                timestamp = datetime.utcnow()

                event_uuid = str(uuid.uuid4())
                sql = """
                    INSERT INTO pull_requests
                    (id, github_id, repo, pr_number, title, action, state, author_login, head_sha, merged, timestamp, raw)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (github_id, repo)
                    DO UPDATE SET
                        pr_number = EXCLUDED.pr_number,
                        title = EXCLUDED.title,
                        action = EXCLUDED.action,
                        state = EXCLUDED.state,
                        author_login = EXCLUDED.author_login,
                        head_sha = EXCLUDED.head_sha,
                        merged = EXCLUDED.merged,
                        timestamp = EXCLUDED.timestamp,
                        raw = EXCLUDED.raw
                """
                cur.execute(sql, (
                    event_uuid,
                    github_id,
                    repo,
                    pr_number,
                    title,
                    action,
                    state,
                    author_login,
                    head_sha,
                    merged,
                    timestamp,
                    json.dumps(pr)
                ))

                print("Pull request upserted successfully.")

                # 🔔 Broadcast PR event to all websocket connections
                payload_ws = {
                    "event": "github:pull_request",
                    "repo": repo,
                    "pr_number": pr_number,
                    "title": title,
                    "action": action,
                    "state": state,
                    "author": author_login,
                    "merged": merged,
                    "head_sha": head_sha,
                    "timestamp": timestamp.isoformat(),
                    "raw": pr
                }

                broadcast_to_all(payload_ws)
                notify_and_broadcast(
                    notification_args={
                        "source": "github",
                        "event_name": "github:pull_request",
                        "action": action,
                        "entity_type": "pull_request",
                        "entity_id":str(pr_number),
                        "actor_login": author_login,
                        "title": f"PR {action}: {title}",
                        "message": f"PR #{pr_number} is {state}",
                        "extra": {"merged": merged, "head_sha": head_sha},
                        "raw": pr
                    },
                    ws_payload=payload_ws
                )



            elif github_event == "issues":
                issue = payload["issue"]
                github_id = issue["id"]
                issue_number = issue["number"]
                title = issue["title"]
                body_text = issue.get("body", "")
                action = payload["action"]
                state = issue["state"]
                author_login = issue["user"]["login"]
                timestamp = datetime.utcnow()
                event_uuid = str(uuid.uuid4())

                sql = """
                    INSERT INTO issues
                    (id, github_id, repo, issue_number, title, body, action, state, author_login, timestamp, raw)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (github_id, repo)
                    DO UPDATE SET
                        issue_number = EXCLUDED.issue_number,
                        title = EXCLUDED.title,
                        body = EXCLUDED.body,
                        action = EXCLUDED.action,
                        state = EXCLUDED.state,
                        author_login = EXCLUDED.author_login,
                        timestamp = EXCLUDED.timestamp,
                        raw = EXCLUDED.raw
                """
                cur.execute(sql, (
                    event_uuid,
                    github_id,
                    repo,
                    issue_number,
                    title,
                    body_text,
                    action,
                    state,
                    author_login,
                    timestamp,
                    json.dumps(issue)
                ))

                print("Issue upserted successfully.")

                payload_ws = {
                    "event": "github:issue",
                    "source": "github",
                    "repo": repo,
                    "issue_number": issue_number,
                    "title": title,
                    "action": action,
                    "state": state,
                    "author": author_login,
                    "timestamp": timestamp.isoformat()
                }

                notify_and_broadcast(
                    notification_args={
                        "source": "github",
                        "event_name": "github:issue",
                        "action": action,
                        "entity_type": "issue",
                        "entity_id":str(pr_number),
                        "actor_login": author_login,
                        "title": f"Issue {action}: {title}",
                        "message": body_text,
                        "raw": issue
                    },
                    ws_payload=payload_ws
                )



            elif github_event == "issue_comment":
                print("issue_comment===>")
                comment = payload["comment"]
                github_id = comment["id"]
                issue_number = payload["issue"]["number"]
                comment_body = comment.get("body", "")
                action = payload["action"]
                author_login = comment["user"]["login"]
                timestamp = datetime.utcnow()
                event_uuid = str(uuid.uuid4())

                sql = """
                    INSERT INTO issue_comments
                    (id, github_id, repo, issue_number, comment_body, action, author_login, timestamp, raw)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (github_id, repo)
                    DO UPDATE SET
                        issue_number = EXCLUDED.issue_number,
                        comment_body = EXCLUDED.comment_body,
                        action = EXCLUDED.action,
                        author_login = EXCLUDED.author_login,
                        timestamp = EXCLUDED.timestamp,
                        raw = EXCLUDED.raw
                """
                cur.execute(sql, (
                    event_uuid,
                    github_id,
                    repo,
                    issue_number,
                    comment_body,
                    action,
                    author_login,
                    timestamp,
                    json.dumps(comment)
                ))

                print("Issue comment upserted successfully.")


            elif github_event == "issue_comment":
                comment = payload["comment"]
                github_id = comment["id"]
                author_email = comment["user"]["login"]
                message = f"Comment {payload['action']}: {comment['body']}"
                upsert_record(github_id, author_email, message)

            elif github_event == "workflow_run":
                run = payload["workflow_run"]
                github_id = run["id"]
                author_email = run["head_repository"]["owner"]["login"]
                message = f"Workflow run {run['name']} → {run['status']} / {run.get('conclusion')}"
                # upsert_record(github_id, author_email, message, commit_sha=run.get("head_sha"))

            elif github_event == "workflow_job":
                job = payload["workflow_job"]
                github_id = job["id"]
                author_email = job["run_url"]
                message = f"Workflow job {job['name']} → {job['status']} / {job.get('conclusion')}"
                upsert_record(github_id, author_email, message, commit_sha=job.get("head_sha"))

            elif github_event == "release":
                release = payload["release"]
                github_id = release["id"]
                author_email = release["author"]["login"]
                message = f"Release {release['tag_name']} → {payload['action']}"
                upsert_record(github_id, author_email, message)

            elif github_event == "star":
                star = payload
                github_id = star["sender"]["id"]
                author_email = star["sender"]["login"]
                message = f"Repo starred → {payload['action']}"
                upsert_record(github_id, author_email, message)

            elif github_event == "fork":
                fork = payload["forkee"]
                github_id = fork["id"]
                author_email = fork["owner"]["login"]
                message = f"Repo forked → {payload['action']}"
                upsert_record(github_id, author_email, message)

            else:
                print("Unhandled GitHub event:", github_event)

        except Exception as event_error:
            print(f"Error processing {github_event} event:", str(event_error))

        finally:
            conn.commit()
            cur.close()
            conn.close()

    except Exception as e:
        print("Error handling event:", str(e))
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}

    return {"statusCode": 200, "body": json.dumps({"message": f"Received {github_event}"})}
