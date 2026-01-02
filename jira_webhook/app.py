import json
import os
import psycopg2
from datetime import datetime
import uuid


import requests
from requests.auth import HTTPBasicAuth


import boto3

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


def get_board_name(board_id):
    if not board_id:
        return None

    url = f"https://praveenreddygopidi.atlassian.net/rest/agile/1.0/board/{board_id}"
    auth = HTTPBasicAuth(os.environ["JIRA_USER"], os.environ["JIRA_API_TOKEN"])
    headers = {"Accept": "application/json"}

    resp = requests.get(url, headers=headers, auth=auth)
    if resp.status_code == 200:
        return resp.json().get("name")
    else:
        print("Failed to fetch board name for board:", board_id)
        return None


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



def extract_author_email(body, issue=None, comment=None, worklog=None):
    account_id = None

    # 1️⃣ Comment author
    if comment and comment.get("author"):
        account_id = comment["author"].get("accountId")

    # 2️⃣ Worklog author
    elif worklog and worklog.get("author"):
        account_id = worklog["author"].get("accountId")

    # 3️⃣ Generic webhook user
    elif body.get("user"):
        account_id = body["user"].get("accountId")

    # 4️⃣ Fallback: reporter
    elif issue and issue.get("fields", {}).get("reporter"):
        account_id = issue["fields"]["reporter"].get("accountId")

    if not account_id:
        return None

    return get_jira_user_email(account_id)



def get_jira_user_email(account_id):
    url = f"https://praveenreddygopidi.atlassian.net/rest/api/3/user?accountId={account_id}"
    auth = HTTPBasicAuth(os.environ["JIRA_USER"], os.environ["JIRA_API_TOKEN"])

    headers = {"Accept": "application/json"}
    response = requests.get(url, headers=headers, auth=auth)
    if response.status_code == 200:
        return response.json().get("emailAddress")
    else:
        print("Failed to fetch email for", account_id)
        return None

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

# ==========================================================
# Lambda Handler
# ==========================================================
def lambda_handler(event, context):
    print("Raw Event:", json.dumps(event))
    try:
        body = json.loads(event.get("body", "{}"))
        webhook_event = body.get("webhookEvent")
        issue = body.get("issue")
        comment = body.get("comment")
        changelog = body.get("changelog")
        sprint = body.get("sprint")
        worklog = body.get("worklog")

        print("Webhook Event:", webhook_event)

        # ---- ISSUE EVENTS ---- #
        if webhook_event == "jira:issue_created":
            handle_issue_created(issue)
        elif webhook_event == "jira:issue_updated":
            handle_issue_updated(issue, changelog)
        elif webhook_event == "jira:issue_deleted":
            handle_issue_deleted(issue)

        # ---- SPRINT EVENTS ---- #
        elif webhook_event in ["sprint_created", "sprint_updated", "sprint_deleted", "sprint_started", "sprint_closed"]:
            author_login = extract_author_email(body)
            handle_sprint_events(webhook_event, sprint, author_login=author_login)
            

        # ---- COMMENT EVENTS ---- #
        elif webhook_event in ["comment_created", "comment_updated", "comment_deleted"]:
            author_login = extract_author_email(body, issue=issue, comment=comment)
            handle_comment_events(webhook_event, issue, comment, author_login=author_login)
            

        # ---- VOTING/WATCHING ---- #
        elif webhook_event in ["issue_vote_changed", "issue_watch_changed"]:
            handle_vote_watch_events(webhook_event, issue)

        # ---- ISSUE LINKS ---- #
        elif webhook_event in ["issue_link_created", "issue_link_deleted"]:
            author_login = body.get("user", {}).get("displayName")
            handle_issue_links(webhook_event, body, author_login=author_login)


        # ---- SUBTASKS ---- #
        elif webhook_event in ["subtask_created", "subtask_updated", "subtask_deleted"]:
            board_id = body.get("issue", {}).get("originBoardId")  # optional
            issue_data = body.get("issue")
            author_login = body.get("user", {}).get("displayName")
            author_login = extract_author_email(body, issue=issue_data)
            handle_subtask_events(webhook_event, issue_data, board_id=board_id, author_login=author_login)



        # ---- WORKLOG ---- #
        elif webhook_event in ["worklog_created", "worklog_updated", "worklog_deleted"]:
            handle_worklog_events(webhook_event, issue, worklog)

        # ---- TIMETRACKING PROVIDER ---- #
        elif webhook_event == "timetrackingprovider_update":
            handle_timetracking_provider(body)

        # ---- FEATURE TOGGLE ---- #
        elif webhook_event in ["feature_flag_enabled", "feature_flag_disabled"]:
            handle_feature_toggle(webhook_event, body)

        else:
            print("Unhandled event:", webhook_event)

        return {"statusCode": 200, "body": json.dumps({"message": "Webhook received"})}

    except Exception as e:
        print("Error:", str(e))
        return {"statusCode": 500, "body": json.dumps({"error": "Internal server error"})}


