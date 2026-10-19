class ResearchPolicy:
    POLICY_VERSION = "1.1.0"
    PLAN_VERSION = "1.1.0"

    DEFAULT_RECENT_MATCHES = 10
    MIN_COVERAGE_SCORE = 0.80
    MAX_RETRIES = 3

    REQUIRED_DOMAINS = [
        "TEAM_PROFILE_HOME",
        "TEAM_PROFILE_AWAY",
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
        "REFEREE",
        "RIVALRY",
        "STYLE_MATCHUP",
        "MOTIVATION_HOME",
        "MOTIVATION_AWAY",
        "TRAVEL_FATIGUE_HOME",
        "TRAVEL_FATIGUE_AWAY",
    ]

    DOMAIN_PRIORITIES = {
        "TEAM_PROFILE_HOME": 100,
        "TEAM_PROFILE_AWAY": 99,
        "ABSENCES_HOME": 95,
        "ABSENCES_AWAY": 95,
        "FORM_HOME": 90,
        "FORM_AWAY": 90,
        "STATISTICS": 85,
        "EXPECTED_LINEUPS": 80,
        "HEAD_TO_HEAD": 60,
        "WEATHER": 30,
        "REFEREE": 55,
        "RIVALRY": 45,
        "STYLE_MATCHUP": 50,
        "MOTIVATION_HOME": 65,
        "MOTIVATION_AWAY": 64,
        "TRAVEL_FATIGUE_HOME": 58,
        "TRAVEL_FATIGUE_AWAY": 58,
    }

    TIMEOUTS = {
        "http_fetch": 30,
        "browser": 120,
        "statistics": 60,
    }
