import os
import json
import psycopg2
from datetime import date

ALLOWED_ROLES = ["DEV", "QA", "MANAGER", "DEV_MANAGER"]


def get_connection():
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        dbname=os.environ["DB_NAME"],
        port=5432
    )


def lambda_handler(event, context):
    try:
        # ==========================================================
        # Extract JWT claims
        # ==========================================================
        claims = event.get("requestContext", {}) \
                      .get("authorizer", {}) \
                      .get("jwt", {}) \
                      .get("claims", {})

        user_email = claims.get("email")
        user_role = claims.get("custom:role")
        sub = claims.get("sub")

        print("User Email:", user_email)
        print("User Role:", user_role)
        print("sub:", sub)

        # ==========================================================
        # Role check
        # ==========================================================
        if not user_role or user_role not in ALLOWED_ROLES:
            return {
                "statusCode": 403,
                "body": json.dumps({"error": "Access denied. Insufficient permissions."})
            }

        conn = get_connection()
        cur = conn.cursor()

        # ==========================================================
        # Fetch ALL Sprints (latest record per sprint)
        # ==========================================================
        cur.execute("""
            SELECT DISTINCT ON (sprint_id)
                sprint_id,
                repo_or_board_id,
                name,
                state,
                start_date,
                end_date,
                goal,
                event_type,
                author_login,
                timestamp
            FROM jira_sprints
            ORDER BY sprint_id, timestamp DESC
        """)

        sprints = cur.fetchall()

        if not sprints:
            cur.close()
            conn.close()
            return {
                "statusCode": 404,
                "body": json.dumps({"error": "No sprints found"})
            }

        today = date.today()
        sprint_list = []

        # ==========================================================
        # Process Each Sprint
        # ==========================================================
        for sprint in sprints:
            (
                sprint_id,
                board_id,
                name,
                state,
                start_date,
                end_date,
                goal,
                event_type,
                author_login,
                updated_at
            ) = sprint

            # -------------------------------
            # WORK-BASED PROGRESS (DEV DONE)
            # -------------------------------
            # -------------------------------
            # WORK-BASED PROGRESS (DEV DONE ONLY)
            # -------------------------------
            cur.execute("""
                SELECT
                    COUNT(*) AS total_issues,
                    COUNT(*) FILTER (
                        WHERE raw->'fields'->'status'->>'name'
                        IN ('Dev Done', 'Done', 'Closed', 'Resolved')
                    ) AS dev_done_issues
                FROM jira_issues
                WHERE
                    COALESCE(
                        (raw->'fields'->'issuetype'->>'subtask')::boolean,
                        false
                    ) = false
                    AND EXISTS (
                        SELECT 1
                        FROM jsonb_array_elements(
                            COALESCE(
                                CASE
                                    WHEN jsonb_typeof(raw->'fields'->'customfield_10020') = 'array'
                                    THEN raw->'fields'->'customfield_10020'
                                    ELSE '[]'::jsonb
                                END,
                                '[]'::jsonb
                            )
                        ) sprint
                        WHERE (sprint->>'id')::int = %s
                    );
            """, (str(sprint_id),))

            total_issues, dev_done_issues = cur.fetchone()

            # -------------------------------
            # Sprint Progress %
            # -------------------------------
            progress_percent = round((dev_done_issues / total_issues) * 100, 2) if total_issues else 0

            # -------------------------------
            # Sprint Time Calculation
            # -------------------------------
            total_days = elapsed_days = remaining_days = time_elapsed_percent = None

            if start_date and end_date:
                total_days = (end_date.date() - start_date.date()).days
                elapsed_days = max((today - start_date.date()).days, 0)
                remaining_days = max((end_date.date() - today).days, 0)

                if total_days > 0:
                    time_elapsed_percent = round((elapsed_days / total_days) * 100, 2)

            # -------------------------------
            # Sprint Health Status
            # -------------------------------
            sprint_status = "NO_DATA"

            if time_elapsed_percent is not None:
                gap = time_elapsed_percent - progress_percent

                if progress_percent >= time_elapsed_percent:
                    sprint_status = "ON_TRACK"
                elif gap <= 15:
                    sprint_status = "AT_RISK"
                else:
                    sprint_status = "OFF_TRACK"


            if total_issues == 0:
                progress = 0
                status = "No Issues"
            else:
                progress = round((dev_done_issues / total_issues) * 100, 2)

                if progress == 100:
                    status = "Completed"
                elif progress > 0:
                    status = "In Progress"
                else:
                    status = "Not Started"

            # -------------------------------
            # Time info (ONLY for display)
            # -------------------------------
            total_days = None
            elapsed_days = None
            remaining_days = None

            if start_date and end_date:
                total_days = (end_date.date() - start_date.date()).days
                elapsed_days = max((today - start_date.date()).days, 0)
                remaining_days = max((end_date.date() - today).days, 0)

            sprint_list.append({
                "sprint_id": sprint_id,
                "board_id": board_id,
                "name": name,
                "state": state,
                "goal": goal,

                # Dates
                "start_date": str(start_date),
                "end_date": str(end_date),

                # Work metrics
                "total_issues": total_issues,
                "dev_done_issues": dev_done_issues,
                "progress_percent": progress_percent,

                # Time metrics
                "total_days": total_days,
                "elapsed_days": elapsed_days,
                "remaining_days": remaining_days,
                "time_elapsed_percent": time_elapsed_percent,

                # Final sprint health
                "sprint_status": sprint_status,

                "last_update": str(updated_at)
            })


        cur.close()
        conn.close()

        # ==========================================================
        # Final Response
        # ==========================================================
        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "count": len(sprint_list),
                    "sprints": sprint_list
                },
                default=str,
                indent=2
            )
        }

    except Exception as e:
        print("Error:", str(e))
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