# ==========================================================
# ISSUE HANDLERS
# ==========================================================

def handle_issue_created(issue):
    import json
    from datetime import datetime

    print("Issue created:", json.dumps(issue))
    conn = None
    cur = None

    try:
        conn = get_connection()
        cur = conn.cursor()

        fields = issue.get("fields", {})

        # ===============================
        # Story Points (custom field)
        # ===============================
        story_points_field = os.environ.get("STORY_POINTS_FIELD")
        story_points = fields.get(story_points_field) if story_points_field else None

        # ===============================
        # Project info
        # ===============================
        project = fields.get("project", {})
        project_id = project.get("id")
        project_name = project.get("name")

        # ===============================
        # Board info
        # ===============================
        board_id = issue.get("originBoardId")
        board_name = get_board_name(board_id)

        # ===============================
        # Org ID
        # ===============================
        org = fields.get("organization")
        if org and org.get("id"):
            org_id = str(org.get("id"))
        else:
            org_id = str(project_id) if project_id else None

        # ===============================
        # Assignee
        # ===============================
        assignee = fields.get("assignee")
        assignee_id = assignee.get("accountId") if assignee else None
        assignee_name = assignee.get("displayName") if assignee else None
        assignee_email = get_jira_user_email(assignee_id)

        # ===============================
        # Reporter
        # ===============================
        reporter = fields.get("reporter")
        reporter_id = reporter.get("accountId") if reporter else None
        reporter_name = reporter.get("displayName") if reporter else None
        reporter_email = get_jira_user_email(reporter_id)

        # ===============================
        # Other fields
        # ===============================
        status = fields.get("status", {}).get("name")
        priority = fields.get("priority", {}).get("name")
        components = json.dumps(fields.get("components") or [])

        sql = """
            INSERT INTO jira_issues (
                id,
                issue_key,
                org_id,

                project_id,
                project_name,
                board_id,
                board_name,
                story_points,

                assignee_user_id,
                assignee_name,
                assignee_email,

                reporter_user_id,
                reporter_name,
                reporter_email,

                status,
                priority,
                component,
                updated_at,
                raw
            )
            VALUES (
                %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s
            )
            ON CONFLICT (issue_key)
            DO UPDATE SET
                org_id = EXCLUDED.org_id,
                project_id = EXCLUDED.project_id,
                project_name = EXCLUDED.project_name,
                board_id = EXCLUDED.board_id,
                board_name = EXCLUDED.board_name,
                story_points = EXCLUDED.story_points,

                assignee_user_id = EXCLUDED.assignee_user_id,
                assignee_name = EXCLUDED.assignee_name,
                assignee_email = EXCLUDED.assignee_email,

                reporter_user_id = EXCLUDED.reporter_user_id,
                reporter_name = EXCLUDED.reporter_name,
                reporter_email = EXCLUDED.reporter_email,

                status = EXCLUDED.status,
                priority = EXCLUDED.priority,
                component = EXCLUDED.component,
                updated_at = EXCLUDED.updated_at,
                raw = EXCLUDED.raw
        """

        cur.execute(sql, (
            str(issue.get("id")),
            issue.get("key"),
            org_id,

            project_id,
            project_name,
            board_id,
            board_name,
            story_points,

            assignee_id,
            assignee_name,
            assignee_email,

            reporter_id,
            reporter_name,
            reporter_email,

            status,
            priority,
            components,
            datetime.utcnow(),
            json.dumps(issue)
        ))

        conn.commit()
        print(f"Issue {issue.get('key')} created/updated with story points & board info.")

        # 🔔 WebSocket broadcast
        payload = {
            "event": "jira:issue_created",
            "issue_key": issue.get("key"),
            "summary": fields.get("summary"),
            "status": status,
            "story_points": story_points,
            "project": project_name,
            "board": board_name,
            "assignee": assignee_name,
            "reporter": reporter_name
        }
        broadcast_to_all(payload)
        insert_notification(
            source="jira",
            event_name="jira:issue_created",
            action="created",
            org_id=org_id,
            project_id=project_id,
            project_name=project_name,
            board_id=board_id,
            board_name=board_name,
            entity_type="issue",
            entity_id=str(issue.get("id")),
            entity_key=issue.get("key"),
            actor_email=reporter_email,
            title=f"Issue {issue.get('key')} created",
            message=fields.get("summary"),
            extra={
                "status": status,
                "priority": priority,
                "story_points": story_points
            },
            raw=issue
        )


    except Exception as e:
        print("Error in handle_issue_created:", str(e))

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def handle_issue_updated(issue, changelog):
    print("Issue updated:", json.dumps(issue))
    handle_issue_created(issue)  # same logic as create


