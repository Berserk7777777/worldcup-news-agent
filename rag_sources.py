from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class SourceConfig:
    key: str
    level: str
    name: str
    language: str
    source_type: str
    seed_url: str
    purpose: str

    @property
    def domain(self) -> str:
        return urlparse(self.seed_url).hostname or ""


SOURCES = [
    SourceConfig(
        "fifa_world_cup",
        "A",
        "FIFA 世界杯官网",
        "en",
        "official",
        "https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026/news",
        "赛程、比分、阵容、官方统计和球员背景",
    ),
    SourceConfig(
        "fifa_media",
        "A",
        "FIFA 新闻稿",
        "en",
        "official",
        "https://inside.fifa.com/organisation/media/all-media-releases",
        "规则、赛事公告、官方数据和赛事影响",
    ),
    SourceConfig(
        "us_soccer",
        "A",
        "美国足协",
        "en",
        "federation",
        "https://www.ussoccer.com/teams/usmnt/stories",
        "美国队阵容、备战和赛后信息",
    ),
    SourceConfig(
        "canada_soccer",
        "A",
        "加拿大足协",
        "en",
        "federation",
        "https://news.canadasoccer.com/",
        "加拿大队阵容、备战和官方新闻",
    ),
    SourceConfig(
        "mexico_soccer",
        "A",
        "墨西哥足协",
        "es",
        "federation",
        "https://miseleccion.mx/noticias",
        "墨西哥队阵容、备战和官方新闻",
    ),
    SourceConfig(
        "uefa",
        "A",
        "UEFA",
        "en",
        "confederation",
        "https://www.uefa.com/european-qualifiers/news/",
        "欧洲区预选赛和球队资料",
    ),
    SourceConfig(
        "conmebol",
        "A",
        "CONMEBOL",
        "es",
        "confederation",
        "https://www.conmebol.com/noticias/",
        "南美区预选赛和球队资料",
    ),
    SourceConfig(
        "concacaf",
        "A",
        "CONCACAF",
        "en",
        "confederation",
        "https://www.concacaf.com/en/world-cup-qualifying-men/",
        "中北美及加勒比区预选赛和球队资料",
    ),
    SourceConfig(
        "afc",
        "A",
        "AFC",
        "en",
        "confederation",
        "https://www.the-afc.com/en/national/asian_qualifiers.html",
        "亚洲区预选赛和球队资料",
    ),
    SourceConfig(
        "caf",
        "A",
        "CAF",
        "en",
        "confederation",
        "https://www.cafonline.com/fifa-world-cup/news/",
        "非洲区预选赛和球队资料",
    ),
    SourceConfig(
        "ofc",
        "A",
        "OFC",
        "en",
        "confederation",
        "https://www.oceaniafootball.com/category/fifa-world-cup-2026/",
        "大洋洲区预选赛和球队资料",
    ),
    SourceConfig(
        "atlanta_host",
        "A",
        "Atlanta World Cup Host Committee",
        "en",
        "host_city",
        "https://atlantafwc26.com/newsroom/",
        "亚特兰大交通、城市活动和经济影响",
    ),
    SourceConfig(
        "toronto_host",
        "A",
        "Toronto FIFA World Cup 26",
        "en",
        "host_city",
        "https://torontofwc26.ca/en",
        "多伦多交通、城市活动和公共服务",
    ),
    SourceConfig(
        "vancouver_host",
        "A",
        "Vancouver FIFA World Cup 26",
        "en",
        "host_city",
        "https://www.vancouverfwc26.ca/news",
        "温哥华交通、城市活动和公共服务",
    ),
    SourceConfig(
        "nynj_host",
        "A",
        "New York New Jersey Host Committee",
        "en",
        "host_city",
        "https://nynjfwc26.com/news/",
        "纽约新泽西主办活动、交通和赛后信息",
    ),
    SourceConfig(
        "statcan",
        "A",
        "加拿大统计局",
        "en",
        "statistics",
        "https://www.statcan.gc.ca/en/subjects-start/travel_and_tourism",
        "旅游、住宿、消费和就业数据",
    ),
    SourceConfig(
        "us_ntto",
        "A",
        "美国国家旅游办公室",
        "en",
        "statistics",
        "https://www.trade.gov/national-travel-and-tourism-office",
        "美国旅游、国际访客和消费数据",
    ),
    SourceConfig(
        "inegi",
        "A",
        "墨西哥国家统计局 INEGI",
        "es",
        "statistics",
        "https://www.inegi.org.mx/temas/turismo/",
        "墨西哥旅游、消费和就业数据",
    ),
    SourceConfig(
        "xinhua",
        "B",
        "新华网体育",
        "zh",
        "media",
        "https://www.news.cn/sports/news.htm",
        "中文赛事报道、赛后采访和现场信息",
    ),
    SourceConfig(
        "cctv",
        "B",
        "央视体育",
        "zh",
        "media",
        "https://sports.cctv.com/football/index.shtml",
        "中文赛事报道、视频新闻和评论",
    ),
    SourceConfig(
        "people",
        "B",
        "人民网体育",
        "zh",
        "media",
        "http://sports.people.com.cn/",
        "中文赛事报道和背景信息",
    ),
    SourceConfig(
        "chinanews",
        "B",
        "中国新闻网体育",
        "zh",
        "media",
        "https://www.chinanews.com.cn/sports/",
        "中文赛事报道和现场采访",
    ),
    SourceConfig(
        "ap",
        "B",
        "Associated Press",
        "en",
        "media",
        "https://apnews.com/hub/soccer",
        "国际赛事报道、采访和背景分析",
    ),
    SourceConfig(
        "bbc",
        "B",
        "BBC Sport",
        "en",
        "media",
        "https://www.bbc.com/sport/football",
        "国际赛事报道、球队和球员背景",
    ),
    SourceConfig(
        "reuters",
        "B",
        "Reuters",
        "en",
        "media",
        "https://www.reuters.com/sports/soccer/",
        "国际赛事、商业和主办城市经济报道",
    ),
]


def sources_for_query(query: str, limit: int = 6) -> list[SourceConfig]:
    economy = any(
        word in query
        for word in ["经济", "城市", "旅游", "酒店", "消费", "交通", "就业", "主办"]
    )
    preferred_types = (
        {"host_city", "statistics", "official", "media"}
        if economy
        else {"official", "federation", "confederation", "media"}
    )
    preferred = [source for source in SOURCES if source.source_type in preferred_types]
    return preferred[:limit]
