import os
import json
import psycopg2
import psycopg2.extras


# ==========================================================
# PostgreSQL Connection
# ==========================================================
def get_connection():
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        dbname=os.environ["DB_NAME"],
        port=5432
    )


# ==========================================================
# Lambda Handler
# ==========================================================
def lambda_handler(event, context):
    try:
        params = event.get("queryStringParameters") or {}

        source = params.get("source")
        event_name = params.get("event_name")
        entity_type = params.get("entity_type")
        entity_id = params.get("entity_id")

        limit = int(params.get("limit", 50))
        offset = int(params.get("offset", 0))

        where_clauses = []
        values = []

        if source:
            where_clauses.append("source = %s")
            values.append(source)

        if event_name:
            where_clauses.append("event_name = %s")
            values.append(event_name)

        if entity_type:
            where_clauses.append("entity_type = %s")
            values.append(entity_type)

        if entity_id:
            where_clauses.append("entity_id = %s")
            values.append(entity_id)

        where_sql = ""
        if where_clauses:
            where_sql = "WHERE " + " AND ".join(where_clauses)

        sql = f"""
            SELECT
                id,
                source,
                event_name,
                action,
                entity_type,
                entity_id,
                actor_login,
                actor_email,
                title,
                message,
                extra,
                created_at
            FROM notifications
            {where_sql}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """

        values.extend([limit, offset])

        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, values)

        rows = cur.fetchall()

        cur.close()
        conn.close()

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*"
            },
            "body": json.dumps({
                "count": len(rows),
                "limit": limit,
                "offset": offset,
                "data": rows
            }, default=str)
        }

    except Exception as e:
        print("❌ Fetch notifications failed:", str(e))
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
