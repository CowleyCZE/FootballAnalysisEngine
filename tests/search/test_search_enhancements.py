import unittest
from datetime import datetime
from app.search.models import SearchResult
from app.search.sport_filter import is_football_content, filter_sports_results
from app.search.relevance import calculate_relevance, calculate_identity_confidence

class TestSearchEnhancements(unittest.TestCase):
    def test_sport_filter_accepts_football(self):
        res = SearchResult(
            title="Arsenal vs Chelsea Match Analysis",
            content="Striker scored two goals in a thrilling premier league derby",
            url="https://football-news.com/match"
        )
        self.assertTrue(is_football_content(res))

    def test_sport_filter_rejects_basketball(self):
        res = SearchResult(
            title="Lakers beat Celtics in NBA finals",
            content="Basketball star score 40 points on court",
            url="https://sports.com/nba"
        )
        self.assertFalse(is_football_content(res))

    def test_youth_filtering_penalty(self):
        res = SearchResult(
            title="Arsenal U19 vs Chelsea U19 derby",
            content="Youth players played well in under-19 cup",
            url="https://football-news.com/u19"
        )
        score = calculate_relevance(res, "Arsenal", home_team="Arsenal", away_team="Chelsea")
        self.assertEqual(score, 0.0)

    def test_identity_confidence_calculation(self):
        res = SearchResult(
            title="Real Madrid vs Barcelona La Liga 2026 preview",
            content="Real Madrid host Barcelona at Santiago Bernabeu",
            url="https://football.com/elclasico"
        )
        cutoff = datetime(2026, 10, 15, 20, 0)
        conf = calculate_identity_confidence(
            res, home_team="Real Madrid", away_team="Barcelona", competition="La Liga", scheduled_at=cutoff
        )
        self.assertGreaterEqual(conf, 0.8)

    def test_relevance_freshness(self):
        cutoff = datetime(2026, 10, 1, 12, 0, 0)
        recent_res = SearchResult(
            title="Arsenal squad news",
            content="Team tactics for upcoming match",
            url="https://news.com",
            published_at="2026-09-28T10:00:00"
        )
        old_res = SearchResult(
            title="Arsenal squad news",
            content="Team tactics for upcoming match",
            url="https://news.com",
            published_at="2025-01-01T10:00:00"
        )
        recent_score = calculate_relevance(recent_res, "Arsenal", ["tactics"], data_cutoff_at=cutoff)
        old_score = calculate_relevance(old_res, "Arsenal", ["tactics"], data_cutoff_at=cutoff)

        self.assertGreater(recent_score, old_score)

if __name__ == "__main__":
    unittest.main()
