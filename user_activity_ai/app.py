import json
import os
import psycopg2
import psycopg2.extras
from datetime import datetime, timedelta
from openai import OpenAI
import re

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

# PostgreSQL connection
def get_connection():
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        dbname=os.environ["DB_NAME"],
        port=5432
    )

# Lambda handler
def lambda_handler(event, context):
    try:
        body = json.loads(event.get("body", "{}"))
        question = body.get("question", "")

        if not question:
            return {"statusCode": 400, "body": json.dumps({"error": "question is required"})}

        # Try to detect email in the question
        email_match = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", question)
        
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        if email_match:
            # Match by email
            cur.execute("""
                SELECT id, email, display_name
                FROM users
                WHERE LOWER(email) = %s
                LIMIT 1
            """, (email_match.group(0).lower(),))
        else:
            # Extract alphabetic words
            words = re.findall(r"[a-zA-Z]{2,}", question)
            if not words:
                return {"statusCode": 400, "body": json.dumps({"error": "No valid user identifier found in question"})}

            # Build SQL: match any word in display_name or email
            sql_conditions = " OR ".join(["LOWER(display_name) ILIKE %s" for _ in words] +
                                          ["LOWER(email) ILIKE %s" for _ in words])
            sql_params = [f"%{w.lower()}%" for w in words] * 2

            query = f"""
                SELECT id, email, display_name
                FROM users
                WHERE {sql_conditions}
                LIMIT 1
            """
            cur.execute(query, sql_params)

        user = cur.fetchone()
        if not user:
            return {"statusCode": 404, "body": json.dumps({"error": "User not found"})}

        user_id = user["id"]
        since = datetime.utcnow() - timedelta(days=7)

        # Fetch Git commits
        cur.execute("""
            SELECT repo, commit_sha, message, files, timestamp
            FROM git_commits
            WHERE author_user_id = %s AND timestamp >= %s
            ORDER BY timestamp DESC
            LIMIT 20
        """, (user_id, since))
        commits = cur.fetchall()

        # Fetch Jira issues
        cur.execute("""
            SELECT issue_key, status, priority, updated_at
            FROM jira_issues
            WHERE LOWER(assignee_email) = %s
            ORDER BY updated_at DESC
            LIMIT 20
        """, (user['email'].lower(),))
        issues = cur.fetchall()
        print("email==>",user['email'])
        print("issues==>",issues)

        # Fetch Jira subtasks
        cur.execute("""
            SELECT summary, status, timestamp
            FROM jira_subtasks
            WHERE author_login ILIKE %s
            ORDER BY timestamp DESC
            LIMIT 20
        """, (f"%{user['email']}%",))
        subtasks = cur.fetchall()

        cur.close()
        conn.close()

        # Build prompt for OpenAI
        prompt = f"""
            You are an engineering manager assistant.

            User: {user['display_name']} ({user['email']})

            Git commits (last 7 days):
            {json.dumps(commits, indent=2, default=str)}

            Jira issues:
            {json.dumps(issues, indent=2, default=str)}

            Jira subtasks:
            {json.dumps(subtasks, indent=2, default=str)}

            Question:
            {question}

            Answer in clear, concise bullet points.
            """

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Summarize developer activity clearly."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3
        )

        answer = response.choices[0].message.content

        return {"statusCode": 200, "body": json.dumps({"user": user, "answer": answer})}

    except Exception as e:
        print("ERROR:", str(e))
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}
