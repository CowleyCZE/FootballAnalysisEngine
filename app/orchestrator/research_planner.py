from typing import List
from app.orchestrator.models import MatchIdentity, TaskRequirement
from app.orchestrator.policies import ResearchPolicy

class ResearchPlanner:
    def create_plan(self, match_identity: MatchIdentity) -> List[TaskRequirement]:
        tasks = []
        
        # Procházíme povinné i volitelné oblasti
        all_domains = [(d, True) for d in ResearchPolicy.REQUIRED_DOMAINS] + [(d, False) for d in ResearchPolicy.OPTIONAL_DOMAINS]

        for domain, is_required in all_domains:
            priority = ResearchPolicy.DOMAIN_PRIORITIES.get(domain, 50)
            
            # Stanovení typu a nároků podle domény
            if domain == "MATCH_IDENTITY":
                task_type = "FACT_COLLECTION"
                caps = []
                desc = f"Ověř identitu zápasu #{match_identity.match_id}."
            elif domain in ["FORM_HOME", "FORM_AWAY", "STATISTICS", "HEAD_TO_HEAD"]:
                task_type = "STAT_COLLECTION"
                caps = []
                desc = f"Získej statistická data pro doménu {domain} před časem {match_identity.data_cutoff_at.isoformat()}."
            elif domain in ["ABSENCES_HOME", "ABSENCES_AWAY", "EXPECTED_LINEUPS"]:
                task_type = "NEWS_COLLECTION"
                caps = []
                desc = f"Získej aktuální novinky a absence pro {domain} před časem {match_identity.data_cutoff_at.isoformat()}."
            else:
                task_type = "FACT_COLLECTION"
                caps = ["http_fetch"]
                desc = f"Získej doplňující informace pro {domain}."

            task_uuid = f"TASK-{match_identity.match_id}-{domain}"
            tasks.append(
                TaskRequirement(
                    task_uuid=task_uuid,
                    domain=domain,
                    task_type=task_type,
                    description=desc,
                    priority=priority,
                    required=is_required,
                    capabilities_required=caps
                )
            )

        return tasks