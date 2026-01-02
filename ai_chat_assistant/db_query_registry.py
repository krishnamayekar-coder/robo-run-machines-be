DB_QUERY_REGISTRY = {

    "jira_issues": """
        SELECT issue_key, status, priority, assignee_name, reporter_name, updated_at
        FROM jira_issues
        ORDER BY updated_at DESC
        LIMIT 300
    """,

    "pull_requests": """
        SELECT pr_number, title, author_login, state, merged,timestamp
        FROM pull_requests
        ORDER BY timestamp DESC
        LIMIT 300
    """,

    "git_commits": """
        SELECT repo, author_email, message, timestamp
        FROM git_commits
        ORDER BY timestamp DESC
        LIMIT 300
    """,

    "users": """
        SELECT id, display_name, email
        FROM users
    """,

    "activity_events": """
        SELECT type, source_ref, occurred_at
        FROM activity_events
        ORDER BY occurred_at DESC
        LIMIT 300
    """,

    "open_incidents": """
        SELECT incident_number, severity, state, updated_at
        FROM servicenow_incidents
        WHERE state NOT IN ('Resolved', 'Closed')
        ORDER BY updated_at DESC
        LIMIT 50
    """
}
