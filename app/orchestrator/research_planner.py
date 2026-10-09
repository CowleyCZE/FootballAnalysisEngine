from typing import List
from app.orchestrator.models import MatchIdentity, TaskRequirement
from app.orchestrator.policies import ResearchPolicy


class ResearchPlanner:
    def create_plan(self, match_identity: MatchIdentity) -> List[TaskRequirement]:
        tasks = []

        identity_task_uuid = f"TASK-{match_identity.match_id}-MATCH_IDENTITY"

        # Procházíme povinné i volitelné oblasti
        all_domains = [(d, True) for d in ResearchPolicy.REQUIRED_DOMAINS] + [(d, False) for d in ResearchPolicy.OPTIONAL_DOMAINS]

        for domain, is_required in all_domains:
            priority = ResearchPolicy.DOMAIN_PRIORITIES.get(domain, 50)
            deps = []

            # Stanovení typu a nároků podle domény
            if domain == "MATCH_IDENTITY":
                task_type = "FACT_COLLECTION"
                caps = ["SEARCH", "CRAWL"]
                desc = f"Ověř identitu zápasu #{match_identity.match_id}."
            elif domain in ["FORM_HOME", "FORM_AWAY", "STATISTICS", "HEAD_TO_HEAD"]:
                task_type = "STAT_COLLECTION"
                caps = ["STATISTICS"]
                desc = f"Získej statistická data pro doménu {domain} před časem {match_identity.data_cutoff_at.isoformat()}."
                deps = [identity_task_uuid]
            elif domain in ["ABSENCES_HOME", "ABSENCES_AWAY", "EXPECTED_LINEUPS"]:
                task_type = "NEWS_COLLECTION"
                caps = ["SEARCH", "CRAWL"]
                desc = f"Získej aktuální novinky a absence pro {domain} před časem {match_identity.data_cutoff_at.isoformat()}."
                deps = [identity_task_uuid]
            else:
                task_type = "FACT_COLLECTION"
                caps = ["SEARCH", "CRAWL"]
                desc = f"Získej doplňující informace pro {domain}."
                deps = [identity_task_uuid]

            task_uuid = f"TASK-{match_identity.match_id}-{domain}"
            tasks.append(
                TaskRequirement(
                    task_uuid=task_uuid,
                    domain=domain,
                    task_type=task_type,
                    description=desc,
                    priority=priority,
                    required=is_required,
                    capabilities_required=caps,
                    depends_on=deps
                )
            )

        return tasks
