from typing import List
from app.orchestrator.models import MatchIdentity, TaskRequirement
from app.orchestrator.policies import ResearchPolicy


class ResearchPlanner:
    def create_plan(self, match_identity: MatchIdentity) -> List[TaskRequirement]:
        tasks = []

        # Procházíme povinné i volitelné oblasti
        all_domains = [(d, True) for d in ResearchPolicy.REQUIRED_DOMAINS] + [(d, False) for d in ResearchPolicy.OPTIONAL_DOMAINS]

        # Sloučení statistických domén (FORM_HOME, FORM_AWAY, STATISTICS, HEAD_TO_HEAD)
        # do jediné kanonické STATISTICS úlohy pro daný běh
        stat_domains_seen = False

        for domain, is_required in all_domains:
            priority = ResearchPolicy.DOMAIN_PRIORITIES.get(domain, 50)
            if domain in ["FORM_HOME", "FORM_AWAY", "STATISTICS", "HEAD_TO_HEAD"]:
                if stat_domains_seen:
                    # Přeskočit vytváření dalších identických STATISTICS úloh pro stejný run
                    continue
                stat_domains_seen = True
                task_type = "STAT_COLLECTION"
                caps = ["STATISTICS"]
                cutoff_str = match_identity.data_cutoff_at.isoformat() if match_identity.data_cutoff_at else "N/A"
                desc = f"Získej statistická data a výpočet formy pro zápas před časem {cutoff_str}."
                canonical_domain = "STATISTICS"
            elif domain in ["ABSENCES_HOME", "ABSENCES_AWAY", "EXPECTED_LINEUPS"]:
                task_type = "NEWS_COLLECTION"
                caps = ["SEARCH", "CRAWL"]
                cutoff_str = match_identity.data_cutoff_at.isoformat() if match_identity.data_cutoff_at else "N/A"
                desc = f"Získej aktuální novinky a absence pro {domain} před časem {cutoff_str}."
                canonical_domain = domain
            else:
                task_type = "FACT_COLLECTION"
                caps = ["SEARCH", "CRAWL"]
                desc = f"Získej doplňující informace pro {domain}."
                canonical_domain = domain

            task_uuid = f"TASK-{match_identity.match_id}-{canonical_domain}"
            tasks.append(
                TaskRequirement(
                    task_uuid=task_uuid,
                    domain=canonical_domain,
                    task_type=task_type,
                    description=desc,
                    priority=priority,
                    required=is_required,
                    capabilities_required=caps,
                    depends_on=[]
                )
            )

        return tasks
