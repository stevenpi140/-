from datetime import date

from scoreboard.aggregator import Aggregator
from scoreboard.config import Config


def cfg_with(**season):
    c = Config.load(None)
    c.raw["season"] = {**c.raw["season"], **season}
    return c


def test_default_seasons():
    c = Config.load(None)
    assert c.active_sports(date(2026, 10, 26)) == ["basketball"]  # 現在：只有籃球
    assert c.active_sports(date(2026, 1, 15)) == ["basketball"]
    assert c.active_sports(date(2026, 7, 15)) == ["baseball"]  # 夏天：只有棒球
    assert c.active_sports(date(2026, 4, 10)) == ["baseball", "basketball"]  # 重疊：全部輪播
    assert c.active_sports(date(2026, 10, 5)) == ["baseball", "basketball"]


def test_manual_mode():
    assert cfg_with(mode="baseball").active_sports(date(2026, 12, 1)) == ["baseball"]
    assert cfg_with(mode="all").active_sports(date(2026, 12, 1)) == ["baseball", "basketball"]


def test_aggregator_only_active_leagues():
    agg = Aggregator(Config.load(None))
    keys = {s.league.key for s in agg.active_states(date(2026, 10, 26))}
    assert keys == {"nba", "tpbl", "plg"}
    keys = {s.league.key for s in agg.active_states(date(2026, 7, 1))}
    assert keys == {"cpbl", "mlb"}
