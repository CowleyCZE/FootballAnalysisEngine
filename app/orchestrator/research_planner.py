from typing import List

from app.orchestrator.models import MatchIdentity, TaskRequirement
from app.orchestrator.policies import ResearchPolicy


class ResearchPlanner:
    """Plans entity-first research, then match-level research and statistics."""

    def create_plan(self, match_identity: MatchIdentity) -> List[TaskRequirement]:
        tasks: List[TaskRequirement] = []
        home_profile = "TEAM_PROFILE_HOME"
        away_profile = "TEAM_PROFILE_AWAY"
        cutoff = match_identity.data_cutoff_at.isoformat() if match_identity.data_cutoff_at else "N/A"

        tasks.append(TaskRequirement(
            task_uuid=f"TASK-{match_identity.match_id}-{home_profile}",
            domain=home_profile, task_type="NEWS_COLLECTION",
            description=f"Vytvoř časově omezený profil týmu {match_identity.home_team} k {cutoff}.",
            priority=100, required=True, capabilities_required=["SEARCH", "CRAWL"],
            subject_team_id=match_identity.home_team_id,
        ))
        tasks.append(TaskRequirement(
            task_uuid=f"TASK-{match_identity.match_id}-{away_profile}",
            domain=away_profile, task_type="NEWS_COLLECTION",
            description=f"Vytvoř časově omezený profil týmu {match_identity.away_team} k {cutoff}.",
            priority=99, required=True, capabilities_required=["SEARCH", "CRAWL"],
            depends_on=[f"TASK-{match_identity.match_id}-{home_profile}"],
            subject_team_id=match_identity.away_team_id,
        ))

        stat_added = False
        for domain in ResearchPolicy.REQUIRED_DOMAINS + ResearchPolicy.OPTIONAL_DOMAINS:
            if domain in (home_profile, away_profile):
                continue
            if domain in {"FORM_HOME", "FORM_AWAY", "STATISTICS"}:
                if stat_added:
                    continue
                stat_added = True
                canonical_domain, task_type, caps = "STATISTICS", "STAT_COLLECTION", ["STATISTICS"]
                description = f"Vypočítej historické statistiky zápasu před cutoffem {cutoff}."
                dependencies = []
            elif domain == "HEAD_TO_HEAD":
                canonical_domain, task_type, caps = domain, "FACT_COLLECTION", ["SEARCH", "CRAWL"]
                description = f"Po profilech obou týmů ověř vzájemné zápasy a související kontext před {cutoff}."
                dependencies = [f"TASK-{match_identity.match_id}-{away_profile}"]
            elif domain.startswith("ABSENCES_") or domain == "EXPECTED_LINEUPS":
                canonical_domain, task_type, caps = domain, "NEWS_COLLECTION", ["SEARCH", "CRAWL"]
                description = f"Zjisti aktuální týmové zprávy pro {domain} před cutoffem {cutoff}."
                dependencies = []
            elif domain.startswith("MOTIVATION_") or domain.startswith("TRAVEL_FATIGUE_"):
                canonical_domain, task_type, caps = domain, "FACT_COLLECTION", ["SEARCH", "CRAWL"]
                description = f"Vyhodnoť motivaci, rozpis, odpočinek, cestování a únavu ({domain}) před cutoffem {cutoff}."
                dependencies = []
            elif domain in {"REFEREE", "RIVALRY", "STYLE_MATCHUP"}:
                canonical_domain, task_type, caps = domain, "FACT_COLLECTION", ["SEARCH", "CRAWL"]
                description = f"Analyzuj {domain.lower()} v kontextu {match_identity.home_team} vs {match_identity.away_team}."
                dependencies = [f"TASK-{match_identity.match_id}-{away_profile}"] if domain != "REFEREE" else []
            else:
                canonical_domain, task_type, caps = domain, "FACT_COLLECTION", ["SEARCH", "CRAWL"]
                description = f"Zjisti doplňující informace pro {domain}."
                dependencies = []

            tasks.append(TaskRequirement(
                task_uuid=f"TASK-{match_identity.match_id}-{canonical_domain}",
                domain=canonical_domain, task_type=task_type, description=description,
                priority=ResearchPolicy.DOMAIN_PRIORITIES.get(domain, 50),
                required=domain in ResearchPolicy.REQUIRED_DOMAINS,
                capabilities_required=caps, depends_on=dependencies,
                subject_team_id=(match_identity.home_team_id if domain.endswith("_HOME")
                                 else match_identity.away_team_id if domain.endswith("_AWAY") else None),
            ))
        # TODO 3.2: STATISTICS čeká na research domény (jen na terminální stav, ne úspěch;
        # zaseklé joby ukončí recovery timeoutem), aby ResearchContextMapper viděl jejich snapshoty.
        stat_task = next((t for t in tasks if t.domain == "STATISTICS"), None)
        if stat_task is not None:
            stat_task.depends_on = [
                t.task_uuid for t in tasks
                if t is not stat_task and t.domain not in (home_profile, away_profile)
            ]
        return tasks