def handle_issue_deleted(issue):
    print("Issue deleted:", json.dumps(issue))
    try:
        conn = get_connection()
        cur = conn.cursor()
        sql = "DELETE FROM jira_issues WHERE issue_key = %s"
        cur.execute(sql, (issue.get("key"),))
        conn.commit()
        cur.close()
        conn.close()
        print(f"Issue {issue.get('key')} deleted.")
        # 🔔 Broadcast to all websocket connections
        payload = {
            "event": "jira:issue_deleted",
            "issue_key": issue.get("key"),
            "summary": issue.get("fields", {}).get("summary"),
            "status": issue.get("fields", {}).get("status", {}).get("name"),
            "assignee": issue.get("fields", {}).get("assignee", {}).get("displayName")
                if issue.get("fields", {}).get("assignee") else None,
            "reporter": issue.get("fields", {}).get("reporter", {}).get("displayName")
                if issue.get("fields", {}).get("reporter") else None,
            "raw": issue
        }

        broadcast_to_all(payload)
        insert_notification(
            source="jira",
            event_name="jira:issue_deleted",
            action="deleted",
            entity_type="issue",
            entity_id=str(issue.get("id")),
            entity_key=issue.get("key"),
            title=f"Issue {issue.get('key')} deleted",
            message=issue.get("fields", {}).get("summary"),
            raw=issue
        )

    except Exception as e:
        print("Error in handle_issue_deleted:", str(e))


# ==========================================================
# SPRINT HANDLER
# ==========================================================
def handle_sprint_events(event_type, sprint, repo_or_board_id=None, author_login=None):
    try:
        conn = get_connection()
        cur = conn.cursor()

        event_uuid = str(uuid.uuid4())
        timestamp = datetime.utcnow()

        # ===============================
        # Board info
        # ===============================
        board_id = repo_or_board_id or sprint.get("originBoardId")
        board_name = get_board_name(board_id)

        # ===============================
        # Project info (if available)
        # ===============================
        project_id = sprint.get("projectId")
        project_name = sprint.get("projectName")
        org_id = sprint.get("orgId")  # optional, adjust if you track org_id

        # ===============================
        # Ensure project exists or update name
        # ===============================
        if project_id and project_name:
            project_sql = """
                INSERT INTO projects (id, org_id, name, created_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (id)
                DO UPDATE SET name = EXCLUDED.name
            """
            cur.execute(project_sql, (project_id, org_id, project_name, datetime.utcnow()))
            print(f"Project '{project_name}' ensured/updated in projects table.")

        # ===============================
        # Insert or update sprint record
        # ===============================
        sql = """
            INSERT INTO jira_sprints (
                id,
                sprint_id,
                board_id,
                board_name,
                project_id,
                project_name,
                name,
                state,
                start_date,
                end_date,
                goal,
                event_type,
                author_login,
                timestamp,
                raw
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (sprint_id, event_type)
            DO UPDATE SET
                board_id = EXCLUDED.board_id,
                board_name = EXCLUDED.board_name,
                project_id = EXCLUDED.project_id,
                project_name = EXCLUDED.project_name,
                name = EXCLUDED.name,
                state = EXCLUDED.state,
                start_date = EXCLUDED.start_date,
                end_date = EXCLUDED.end_date,
                goal = EXCLUDED.goal,
                author_login = EXCLUDED.author_login,
                timestamp = EXCLUDED.timestamp,
                raw = EXCLUDED.raw
        """

        cur.execute(sql, (
            event_uuid,
            sprint.get("id"),
            board_id,
            board_name,
            project_id,
            project_name,
            sprint.get("name"),
            sprint.get("state"),
            sprint.get("startDate"),
            sprint.get("endDate"),
            sprint.get("goal"),
            event_type,
            author_login,
            timestamp,
            json.dumps(sprint)
        ))

        conn.commit()
        cur.close()
        conn.close()

        print(f"Sprint event '{event_type}' recorded with board & project info.")

        # 🔔 WebSocket broadcast
        payload = {
            "event": event_type,
            "sprint_id": sprint.get("id"),
            "name": sprint.get("name"),
            "state": sprint.get("state"),
            "start_date": sprint.get("startDate"),
            "end_date": sprint.get("endDate"),
            "goal": sprint.get("goal"),
            "board_id": board_id,
            "board_name": board_name,
            "project": project_name,
            "author": author_login
        }

        broadcast_to_all(payload)
        insert_notification(
            source="jira",
            event_name=event_type,
            action=event_type.replace("sprint_", ""),
            org_id=org_id,
            project_id=project_id,
            project_name=project_name,
            board_id=board_id,
            board_name=board_name,
            entity_type="sprint",
            entity_id=str(sprint.get("id")),
            actor_email=author_login,
            title=f"Sprint {event_type.replace('sprint_', '')}",
            message=sprint.get("name"),
            extra={
                "state": sprint.get("state"),
                "goal": sprint.get("goal")
            },
            raw=sprint
        )


    except Exception as e:
        print(f"Error recording sprint event '{event_type}':", str(e))


