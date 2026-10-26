"""球隊中文名稱與代表色。

顏色會再經過 led_color() 提亮，避免深藍、深綠在 LED 上看不清楚。
找不到的球隊會用 fallback_short_name() 自動縮短，也可以在 config.yaml 的 aliases 覆寫。
"""

from __future__ import annotations

import re


def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def led_color(rgb: tuple[int, int, int], min_peak: int = 190) -> tuple[int, int, int]:
    """把顏色等比例放大到最亮通道至少 min_peak，暗色在點陣上才看得到。"""
    peak = max(rgb)
    if peak == 0:
        return (min_peak, min_peak, min_peak)
    if peak >= min_peak:
        return rgb
    k = min_peak / peak
    return tuple(min(255, int(c * k)) for c in rgb)  # type: ignore[return-value]


# MLB：statsapi team id -> (縮寫, 中文, 顏色)
MLB_TEAMS: dict[int, tuple[str, str, str]] = {
    108: ("LAA", "天使", "#BA0021"),
    109: ("ARI", "響尾蛇", "#A71930"),
    110: ("BAL", "金鶯", "#DF4601"),
    111: ("BOS", "紅襪", "#BD3039"),
    112: ("CHC", "小熊", "#3D6BD6"),
    113: ("CIN", "紅人", "#C6011F"),
    114: ("CLE", "守護者", "#E31937"),
    115: ("COL", "洛磯", "#8B74C4"),
    116: ("DET", "老虎", "#FA4616"),
    117: ("HOU", "太空人", "#EB6E1F"),
    118: ("KC", "皇家", "#4F8FDB"),
    119: ("LAD", "道奇", "#1E7FD6"),
    120: ("WSH", "國民", "#D3122B"),
    121: ("NYM", "大都會", "#FF5910"),
    133: ("ATH", "運動家", "#EFB21E"),
    134: ("PIT", "海盜", "#FDB827"),
    135: ("SD", "教士", "#FFC425"),
    136: ("SEA", "水手", "#00B2A9"),
    137: ("SF", "巨人", "#FD5A1E"),
    138: ("STL", "紅雀", "#C41E3A"),
    139: ("TB", "光芒", "#8FBCE6"),
    140: ("TEX", "遊騎兵", "#3A6FD8"),
    141: ("TOR", "藍鳥", "#3B7DD8"),
    142: ("MIN", "雙城", "#D31145"),
    143: ("PHI", "費城人", "#E81828"),
    144: ("ATL", "勇士", "#CE1141"),
    145: ("CWS", "白襪", "#C4CED4"),
    146: ("MIA", "馬林魚", "#00A3E0"),
    147: ("NYY", "洋基", "#5B7FD1"),
    158: ("MIL", "釀酒人", "#FFC52F"),
}

# NBA：標準縮寫 -> (中文, 顏色)
NBA_TEAMS: dict[str, tuple[str, str]] = {
    "ATL": ("老鷹", "#E03A3E"),
    "BOS": ("塞爾提克", "#18A050"),
    "BKN": ("籃網", "#DDDDDD"),
    "CHA": ("黃蜂", "#00A3B4"),
    "CHI": ("公牛", "#CE1141"),
    "CLE": ("騎士", "#C0204F"),
    "DAL": ("獨行俠", "#1E7FD6"),
    "DEN": ("金塊", "#FEC524"),
    "DET": ("活塞", "#C8102E"),
    "GSW": ("勇士", "#FFC72C"),
    "HOU": ("火箭", "#CE1141"),
    "IND": ("溜馬", "#FDBB30"),
    "LAC": ("快艇", "#C8102E"),
    "LAL": ("湖人", "#FDB927"),
    "MEM": ("灰熊", "#6F8DCC"),
    "MIA": ("熱火", "#D0103A"),
    "MIL": ("公鹿", "#3FA34D"),
    "MIN": ("灰狼", "#78BE20"),
    "NOP": ("鵜鶘", "#C8A45A"),
    "NYK": ("尼克", "#F58426"),
    "OKC": ("雷霆", "#007AC1"),
    "ORL": ("魔術", "#0077C0"),
    "PHI": ("七六人", "#1E7FD6"),
    "PHX": ("太陽", "#E56020"),
    "POR": ("拓荒者", "#E03A3E"),
    "SAC": ("國王", "#8A5BC8"),
    "SAS": ("馬刺", "#C4CED4"),
    "TOR": ("暴龍", "#CE1141"),
    "UTA": ("爵士", "#9B6BE0"),
    "WAS": ("巫師", "#E31837"),
}

