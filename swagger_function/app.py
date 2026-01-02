import json
import flask
from flask import jsonify, request
from flask_restx import Api, Namespace, Resource, fields
from aws_lambda_wsgi import response as wsgi_response
import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.exceptions import ClientError
import requests
import os

# -----------------------------
# Flask app & RESTX API setup
# -----------------------------
app = flask.Flask(__name__)

authorizations = {
    "BearerAuth": {
        "type": "apiKey",
        "in": "header",
        "name": "Authorization",
        "description": "Add 'Bearer <token>'"
    }
}

api = Api(
    app,
    version="1.0",
    title="Robo Run API Endpoints ",
    description="Swagger for AWS Lambda function",
    authorizations=authorizations,
    security="BearerAuth"
)

swagger_ns = Namespace("", description="Cognito Proxy Namespace")
api.add_namespace(swagger_ns)

# -----------------------------
# API Keys
# -----------------------------
API_KEYS = ["my-secret-api-key"]

def require_api_key(func):
    def wrapper(*args, **kwargs):
        api_key = request.headers.get("X-API-KEY")
        if not api_key or api_key not in API_KEYS:
            return jsonify({"message": "Unauthorized"}), 401
        return func(*args, **kwargs)
    wrapper.__name__ = func.__name__
    return wrapper

def require_bearer_auth(func):
    """
    Accepts only Authorization: Bearer <token>
    """
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            if token:  # optionally validate token here
                return func(*args, **kwargs)
        return jsonify({"message": "Unauthorized"}), 401
    wrapper.__name__ = func.__name__
    return wrapper



@swagger_ns.route("/test")
class Test(Resource):
    @swagger_ns.doc(security="BearerAuth")
    def post(self):
        return {"msg": "OK"}

# -----------------------------
# Swagger model for Cognito request
# -----------------------------
@swagger_ns.route("/auth/login")
class AuthLogin(Resource):
    @swagger_ns.expect(
        swagger_ns.model(
            "AuthLoginModel",
            {
                "email": fields.String(required=True, description="User email"),
                "password": fields.String(required=True, description="User password")
            }
        )
    )
    def post(self):
        body = request.json

        # Required fields
        required_fields = ["email", "password"]
        for field in required_fields:
            if field not in body:
                return jsonify({"message": f"{field} is required"}), 400

        email = body["email"]
        password = body["password"]

        # ===== No middleware, no auth, no token checks =====
        # Add real DB check here if required
        # For now return a fixed success response

        response = {
            "message": "Login successful",
            "user": {
                "email": email,
                "role": "agent"
            },
            "access_token": "mock-jwt-token-123456",
            "token_type": "Bearer",
            "expires_in": 3600
        }

        return jsonify(response), 200



forgot_password_model = swagger_ns.model(
    "ForgotPasswordRequest",
    {
        "email": fields.String(
            required=True,
            example="swaroop.s@aithinkers.com",
            description="Email of the user requesting password reset"
        ),
    }
)

@swagger_ns.route("/forgotPassword")
class ForgotPassword(Resource):

    @swagger_ns.expect(forgot_password_model)
    def post(self):
        body = request.json

        email = body.get("email")
        if not email:
            return jsonify({"message": "email is required"}), 400

        # ===== Mocked Response =====
        response = {
            "email": email,
            "status": "Reset link sent successfully",
            "timestamp": "2025-12-11T16:45:00Z"
        }

        return jsonify(response), 200


confirm_forgot_password_model = swagger_ns.model(
    "ConfirmForgotPasswordRequest",
    {
        "email": fields.String(
            required=True,
            example="krishna.aithinkers@gmail.com",
            description="Email of the user"
        ),
        "otp": fields.String(
            required=True,
            example="048120",
            description="OTP received by the user"
        ),
        "new_password": fields.String(
            required=True,
            example="1NewSecurePassword456@",
            description="New password to set"
        ),
    }
)

