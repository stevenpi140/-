"""解析器測試。樣本是依各來源已知欄位手寫的最小 JSON / HTML，不是真實比賽資料。"""

from datetime import date, datetime, timedelta

from scoreboard.config import Config
from scoreboard.leagues import cpbl, mlb, nba, plg, tpbl

CFG = Config.load(None)
DAY = date(2026, 10, 26)


def test_mlb_live_and_filters_by_taipei_date():
    data = {
        "dates": [
            {
                "games": [
                    {
                        "gamePk": 1,
                        "gameDate": "2026-10-26T00:08:00Z",  # 台灣 10/26 08:08
                        "gameType": "W",
                        "seriesGameNumber": 3,
                        "status": {"abstractGameState": "Live", "codedGameState": "I", "detailedState": "In Progress"},
                        "teams": {
                            "away": {"team": {"id": 119, "name": "Los Angeles Dodgers"}, "score": 3},
                            "home": {"team": {"id": 141, "name": "Toronto Blue Jays"}, "score": 2},
                        },
                        "linescore": {
                            "currentInning": 7, "isTopInning": False, "inningState": "Bottom", "outs": 1,
                            "offense": {"first": {"id": 1}, "third": {"id": 2}},
                        },
                        "venue": {"name": "Rogers Centre"},
                    },
                    {
                        "gamePk": 2,
                        "gameDate": "2026-10-25T00:08:00Z",  # 台灣 10/25，應被排除
                        "status": {"abstractGameState": "Final"},
                        "teams": {"away": {"team": {"id": 147}}, "home": {"team": {"id": 111}}},
                    },
                ]
            }
        ]
    }
    games = mlb.parse(data, CFG, DAY)
    assert len(games) == 1
    g = games[0]
    assert (g.away.name, g.home.name) == ("道奇", "藍鳥")
    assert (g.away.score, g.home.score) == (3, 2)
    assert g.state == "live" and g.status_text() == "7局下"
    assert g.bases == (True, False, True) and g.outs == 1
    assert g.label == "世界大賽G3"


def test_mlb_end_of_inning_shows_next_half():
    data = {"dates": [{"games": [{
        "gamePk": 3, "gameDate": "2026-10-26T00:00:00Z",
        "status": {"abstractGameState": "Live"},
        "teams": {"away": {"team": {"id": 119}, "score": 0}, "home": {"team": {"id": 141}, "score": 0}},
        "linescore": {"currentInning": 4, "isTopInning": False, "inningState": "End"},
    }]}]}
    g = mlb.parse(data, CFG, DAY)[0]
    assert g.status_text() == "5局上"


def test_nba_espn():
    data = {
        "events": [
            {
                "id": "401",
                "date": "2026-10-26T02:30Z",
                "competitions": [
                    {
                        "status": {"period": 3, "displayClock": "5:21", "type": {"state": "in", "name": "STATUS_IN_PROGRESS"}},
                        "competitors": [
                            {"homeAway": "home", "score": "91", "team": {"abbreviation": "LAL"}},
                            {"homeAway": "away", "score": "88", "team": {"abbreviation": "GS"}},
                        ],
                    }
                ],
            }
        ]
    }
    g = nba.parse(data, CFG, DAY)[0]
    assert (g.away.code, g.away.name, g.away.score) == ("GSW", "勇士", 88)
    assert g.status_text() == "Q3 5:21"


def test_cpbl_rows():
    rows = [
        {
            "GameSno": 6, "GameDate": "2026-10-26T00:00:00", "PreExeDate": "2026-10-26T18:35:00",
            "VisitingTeamName": "中信兄弟", "HomeTeamName": "味全龍",
            "VisitingFirstMover": "勝騎士", "HomeFirstMover": "梅賽德",
            "FieldAbbe": "大巨蛋", "GameStatus": 1,
        },
        {"GameSno": 5, "GameDate": "2026-10-25T00:00:00", "PreExeDate": "2026-10-25T18:35:00",
         "VisitingTeamName": "味全龍", "HomeTeamName": "中信兄弟", "GameStatus": 3},
    ]
    games = cpbl.parse_rows(rows, "C", CFG, DAY)
    assert len(games) == 1
    g = games[0]
    assert g.state == "pre" and g.label == "總冠軍賽G6"
    assert (g.away.name, g.home.name) == ("中信", "味全")
    assert g.away.pitcher == "勝騎士"
    assert g.start.hour == 18 and g.start.minute == 35


def test_cpbl_gamedatas_string_and_token():
    assert cpbl.decode_list({"Success": True, "GameDatas": '[{"GameSno": 1}]'}) == [{"GameSno": 1}]
    html = "headers: { RequestVerificationToken: 'abcDEF1234567890abcDEF1234567890' }"
    assert cpbl.find_token(html) == "abcDEF1234567890abcDEF1234567890"


def test_cpbl_live_scoreboard():
    g = cpbl.parse_rows([{"GameSno": 1, "PreExeDate": "2026-10-26T18:35:00", "VisitingTeamName": "樂天桃猿",
                          "HomeTeamName": "統一7-ELEVEn獅", "GameStatus": 2, "VisitingScore": 1, "HomeScore": 0}],
                        "A", CFG, DAY)[0]
    cpbl.apply_live(g, {"ScoreboardJson": '[{"InningSeq":1,"VisitingHomeType":1,"ScoreCnt":1},'
                                          '{"InningSeq":1,"VisitingHomeType":2,"ScoreCnt":0},'
                                          '{"InningSeq":2,"VisitingHomeType":1,"ScoreCnt":2}]'})
    assert g.status_text() == "2局上"
    assert (g.away.score, g.home.score) == (3, 0)


