import os
import json
import requests
from datetime import datetime, date
from openai import OpenAI

from api_registry import API_REGISTRY
from db_query_registry import DB_QUERY_REGISTRY
from db_client import run_safe_query

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
GLOBAL_TIMEOUT = 20


# -------------------------
# SAFE JSON SERIALIZER
# -------------------------
def safe_json(obj):
    def default(o):
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        return str(o)
    return json.dumps(obj, indent=2, default=default)


# -------------------------
# GREETING HANDLER
# -------------------------
def is_greeting(text: str) -> bool:
    greetings = [
        "hi", "hello", "hey",
        "good morning", "good evening",
        "good afternoon", "how are you"
    ]
    return text.lower() in greetings


def lambda_handler(event, context):
    try:
        body = json.loads(event.get("body", "{}"))
        question = body.get("question", "").strip()

        if not question:
            return _response(400, {"error": "Question is required"})

        # -------------------------
        # GREETING SHORT-CIRCUIT
        # -------------------------
        if is_greeting(question):
            return _response(200, {
                "facts": "Hello! You can ask me about Jira issues, pull requests, commits, sprint activity, or team workload.",
                "sources": [],
                #"confidence": 100
            })

        collected_data = {}

        # -------------------------
        # SAFE API COLLECTION
        # -------------------------
        for api_name, meta in API_REGISTRY.items():
            try:
                resp = requests.get(meta["url"], timeout=GLOBAL_TIMEOUT)
                if resp.status_code == 200:
                    collected_data[f"api::{api_name}"] = resp.json()
            except Exception:
                # Silent failure by design
                continue

        # -------------------------
        # DB SNAPSHOT COLLECTION
        # -------------------------
        for name, sql in DB_QUERY_REGISTRY.items():
            try:
                rows = run_safe_query(sql)
                collected_data[f"db::{name}"] = rows
            except Exception:
                continue

        # -------------------------
        # FACT-ONLY PROMPT
        # -------------------------
        prompt = f"""
You are a FACTUAL REPORTING ASSISTANT.

Your job is to answer the user’s question using ONLY the data provided.
This is NOT a chatbot and NOT a summarizer.

========================
ABSOLUTE RULES (MANDATORY)
========================
- Use ONLY the provided data.
- Do NOT hallucinate, infer, summarize, or recommend.
- Do NOT add external knowledge.
- Do NOT explain causes or implications.
- State ONLY verifiable facts present in the data.
- If no relevant data exists, respond exactly:
  "No relevant factual data was found."

========================
FORMAT RULES (MANDATORY)
========================
- Output MUST be plain text.
- Output MUST be multiple short lines.
- Each line MUST describe EXACTLY ONE category of facts.
- NEVER mix categories in the same line.
- Do NOT use bullet points, numbering, markdown, or paragraphs.
- Prefer COUNTS over item-level details unless explicitly asked.
- List individual IDs or names ONLY when the question asks for them.

========================
ALLOWED FACT CATEGORIES
(Use ONLY when relevant)
========================
- Sprint summary
- Jira status breakdown
- Jira issues (individual)
- High priority issues
- Pull requests
- Git commits
- Workload distribution
- Incidents / alerts
- Team members / users
- Activity timeline

========================
LINE STRUCTURE (STRICT)
========================
Each line MUST follow this pattern:

<Category label>: <factual statement>

========================
GOOD EXAMPLES
========================
Sprint summary: 211 Jira issues were updated during the active sprint window.
Jira status breakdown: To Do 166, In Progress 17, In Review 13, Done 8.
Pull requests: 5 pull requests closed, 2 merged, 3 not merged.
Git commits: 36 commits made by Krishna Mayekar, last commit on 2025-12-30.
Workload distribution: Venkata Ravi Duddunta has 42 open Jira issues.

========================
BAD EXAMPLES (FORBIDDEN)
========================
- Paragraphs
- Bullet points
- Nested lists
- Mixing Jira, PRs, and Git in one sentence
- Listing dozens of IDs when counts are sufficient
- Interpretive language (risk, concern, delay, improvement)

========================
GREETING HANDLING
========================
If the user input is ONLY a greeting (e.g., "hi", "hello", "good morning"):
Respond with a polite greeting and NOTHING else.

Example:
"Hello! How can I help you today?"

========================
USER QUESTION
========================
{question}

========================
DATA (SOURCE OF TRUTH)
========================
{safe_json(collected_data)}

========================
OUTPUT
========================
Return ONLY the formatted factual lines.
Do NOT include explanations or metadata.

"""

        ai_resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=700
        )

        return _response(200, {
            "facts": ai_resp.choices[0].message.content.strip(),
            "sources": list(collected_data.keys()),
            #"confidence": 85
        })

    except Exception as e:
        return _response(500, {"error": str(e)})


def _response(status, body):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body)
    }