@swagger_ns.route("/confirmForgotPassword")
class ConfirmForgotPassword(Resource):

    @swagger_ns.expect(confirm_forgot_password_model)
    def post(self):
        body = request.json

        email = body.get("email")
        otp = body.get("otp")
        new_password = body.get("new_password")

        # ===== Validation =====
        missing_fields = [f for f in ["email", "otp", "new_password"] if not body.get(f)]
        if missing_fields:
            return jsonify({"message": f"Missing fields: {', '.join(missing_fields)}"}), 400

        # ===== Mocked Response =====
        response = {
            "email": email,
            "status": "Password updated successfully",
            "timestamp": "2025-12-11T16:55:00Z"
        }

        return jsonify(response), 200



# Model for query parameters if any (optional)
# =============================
# Parser for GET Query Params
# =============================
git_recent_parser = swagger_ns.parser()
git_recent_parser.add_argument(
    "from_date",
    type=str,
    required=True,
    location="args",
    help="Start date in YYYY-MM-DD format"
)
git_recent_parser.add_argument(
    "to_date",
    type=str,
    required=True,
    location="args",
    help="End date in YYYY-MM-DD format"
)


@swagger_ns.route("/git/recent")
class GitRecent(Resource):

    @swagger_ns.doc(security="BearerAuth")
    # @swagger_ns.expect(git_recent_parser)   # <-- FIXED: parser instead of model
    def get(self):
        """Fetch recent Git activity"""

        args = git_recent_parser.parse_args()
        from_date = args.get("from_date")
        to_date = args.get("to_date")

        # Mock response
        response = {
            "message": "Recent Git activity fetched successfully",
            "data": [
                {
                    "repo": "lms",
                    "pr_number": 101,
                    "title": "Fix login bug",
                    "action": "merged",
                    "date": from_date
                },
                {
                    "repo": "lms",
                    "pr_number": 102,
                    "title": "Add swagger endpoint",
                    "action": "opened",
                    "date": to_date
                }
            ]
        }

        return jsonify(response), 200





# Model for query parameters (optional, adjust as needed)
JiraTeamInsightsQueryModel = swagger_ns.model(
    "JiraTeamInsightsQueryModel",
    {
        "from_date": fields.String(required=True, description="Start date in YYYY-MM-DD format"),
        "to_date": fields.String(required=True, description="End date in YYYY-MM-DD format")
    }
)

@swagger_ns.route("/jira/team/insights")
class JiraTeamInsights(Resource):
    @swagger_ns.doc(security="BearerAuth")
    # @swagger_ns.expect(JiraTeamInsightsQueryModel, validate=True)
    def get(self):
        """Fetch Jira team insights"""
        from_date = request.args.get("from_date")
        to_date = request.args.get("to_date")

        # Validate required query params
        if not from_date or not to_date:
            missing = "from_date" if not from_date else "to_date"
            return jsonify({"message": f"{missing} is required"}), 400

        # Construct the external API URL
        base_url = os.environ.get("ROBO_RUN_BASE_URL", "http://example.com")
        url = f"{base_url}/jira/team/insights?from_date={from_date}&to_date={to_date}"

        try:
            # Call the external API
            resp = requests.get(url)
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.RequestException as e:
            return jsonify({"message": "Failed to fetch Jira team insights", "error": str(e)}), 500

        return jsonify({
            "message": "Jira team insights fetched successfully",
            "data": data
        }), 200




# ==========================
# Parser for GET query params
# ==========================
reports_generate_parser = swagger_ns.parser()

reports_generate_parser.add_argument(
    "team",
    type=str,
    required=True,
    location="args",
    help="Team name, e.g., backend",
    default="backend"
)

reports_generate_parser.add_argument(
    "from_date",
    type=str,
    required=True,
    location="args",
    help="Start date in YYYY-MM-DD format",
    default="2025-01-01"
)

reports_generate_parser.add_argument(
    "to_date",
    type=str,
    required=True,
    location="args",
    help="End date in YYYY-MM-DD format",
    default="2025-12-31"
)

