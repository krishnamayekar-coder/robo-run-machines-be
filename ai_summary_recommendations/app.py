import os
import json
import requests
from openai import OpenAI
from datetime import datetime, date

from api_registry import API_REGISTRY
from db_query_registry import DB_QUERY_REGISTRY
from db_client import run_safe_query

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
GLOBAL_TIMEOUT = 35


# --------------------------------------------------
# Helpers
# --------------------------------------------------
def safe_json(obj):
    def default(o):
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        return str(o)

    return json.dumps(obj, indent=2, default=default)


def enrich_snapshot(snapshot):
    """
    Resolve user IDs → display names and attach them directly
    to records so the model is FORCED to use names.
    """
    users = {}

    for u in snapshot.get("db::users", []):
        users[u["id"]] = u["display_name"]

    def resolve(uid):
        return users.get(uid, uid)

    # Jira assignee enrichment
    for key in [
        "db::jira_assignee_status_breakdown",
        "db::jira_assignee_priority_breakdown",
        "db::stale_jira_issues",
        "db::high_priority_open_jira",
    ]:
        if key in snapshot:
            for row in snapshot[key]:
                if "assignee_user_id" in row:
                    row["assignee_name"] = resolve(row["assignee_user_id"])

    # PR enrichment
    for key in ["db::open_prs_by_author", "db::stale_open_prs"]:
        if key in snapshot:
            for row in snapshot[key]:
                if "author_user_id" in row:
                    row["author_name"] = resolve(row["author_user_id"])

    # Incidents
    if "db::open_incidents" in snapshot:
        for row in snapshot["db::open_incidents"]:
            if "assigned_user_id" in row:
                row["assigned_name"] = resolve(row["assigned_user_id"])

    return snapshot


# --------------------------------------------------
# Core Logic
# --------------------------------------------------
def generate_summary_logic():
    snapshot = {}
    failures = 0

    # -------------------------
    # API SOURCES (BLOCKING)
    # -------------------------
    for api_name, api_url in API_REGISTRY.items():
        try:
            resp = requests.get(api_url, timeout=GLOBAL_TIMEOUT)
            resp.raise_for_status()
            snapshot[api_name] = resp.json()
        except Exception:
            failures += 1

    # -------------------------
    # DB SOURCES (BLOCKING)
    # -------------------------
    for query_name, sql in DB_QUERY_REGISTRY.items():
        try:
            snapshot[f"db::{query_name}"] = run_safe_query(sql)
        except Exception:
            failures += 1

    # -------------------------
    # ENRICH DATA
    # -------------------------
    snapshot = enrich_snapshot(snapshot)

    # -------------------------
    # CONFIDENCE
    # -------------------------
    total_sources = len(API_REGISTRY) +len(DB_QUERY_REGISTRY)
    confidence = max(70, int((1 - failures / total_sources) * 100))

    # -------------------------
    # PROMPT (HARD RULED)
    # -------------------------
    prompt = f"""
You are a SENIOR ENGINEERING ANALYST producing a leadership-ready operational summary.

ABSOLUTE RULES:
- Use ONLY the data provided
- Do NOT invent numbers, names, or causes
- Analyze ACROSS all APIs and DB queries
- If user names, PR numbers, or issue keys exist, YOU MUST mention them
- Merge duplicate signals into ONE insight
- Focus on imbalance, risk, and concentration

PERSPECTIVE ROTATION RULE:
When multiple high-impact issues exist, rotate emphasis between:
- delivery risk
- workload concentration
- review bottlenecks
- stale or aging work

LANGUAGE RULES:
- Use short, factual sentences
- Avoid adjectives unless risk-related
- Prefer numbers over descriptions
- No explanatory fluff

Do NOT repeat the same lead insight ordering if multiple valid patterns exist.


====================
SUMMARY (MANDATORY)
====================
- EXACTLY 4 to 5 bullet points
- EACH bullet = EXACTLY 2 sentences
- Each bullet MUST describe:
  1) What pattern exists
  2) Why it matters
- Mention sprint names, assignee names, PR numbers, issue keys when available
- Highlight:
  - workload imbalance
  - sprint delivery risk
  - backlog growth
  - stale or blocked work
- Omit healthy or normal metrics

====================
RECOMMENDATIONS (MANDATORY)
====================
- EXACTLY 3 recommendations
- EACH recommendation = 1–3 lines
- EACH must address a DIFFERENT issue
- Explicitly state:
  - WHO should act
  - WHAT should change
  - FROM whom → TO whom (for redistribution)
- Mention names, PR numbers, issue keys when applicable

====================
DATA
====================
{safe_json(snapshot)}

====================
OUTPUT (STRICT JSON ONLY)
====================
{{
  "summary": [
    ".Sentence one. Sentence two."
  ],
  "recommendations": [
    {{
      "title": "Action-oriented title",
      "text": "Clear, outcome-focused action.",
      "impact": "High"
    }}
  ],  
  "confidence": {confidence}
}}
"""

    ai_resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=700
    )

    return json.loads(ai_resp.choices[0].message.content)


# --------------------------------------------------
# Lambda Handler
# --------------------------------------------------
def lambda_handler(event, context):
    try:
        result = generate_summary_logic()

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*"
            },
            "body": json.dumps(result)
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
