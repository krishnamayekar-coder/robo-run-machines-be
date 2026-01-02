# db_query_registry.py

DB_QUERY_REGISTRY = {

    # ==================================================
    # JIRA — TEAM LEVEL BREAKDOWNS
    # ==================================================

    "jira_status_breakdown": """
        SELECT status, COUNT(*) AS count
        FROM jira_issues
        GROUP BY status
    """,

    "jira_priority_breakdown": """
        SELECT priority, COUNT(*) AS count
        FROM jira_issues
        GROUP BY priority
    """,

    "jira_assignee_status_breakdown": """
        SELECT assignee_name, status, COUNT(*) AS count
        FROM jira_issues
        WHERE assignee_user_id IS NOT NULL
        GROUP BY assignee_user_id, status
        ORDER BY count DESC
        LIMIT 100
    """,

    "jira_assignee_priority_breakdown": """
        SELECT assignee_name, priority, COUNT(*) AS count
        FROM jira_issues
        WHERE assignee_user_id IS NOT NULL
        GROUP BY assignee_user_id, priority
        ORDER BY count DESC
        LIMIT 100
    """,

    # ==================================================
    # JIRA — NOTABLE / RISK ISSUES
    # ==================================================

    "stale_jira_issues": """
        SELECT issue_key, assignee_name, priority, status, updated_at
        FROM jira_issues
        WHERE updated_at < NOW() - INTERVAL '7 days'
          AND status NOT IN ('Done', 'Closed')
        ORDER BY updated_at ASC
        LIMIT 20
    """,

    "high_priority_open_jira": """
        SELECT issue_key, assignee_name, status, updated_at
        FROM jira_issues
        WHERE priority = 'High'
          AND status NOT IN ('Done', 'Closed')
        ORDER BY updated_at ASC
        LIMIT 20
    """,

    # ==================================================
    # SPRINT — METADATA
    # ==================================================

    "active_sprint": """
        SELECT id, name, start_date, end_date, state
        FROM jira_sprints
        WHERE state = 'active'
        ORDER BY start_date DESC
        LIMIT 1
    """,

    "recent_sprints": """
        SELECT id, name, start_date, end_date, state
        FROM jira_sprints
        ORDER BY start_date DESC
        LIMIT 3
    """,

    # ==================================================
    # SPRINT — PROGRESS & COMPLETION
    # ==================================================

    "active_sprint_issue_status": """
        SELECT
            s.name AS sprint_name,
            i.status,
            COUNT(*) AS count
        FROM jira_issues i
        JOIN jira_sprints s ON i.sprint_id = s.id
        WHERE s.state = 'active'
        GROUP BY s.name, i.status
    """,

    "active_sprint_completion": """
        SELECT
            s.name AS sprint_name,
            COUNT(*) FILTER (WHERE i.status IN ('Done', 'Closed')) AS completed,
            COUNT(*) AS total
        FROM jira_issues i
        JOIN jira_sprints s ON i.sprint_id = s.id
        WHERE s.state = 'active'
        GROUP BY s.name
    """,

    # ==================================================
    # SPRINT — VELOCITY COMPARISON
    # ==================================================

    "sprint_velocity_last_two": """
        SELECT
            s.name AS sprint_name,
            s.start_date,
            COUNT(*) FILTER (WHERE i.status IN ('Done', 'Closed')) AS completed_issues
        FROM jira_issues i
        JOIN jira_sprints s ON i.sprint_id = s.id
        GROUP BY s.name, s.start_date
        ORDER BY s.start_date DESC
        LIMIT 2
    """,

    # ==================================================
    # GIT — PULL REQUESTS
    # ==================================================

    "open_prs_by_author": """
        SELECT author_user_id, COUNT(*) AS open_prs
        FROM pull_requests
        WHERE state = 'open'
        GROUP BY author_user_id
        ORDER BY open_prs DESC
    """,

    "stale_open_prs": """
        SELECT pr_number, author_user_id, state, created_at
        FROM pull_requests
        WHERE state = 'open'
          AND created_at < NOW() - INTERVAL '2 days'
        ORDER BY created_at ASC
        LIMIT 20
    """,

    # ==================================================
    # GIT — COMMITS
    # ==================================================

    "recent_commits_by_author": """
        SELECT author_user_id, COUNT(*) AS commit_count
        FROM git_commits
        WHERE timestamp >= NOW() - INTERVAL '7 days'
        GROUP BY author_user_id
        ORDER BY commit_count DESC
        LIMIT 20
    """,

    # ==================================================
    # INCIDENTS / OPERATIONS
    # ==================================================

    "open_incidents": """
        SELECT incident_number, assigned_user_id, severity, state, updated_at
        FROM servicenow_incidents
        WHERE state NOT IN ('Resolved', 'Closed')
        ORDER BY updated_at DESC
        LIMIT 20
    """,

    # ==================================================
    # USERS — LOOKUP / ATTRIBUTION
    # ==================================================

    "users": """
        SELECT id, display_name, email, roles
        FROM users
        LIMIT 200
    """
}