reports_generate_parser.add_argument(
    "type",
    type=str,
    required=True,
    location="args",
    help="Report type, e.g., full or summary",
    default="full"
)


@swagger_ns.route("/reports/generate")
class ReportsGenerate(Resource):

    @swagger_ns.doc(security="BearerAuth")
    @swagger_ns.expect(reports_generate_parser)  # ✔️ FIXED
    def get(self):
        """Generate team reports"""

        args = reports_generate_parser.parse_args()

        team = args["team"]
        from_date = args["from_date"]
        to_date = args["to_date"]
        report_type = args["type"]

        # Mock response
        response = {
            "message": "Report generated successfully",
            "report": {
                "team": team,
                "from_date": from_date,
                "to_date": to_date,
                "type": report_type,
                "url": f"https://example.com/reports/{team}_{from_date}_to_{to_date}_{report_type}.pdf"
            }
        }

        return jsonify(response), 200




# Model for query parameters
activity_recent_parser = swagger_ns.parser()
activity_recent_parser.add_argument(
    "from_date",
    type=str,
    required=True,
    help="Start date in YYYY-MM-DD format",
    location="args",
    default="2025-01-01"
)
activity_recent_parser.add_argument(
    "to_date",
    type=str,
    required=True,
    help="End date in YYYY-MM-DD format",
    location="args",
    default="2025-12-01"
)

@swagger_ns.route("/activity/recent")
class ActivityRecent(Resource):
    @swagger_ns.doc(security="BearerAuth")
    @swagger_ns.expect(activity_recent_parser)
    def get(self):
        """Fetch recent activity"""

        from_date = request.args.get("from_date")
        to_date = request.args.get("to_date")

        if not from_date or not to_date:
            missing = "from_date" if not from_date else "to_date"
            return {"message": f"{missing} is required"}, 400

        response = {
            "message": "Recent activity fetched successfully",
            "data": [
                {"activity": "Pull request merged", "repo": "lms", "date": from_date},
                {"activity": "Issue closed", "repo": "lms", "date": to_date}
            ]
        }

        return response, 200




# Model for query parameters (if needed, optional here since none are specified)
AnalyticsWeeklyQueryModel = swagger_ns.model(
    "AnalyticsWeeklyQueryModel",
    {
        "week_start": fields.String(required=False, description="Week start date in YYYY-MM-DD format"),
        "week_end": fields.String(required=False, description="Week end date in YYYY-MM-DD format")
    }
)

@swagger_ns.route("/analytics/weekly")
class AnalyticsWeekly(Resource):
    @swagger_ns.doc(security="BearerAuth")
    def get(self):
        """Fetch weekly analytics"""
        week_start = request.args.get("week_start")
        week_end = request.args.get("week_end")

        # Mock response
        response = {
            "message": "Weekly analytics fetched successfully",
            "analytics": {
                "week_start": week_start or "2025-12-01",
                "week_end": week_end or "2025-12-07",
                "total_activities": 42,
                "active_teams": ["backend", "frontend", "qa"],
                "highlights": [
                    {"team": "backend", "activity_count": 15},
                    {"team": "frontend", "activity_count": 12},
                    {"team": "qa", "activity_count": 15}
                ]
            }
        }

        return response, 200



# Model for query parameters (optional, e.g., to filter by team or date range)
DevelopersWorkloadQueryModel = swagger_ns.model(
    "DevelopersWorkloadQueryModel",
    {
        "team": fields.String(required=False, description="Team name, e.g., backend"),
        "from_date": fields.String(required=False, description="Start date in YYYY-MM-DD format"),
        "to_date": fields.String(required=False, description="End date in YYYY-MM-DD format")
    }
)

