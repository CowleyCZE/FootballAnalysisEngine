import re
from typing import List, Dict, Any, Optional
from app.research.models import Evidence


_DOMAIN_KEYWORDS = {
    "ABSENCES_HOME": ["injured", "injury", "miss", "unavailable", "ruled out", "doubt", "suspended", "sidelined", "fitness", "knock", "hamstring", "acl"],
    "ABSENCES_AWAY": ["injured", "injury", "miss", "unavailable", "ruled out", "doubt", "suspended", "sidelined", "fitness", "knock", "hamstring", "acl"],
    "FORM_HOME": ["win", "won", "loss", "lost", "draw", "drew", "streak", "form", "unbeaten", "scored", "conceded", "points", "recent"],
    "FORM_AWAY": ["win", "won", "loss", "lost", "draw", "drew", "streak", "form", "unbeaten", "scored", "conceded", "points", "recent"],
    "STATISTICS": ["xg", "possession", "shots", "corners", "goals", "clean sheet", "pass accuracy", "tackles", "cards", "stats", "average"],
    "HEAD_TO_HEAD": ["head to head", "h2h", "previous meeting", "last meeting", "historic", "against each other", "record"],
    "EXPECTED_LINEUPS": ["lineup", "predicted", "starting xi", "formation", "probable", "squad", "bench", "xi", "4-3-3", "4-2-3-1", "3-5-2"],
    "WEATHER": ["weather", "rain", "temperature", "degrees", "celsius", "wind", "pitch", "forecast", "condition", "humidity", "storm"],
    "REFEREE": ["referee", "official", "cards", "fouls", "penalt", "rozhodčí", "karty", "fauly"],
    "RIVALRY": ["derby", "rivalry", "historic", "intensity", "cards", "rivalita", "derby"],
    "STYLE_MATCHUP": ["tactic", "tactical", "pressing", "possession", "transition", "counter", "set piece", "formation", "taktika"],
    "MOTIVATION_HOME": ["table", "position", "qualification", "relegation", "objective", "motivation", "rotation", "tabulka", "motivace"],
    "MOTIVATION_AWAY": ["table", "position", "qualification", "relegation", "objective", "motivation", "rotation", "tabulka", "motivace"],
    "TRAVEL_FATIGUE_HOME": ["fixture congestion", "rest days", "travel", "rotation", "fatigue", "schedule", "odpočinek", "únava", "cestování"],
    "TRAVEL_FATIGUE_AWAY": ["fixture congestion", "rest days", "travel", "rotation", "fatigue", "schedule", "odpočinek", "únava", "cestování"],
}

# České kmeny (počítá se s ohybáním, shoda je podle podyřetězce na lower-case větě) – TODO 3.4.
_CZECH_KEYWORDS = {
    "ABSENCES": ["zraněn", "zranění", "zranil", "marod", "chybí", "chybět", "nenastoup", "neodehraj", "nebude k dispozici", "pochybn", "suspend", "distanc", "vyřazen", "absenc", "sval", "křížové vazy"],
    "FORM": ["výhr", "vyhrál", "prohr", "remíz", "série", "neporaz", "forma", "formě", "gól", "inkasoval", "bodů", "poslední zápas", "posledních"],
    "STATISTICS": ["držení míče", "střel", "rohov", "gólů", "čisté konto", "přesnost přihrávek", "karty", "průměr", "statistik"],
    "HEAD_TO_HEAD": ["vzájemn", "předchozí zápas", "poslední zápas", "bilanc", "minulý zápas", "vzájemného", "proti sobě"],
    "EXPECTED_LINEUPS": ["sestav", "základní úderní", "základní jedenáctí", "pravděpodobná", "formační", "střídačk", "úderní sestav", "nastoupí"],
    "WEATHER": ["počasí", "déšť", "dešt", "teplot", "stupň", "vítr", "předpověď", "bouř", "trávník", "sníž", "mlha"],
    "REFEREE": ["rozhodčí", "hlavní rozhodčí", "žluté karty", "červené karty", "penalt", "faul", "pišťalš"],
    "RIVALRY": ["derby", "rivalit", "prestiž", "vyhrocen", "atmosfér"],
    "STYLE_MATCHUP": ["taktik", "presink", "pressing", "protiútok", "standardní situac", "formační", "styl hry", "ofenziv", "defenziv"],
    "MOTIVATION": ["tabulk", "pozic", "záchran", "sestup", "postup", "boj o", "motivac", "rotac", "pohár", "evropské poháry", "titul"],
    "TRAVEL_FATIGUE": ["únav", "odpočin", "cestován", "cestě", "nabitý program", "hustý program", "rotac", "program zápasů", "dnů pauzy", "dnů odpočinku"],
}


def _czech_keywords_for(domain: str) -> List[str]:
    for prefix, words in _CZECH_KEYWORDS.items():
        if domain == prefix or domain.startswith(prefix + "_"):
            return words
    return []


def keywords_for_domain(domain: str) -> List[str]:
    """Anglické i české klíčové fráze domény (bez duplicit, pořadí zachováno)."""
    merged = list(_DOMAIN_KEYWORDS.get(domain, [])) + _czech_keywords_for(domain)
    return list(dict.fromkeys(merged))


class EvidenceExtractor:
    def extract_evidence(self, doc: Dict[str, Any], domain: str) -> List[Evidence]:
        text = doc.get("text", "")
        url = doc.get("url", "")
        pub_at = doc.get("published_at")
        retrieved_at = doc.get("retrieved_at")
        canonical_url = doc.get("canonical_url") or url
        content_hash = doc.get("content_hash")
        doc_id = doc.get("document_id")

        if not text:
            return []

        evidence_list = []
        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+|\n+', text) if len(s.strip()) > 15]
        keywords = keywords_for_domain(domain)

        for sent in sentences:
            sent_lower = sent.lower()
            if keywords:
                if any(kw in sent_lower for kw in keywords):
                    evidence_list.append(Evidence(
                        source_url=url,
                        text_fragment=sent,
                        document_id=doc_id,
                        published_at=pub_at,
                        retrieved_at=retrieved_at,
                        canonical_url=canonical_url,
                        content_hash=content_hash,
                        domain=domain
                    ))
            else:
                evidence_list.append(Evidence(
                    source_url=url,
                    text_fragment=sent,
                    document_id=doc_id,
                    published_at=pub_at,
                    retrieved_at=retrieved_at,
                    canonical_url=canonical_url,
                    content_hash=content_hash,
                    domain=domain
                ))

        if not evidence_list and sentences:
            first_fragment = " ".join(sentences[:3])
            evidence_list.append(Evidence(
                source_url=url,
                text_fragment=first_fragment[:500],
                document_id=doc_id,
                published_at=pub_at,
                retrieved_at=retrieved_at,
                canonical_url=canonical_url,
                content_hash=content_hash,
                domain=domain
            ))

        return evidence_list
