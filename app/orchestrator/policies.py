class ResearchPolicy:
    POLICY_VERSION = "1.1.0"
    PLAN_VERSION = "1.1.0"

    DEFAULT_RECENT_MATCHES = 10
    MIN_COVERAGE_SCORE = 0.80
    MAX_RETRIES = 3

    REQUIRED_DOMAINS = [
        "MATCH_IDENTITY",
        "FORM_HOME",
        "FORM_AWAY",
        "ABSENCES_HOME",
        "ABSENCES_AWAY",
        "STATISTICS",
    ]

    OPTIONAL_DOMAINS = [
        "HEAD_TO_HEAD",
        "EXPECTED_LINEUPS",
        "WEATHER",
    ]

    DOMAIN_PRIORITIES = {
        "MATCH_IDENTITY": 100,
        "ABSENCES_HOME": 95,
        "ABSENCES_AWAY": 95,
        "FORM_HOME": 90,
        "FORM_AWAY": 90,
        "STATISTICS": 85,
        "EXPECTED_LINEUPS": 80,
        "HEAD_TO_HEAD": 60,
        "WEATHER": 30,
    }

    TIMEOUTS = {
        "http_fetch": 30,
        "browser": 120,
        "statistics": 60,
    }