# ESPN 用的縮寫和 NBA 官方不同，統一轉成官方縮寫
ESPN_NBA_ABBR = {"GS": "GSW", "NO": "NOP", "NY": "NYK", "SA": "SAS", "UTAH": "UTA", "WSH": "WAS"}

# 台灣聯盟：用關鍵字比對官方回傳的中文隊名 -> (代碼, 中文短名, 顏色)
CPBL_TEAMS: list[tuple[str, str, str, str]] = [
    ("中信", "CTBC", "中信", "#FFD200"),
    ("兄弟", "CTBC", "中信", "#FFD200"),
    ("味全", "WCD", "味全", "#FF2A2A"),
    ("統一", "UNI", "統一", "#FF8A00"),
    ("樂天", "RKM", "樂天", "#E0305A"),
    ("富邦", "FBG", "富邦", "#3D7BF0"),
    ("台鋼", "TSG", "台鋼", "#20C080"),
]

TPBL_TEAMS: list[tuple[str, str, str, str]] = [
    ("國王", "KINGS", "國王", "#9B6BFF"),
    ("戰神", "MARS", "戰神", "#FF3040"),
    ("攻城獅", "LIONEERS", "攻城獅", "#FF7A1A"),
    ("雲豹", "LEOPARDS", "雲豹", "#1EA8F0"),
    ("夢想家", "DREAMERS", "夢想家", "#FFA21A"),
    ("海神", "AQUAS", "海神", "#20B8E8"),
    ("特攻", "DEA", "特攻", "#FFD200"),
]

PLG_TEAMS: list[tuple[str, str, str, str]] = [
    ("勇士", "BRAVES", "勇士", "#3D7BF0"),
    ("領航猿", "PILOTS", "領航猿", "#20C0A0"),
    ("洋基", "YANKEY", "洋基", "#FF5A3A"),
]

_CITY_PREFIX = re.compile(r"^(臺北|台北|新北|桃園|新竹|臺中|台中|臺南|台南|高雄|基隆|福爾摩沙)")


def fallback_short_name(full: str, max_chars: int = 3) -> str:
    name = _CITY_PREFIX.sub("", full.strip())
    return name[-max_chars:] if len(name) > max_chars else name


def match_tw_team(table, full: str, aliases: dict[str, str] | None = None):
    """回傳 (code, short, color)。"""
    if aliases and full in aliases:
        short = aliases[full]
    else:
        short = None
    for kw, code, zh, color in table:
        if kw in full:
            return code, short or zh, led_color(hex_rgb(color))
    s = short or fallback_short_name(full)
    return s, s, (230, 230, 230)


def mlb_team(team_id: int, fallback_name: str = ""):
    if team_id in MLB_TEAMS:
        abbr, zh, color = MLB_TEAMS[team_id]
        return abbr, zh, led_color(hex_rgb(color))
    return fallback_name[:3].upper(), fallback_name[:6], (230, 230, 230)


def nba_team(espn_abbr: str, fallback_name: str = ""):
    abbr = ESPN_NBA_ABBR.get(espn_abbr, espn_abbr)
    if abbr in NBA_TEAMS:
        zh, color = NBA_TEAMS[abbr]
        return abbr, zh, led_color(hex_rgb(color))
    return abbr, fallback_name[:6] or abbr, (230, 230, 230)