def test_tpbl():
    rows = [{
        "id": 77, "game_date": "2026-10-26", "game_time": "17:00:00", "status": "COMPLETED",
        "home_team": {"name": "新北國王", "won_score": 101}, "away_team": {"name": "新竹御嵿攻城獅", "won_score": 99},
    }]
    g = tpbl.parse(rows, CFG, DAY)[0]
    assert g.state == "final" and (g.away.name, g.home.name) == ("攻城獅", "國王")
    assert g.home.score == 101


def test_plg_schedule_html():
    html = """
    <div class="match_row d-2026-10 is-future">
      <div class="match_row_datetime"><h5>10/26</h5><h6>(一) 19:00</h6></div>
      <div class="text-black"><span class="PC_only">桃園璞園領航猿</span></div>
      <div class="text-black"><span class="PC_only">臺北富邦勇士</span></div>
      <h6 class="PC_only ff8bit">0</h6><h6 class="PC_only ff8bit">0</h6>
      <a href="/game/123">數據</a>
    </div>"""
    rows = plg.parse_schedule(html)
    assert rows[0]["id"] == "123" and rows[0]["date"] == DAY and rows[0]["time"] == (19, 0)
    before = datetime(2026, 10, 26, 12, tzinfo=CFG.tz)
    g = plg.to_game(rows[0], CFG, before)
    assert g.state == "pre" and (g.away.name, g.home.name) == ("領航猿", "勇士")
    during = before.replace(hour=19) + timedelta(minutes=30)
    assert plg.to_game(rows[0], CFG, during).state == "live"


def test_follow_filter():
    cfg = Config({**CFG.raw, "leagues": {**CFG.raw["leagues"], "mlb": {"enabled": True, "teams": ["LAD"]},
                                         "cpbl": {"enabled": True, "teams": ["中信"]}}})
    assert cfg.follows("mlb", "LAD")
    assert not cfg.follows("mlb", "NYY", "洋基")
    assert cfg.follows("cpbl", "CTBC", "中信", "中信兄弟")
    assert cfg.follows("nba", "BOS")  # 空清單 = 全部


def test_rebas_cpbl():
    from scoreboard.leagues import rebas

    rows = [
        {
            "uniqid": "A1", "group": "例行賽",
            "away": {"team": "富邦悍將", "runs": 6, "scores": ["5", "0", "1"], "scheduled_SP": None},
            "home": {"team": "樂天桃猿", "runs": 1, "scores": ["0", "0"], "scheduled_SP": None},
            "info": {"status": "PLAYING", "finished_status": "NORMAL", "scheduled_start_at": "2026-10-26 18:35",
                     "started_at": "2026-10-26 18:35", "ended_at": "", "location_abbr": "樂天桃園", "innings": 3},
        },
        {
            "uniqid": "A2", "group": "總冠軍賽",
            "away": {"team": "中信兄弟", "runs": 0, "scores": [], "scheduled_SP": "勝騎士"},
            "home": {"team": "味全龍", "runs": 0, "scores": [], "scheduled_SP": "梅賽德"},
            "info": {"status": "NOT_STARTED", "finished_status": "NORMAL", "scheduled_start_at": "2026-10-26 18:35",
                     "started_at": "", "ended_at": ""},
        },
        {"uniqid": "A3", "away": {}, "home": {}, "info": {"scheduled_start_at": "2026-10-25 18:35"}},
    ]
    games = rebas.parse(rows, CFG, DAY)
    assert len(games) == 2
    live, pre = games
    assert live.state == "live" and live.status_text() == "3局上"
    assert (live.away.name, live.away.score, live.home.name, live.home.score) == ("富邦", 6, "樂天", 1)
    assert live.venue == "樂天桃園" and live.label == ""
    assert pre.state == "pre" and pre.away.score is None
    assert pre.away.pitcher == "勝騎士" and pre.label == "總冠軍賽"


def test_tpbl_completed_without_status_update():
    rows = [{
        "id": 1, "game_date": "2026-10-24", "game_time": "14:30:00", "status": "SCHEDULED", "is_live": False,
        "home_team": {"name": "新竹御嵿攻城獅", "won_score": 100}, "away_team": {"name": "福爾摩沙夢想家", "won_score": 90},
    }]
    g = tpbl.parse(rows, CFG, date(2026, 10, 24))[0]
    assert g.state == "final" and g.home.score == 100


def test_rebas_picks_seasons_covering_day():
    from scoreboard.leagues import rebas

    seasons = [
        {"uniqid": "CPBL-2026-LU", "type": "POSTSEASON", "start_at": "2026-10-17T00:00:00+08:00",
         "end_at": "2026-10-28T00:00:00+08:00"},
        {"uniqid": "CPBL-2026-YQ", "type": "CHALLENGE", "start_at": "2026-10-09T00:00:00+08:00",
         "end_at": "2026-10-13T00:00:00+08:00"},
        {"uniqid": "CPBL-2026-oB", "type": "REGULAR", "start_at": "2026-03-28T00:00:00+08:00",
         "end_at": "2026-10-07T00:00:00+08:00"},
    ]
    assert rebas.seasons_for(seasons, DAY) == ["CPBL-2026-LU"]
    assert rebas.seasons_for(seasons, date(2026, 10, 8)) == ["CPBL-2026-YQ", "CPBL-2026-oB"]
    assert rebas.seasons_for(seasons, date(2026, 12, 1)) == []  # 休賽季：沒有比賽