# ==========================================================
# COMMENT HANDLER
# ==========================================================
def handle_comment_events(event_type, issue, comment, board_id=None, author_login=None):
    try:
        conn = get_connection()
        cur = conn.cursor()
        event_uuid = str(uuid.uuid4())
        timestamp = datetime.utcnow()

        sql = """
            INSERT INTO jira_issue_comments
            (id, comment_id, issue_id, board_id, comment_body, event_type, author_login, timestamp, raw)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (comment_id, event_type)
            DO UPDATE SET
                comment_body = EXCLUDED.comment_body,
                author_login = EXCLUDED.author_login,
                timestamp = EXCLUDED.timestamp,
                raw = EXCLUDED.raw
        """

        cur.execute(sql, (
            event_uuid,
            comment["id"],
            issue["id"],
            board_id,
            comment.get("body"),
            event_type,
            author_login,
            timestamp,
            json.dumps(comment)
        ))

        conn.commit()
        cur.close()
        conn.close()

        print(f"Comment event '{event_type}' recorded successfully.")

        # 🔔 Store notification
        insert_notification(
            source="jira",
            event_name=event_type,
            action=event_type.replace("comment_", ""),
            entity_type="comment",
            entity_id=str(comment.get("id")),
            parent_entity_id=str(issue.get("id")),
            actor_email=author_login,
            title=f"Comment {event_type.replace('comment_', '')}",
            message=comment.get("body"),
            raw=comment
        )

        # 📡 Broadcast to WebSocket clients
        ws_payload = {
            "event": event_type,
            "source": "jira",
            "entity_type": "comment",
            "comment_id": comment.get("id"),
            "issue_id": issue.get("id"),
            "issue_key": issue.get("key"),
            "board_id": board_id,
            "author": author_login,
            "message": comment.get("body"),
            "timestamp": timestamp.isoformat()
        }

        broadcast_to_all(ws_payload)

    except Exception as e:
        print(f"❌ Error recording comment event '{event_type}':", str(e))


# ==========================================================
# VOTING / WATCH HANDLER
# ==========================================================
def handle_vote_watch_events(event_type, issue, board_id=None, author_login=None):
    try:
        conn = get_connection()
        cur = conn.cursor()
        event_uuid = str(uuid.uuid4())
        timestamp = datetime.utcnow()

        total_votes = issue.get("votes", {}).get("votes", 0)
        total_watchers = issue.get("watches", {}).get("watchCount", 0)

        sql = """
            INSERT INTO jira_issue_votes_watches
            (id, issue_id, board_id, event_type, total_votes, total_watchers, author_login, timestamp, raw)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (issue_id, event_type)
            DO UPDATE SET
                total_votes = EXCLUDED.total_votes,
                total_watchers = EXCLUDED.total_watchers,
                author_login = EXCLUDED.author_login,
                timestamp = EXCLUDED.timestamp,
                raw = EXCLUDED.raw
        """

        cur.execute(sql, (
            event_uuid,
            issue["id"],
            board_id,
            event_type,
            total_votes,
            total_watchers,
            author_login,
            timestamp,
            json.dumps(issue)
        ))

        conn.commit()
        cur.close()
        conn.close()
        print(f"Vote/Watch event '{event_type}' recorded successfully.")

    except Exception as e:
        print(f"Error recording Vote/Watch event '{event_type}':", str(e))