@swagger_ns.route("/developers/workload")
class DevelopersWorkload(Resource):
    @swagger_ns.doc(security="BearerAuth")
    def get(self):
        """Fetch developer workload"""
        team = request.args.get("team")
        from_date = request.args.get("from_date")
        to_date = request.args.get("to_date")

        # Mock response
        response = {
            "message": "Developer workload fetched successfully",
            "workload": [
                {"developer": "Alice", "team": "backend", "tasks_assigned": 5, "tasks_completed": 4},
                {"developer": "Bob", "team": "frontend", "tasks_assigned": 6, "tasks_completed": 6},
                {"developer": "Charlie", "team": "qa", "tasks_assigned": 4, "tasks_completed": 3}
            ]
        }

        # Optionally filter by team if provided
        if team:
            response["workload"] = [w for w in response["workload"] if w["team"] == team]

        return response, 200



# Model for query parameters (optional, e.g., to filter by repo or date range)
PRsBottlenecksQueryModel = swagger_ns.model(
    "PRsBottlenecksQueryModel",
    {
        "repo": fields.String(required=False, description="Repository name, e.g., lms"),
        "from_date": fields.String(required=False, description="Start date in YYYY-MM-DD format"),
        "to_date": fields.String(required=False, description="End date in YYYY-MM-DD format")
    }
)

@swagger_ns.route("/prs/bottlenecks")
class PRsBottlenecks(Resource):
    @swagger_ns.doc(security="BearerAuth")
    def get(self):
        """Fetch pull request bottlenecks"""
        repo = request.args.get("repo")
        from_date = request.args.get("from_date")
        to_date = request.args.get("to_date")

        # Mock response
        bottlenecks = [
            {"pr_number": 101, "repo": "lms", "title": "Fix login bug", "days_open": 5},
            {"pr_number": 102, "repo": "lms", "title": "Add swagger endpoint", "days_open": 8},
            {"pr_number": 103, "repo": "cms", "title": "Update README", "days_open": 3}
        ]

        # Optionally filter by repo if provided
        if repo:
            bottlenecks = [b for b in bottlenecks if b["repo"] == repo]

        response = {
            "message": "PR bottlenecks fetched successfully",
            "data": bottlenecks
        }

        return response, 200



# Model for query parameters (optional, e.g., to filter by sprint or team)
JiraSprintProgressQueryModel = swagger_ns.model(
    "JiraSprintProgressQueryModel",
    {
        "sprint_id": fields.String(required=False, description="Jira sprint ID"),
        "team": fields.String(required=False, description="Team name, e.g., backend")
    }
)

@swagger_ns.route("/jira/sprint/progress")
class JiraSprintProgress(Resource):
    @swagger_ns.doc(security="BearerAuth")
    def get(self):
        """Fetch Jira sprint progress"""
        sprint_id = request.args.get("sprint_id")
        team = request.args.get("team")

        # Mock response
        progress_data = [
            {"sprint_id": "SPR-101", "team": "backend", "completed_stories": 12, "total_stories": 15},
            {"sprint_id": "SPR-102", "team": "frontend", "completed_stories": 8, "total_stories": 10},
            {"sprint_id": "SPR-103", "team": "qa", "completed_stories": 5, "total_stories": 7}
        ]

        # Filter by sprint_id or team if provided
        if sprint_id:
            progress_data = [p for p in progress_data if p["sprint_id"] == sprint_id]
        if team:
            progress_data = [p for p in progress_data if p["team"] == team]

        response = {
            "message": "Jira sprint progress fetched successfully",
            "data": progress_data
        }

        return response, 200




# Model for query parameters (optional, e.g., to filter by team or assignee)
@swagger_ns.route("/jira/tasks/today")
class JiraTasksToday(Resource):
    @swagger_ns.doc(security="BearerAuth")
    def get(self):
        """Fetch Jira tasks for today"""
        team = request.args.get("team")
        assignee = request.args.get("assignee")

        # Mock response
        tasks_today = [
            {"task_id": "TASK-101", "title": "Fix login bug", "team": "backend", "assignee": "Alice", "status": "In Progress"},
            {"task_id": "TASK-102", "title": "Update API docs", "team": "frontend", "assignee": "Bob", "status": "To Do"},
            {"task_id": "TASK-103", "title": "Test payment flow", "team": "qa", "assignee": "Charlie", "status": "In Progress"}
        ]

        # Filter by team or assignee if provided
        if team:
            tasks_today = [t for t in tasks_today if t["team"] == team]
        if assignee:
            tasks_today = [t for t in tasks_today if t["assignee"] == assignee]

        response = {
            "message": "Today's Jira tasks fetched successfully",
            "data": tasks_today
        }

        return response, 200



# Model for request body
CognitoCreateUserModel = swagger_ns.model(
    "CognitoCreateUserModel",
    {
        "email": fields.String(required=True, description="User email"),
        "password": fields.String(required=True, description="User password"),
        "role": fields.String(
            required=True,
            description='User role, one of ["DEV", "QA", "MANAGER", "DEV_MANAGER"]'
        )
    }
)

@swagger_ns.route("/cognito/create-user")
class CognitoCreateUser(Resource):
    
    @swagger_ns.expect(CognitoCreateUserModel, validate=True)
    def post(self):
        """Create a new Cognito user"""
        body = request.json

        # Required fields
        required_fields = ["email", "password", "role"]
        for field in required_fields:
            if field not in body:
                return {"message": f"{field} is required"}, 400

        email = body["email"]
        password = body["password"]
        role = body["role"]

        # Validate role
        allowed_roles = ["DEV", "QA", "MANAGER", "DEV_MANAGER"]
        if role not in allowed_roles:
            return {"message": f"role must be one of {allowed_roles}"}, 400

        # ===== Here you would normally create the user in Cognito =====
        # Mock response
        response = {
            "message": "User created successfully",
            "user": {
                "email": email,
                "role": role
            }
        }

        return response, 201


# -----------------------------
# Swagger JSON & UI
# -----------------------------
@app.route("/swagger/openapi.json")
def openapi():
    return jsonify(api.__schema__)

@app.route("/swagger/docs")
def docs():
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Swagger UI</title>
        <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist/swagger-ui.css">
    </head>
    <body>
        <div id="swagger-ui"></div>
        <script src="https://unpkg.com/swagger-ui-dist/swagger-ui-bundle.js"></script>
        <script src="https://unpkg.com/swagger-ui-dist/swagger-ui-standalone-preset.js"></script>
        <script>
            window.onload = () => {
                SwaggerUIBundle({
                    url: "/swagger/openapi.json",
                    dom_id: "#swagger-ui",
                    presets: [
                        SwaggerUIBundle.presets.apis,
                        SwaggerUIStandalonePreset
                    ],
                    requestInterceptor: (req) => {
                        req.headers['X-API-KEY'] = 'my-secret-api-key';

                        // Read from UI "Authorize" section or custom inputs
                        const accessKey = document.getElementById('x-aws-access-key')?.value;
                        const secretKey = document.getElementById('x-aws-secret-key')?.value;
                        const region = document.getElementById('x-aws-region')?.value;

                        if (accessKey) req.headers['x-aws-access-key'] = accessKey;
                        if (secretKey) req.headers['x-aws-secret-key'] = secretKey;
                        if (region) req.headers['x-aws-region'] = region;

                        return req;
                    }
                });
            };
        </script>

    </body>
    </html>
    """
    return html, 200, {"Content-Type": "text/html"}

# -----------------------------
# Lambda adapter
# -----------------------------
def convert_http_api_event(event):
    http = event["requestContext"]["http"]
    return {
        "httpMethod": http["method"],
        "path": event.get("rawPath", http.get("path", "/")),
        "headers": event.get("headers", {}),
        "multiValueHeaders": {},
        "queryStringParameters": event.get("queryStringParameters", {}),
        "body": event.get("body", None),
        "isBase64Encoded": event.get("isBase64Encoded", False)
    }

def lambda_handler(event, context):
    if isinstance(event, dict) and event.get("version") == "2.0":
        event = convert_http_api_event(event)
    return wsgi_response(app, event, context)