# ==========================================================
# ISSUE LINKS HANDLER
# ==========================================================
def handle_issue_links(event_type, payload, author_login=None):
    try:
        conn = get_connection()
        cur = conn.cursor()
        event_uuid = str(uuid.uuid4())
        timestamp = datetime.utcnow()

        link = payload["issueLink"]
        source_issue_id = link["source"]["id"]
        target_issue_id = link["destination"]["id"]
        link_type = link["type"]["name"]
        link_id = link["id"]

        sql = """
            INSERT INTO jira_issue_links
            (id, link_id, source_issue_id, target_issue_id, link_type, event_type, author_login, timestamp, raw)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (link_id, event_type)
            DO UPDATE SET
                source_issue_id = EXCLUDED.source_issue_id,
                target_issue_id = EXCLUDED.target_issue_id,
                link_type = EXCLUDED.link_type,
                author_login = EXCLUDED.author_login,
                timestamp = EXCLUDED.timestamp,
                raw = EXCLUDED.raw
        """

        cur.execute(sql, (
            event_uuid,
            link_id,
            source_issue_id,
            target_issue_id,
            link_type,
            event_type,
            author_login,
            timestamp,
            json.dumps(link)
        ))

        conn.commit()
        cur.close()
        conn.close()
        print(f"Issue link event '{event_type}' recorded successfully.")

    except Exception as e:
        print(f"Error recording issue link event '{event_type}':", str(e))



# ==========================================================
# SUBTASK HANDLER
# ==========================================================
def handle_subtask_events(event_type, issue, board_id=None, author_login=None):
    try:
        conn = get_connection()
        cur = conn.cursor()
        event_uuid = str(uuid.uuid4())
        timestamp = datetime.utcnow()

        # -------------------------
        # Subtask basic info
        # -------------------------
        subtask_id = issue["id"]
        parent_issue_id = issue.get("parent", {}).get("id")
        fields = issue.get("fields", {})
        summary = fields.get("summary")
        status = fields.get("status", {}).get("name")

        # -------------------------
        # Board info
        # -------------------------
        board_id = board_id or issue.get("originBoardId")
        board_name = get_board_name(board_id)

        # -------------------------
        # Project info
        # -------------------------
        project = fields.get("project", {})
        project_id = project.get("id")
        project_name = project.get("name")

        sql = """
            INSERT INTO jira_subtasks (
                id,
                subtask_id,
                parent_issue_id,

                board_id,
                board_name,

                project_id,
                project_name,

                summary,
                status,
                event_type,
                author_login,
                timestamp,
                raw
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (subtask_id, event_type)
            DO UPDATE SET
                board_id = EXCLUDED.board_id,
                board_name = EXCLUDED.board_name,
                project_id = EXCLUDED.project_id,
                project_name = EXCLUDED.project_name,
                summary = EXCLUDED.summary,
                status = EXCLUDED.status,
                author_login = EXCLUDED.author_login,
                timestamp = EXCLUDED.timestamp,
                raw = EXCLUDED.raw
        """

        cur.execute(sql, (
            event_uuid,
            subtask_id,
            parent_issue_id,

            board_id,
            board_name,

            project_id,
            project_name,

            summary,
            status,
            event_type,
            author_login,
            timestamp,
            json.dumps(issue)
        ))

        conn.commit()
        cur.close()
        conn.close()
        print(f"Subtask event '{event_type}' recorded with board & project info.")

        # 🔔 WebSocket broadcast
        payload = {
            "event": event_type,
            "subtask_id": subtask_id,
            "parent_issue_id": parent_issue_id,
            "summary": summary,
            "status": status,
            "board_id": board_id,
            "board_name": board_name,
            "project": project_name,
            "author": author_login,
            "raw": issue
        }

        broadcast_to_all(payload)
        insert_notification(
            source="jira",
            event_name=event_type,
            action=event_type.replace("subtask_", ""),
            project_id=project_id,
            project_name=project_name,
            board_id=board_id,
            board_name=board_name,
            entity_type="subtask",
            entity_id=str(subtask_id),
            parent_entity_id=str(parent_issue_id),
            actor_email=author_login,
            title=f"Subtask {event_type.replace('subtask_', '')}",
            message=summary,
            extra={"status": status},
            raw=issue
        )


    except Exception as e:
        print(f"Error recording subtask event '{event_type}':", str(e))



# ==========================================================
# WORKLOG HANDLER
# ==========================================================
def handle_worklog_events(event, issue, worklog):
    print(f"Worklog event: {event}", json.dumps(worklog))
    # TODO: Insert/update worklogs table


# ==========================================================
# TIMETRACKING PROVIDER
# ==========================================================
def handle_timetracking_provider(body):
    print("Timetracking provider update:", json.dumps(body))
    # TODO: Update timetracking provider info


# ==========================================================
# FEATURE TOGGLE
# ==========================================================
def handle_feature_toggle(event, body):
    print("Feature toggle event:", event, json.dumps(body))
    # TODO: Track feature toggle changes
