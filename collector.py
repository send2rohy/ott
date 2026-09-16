import csv
import html
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser


# ============================================================
# 설정
# ============================================================

NETFLIX_TSV_URL = (
    "https://www.netflix.com/tudum/top10/data/all-weeks-countries.tsv"
)

NETFLIX_KR_MOVIE_URL = (
    "https://www.netflix.com/tudum/top10/south-korea"
)

NETFLIX_KR_TV_URL = (
    "https://www.netflix.com/tudum/top10/south-korea/tv"
)

DISNEY_URL = "https://www.disneyplus.com/ko-kr"

COUPANG_URL = "https://www.coupangplay.com/catalog"

COUNTRY_CODE = "KR"

KEEP_DAYS = 30

RANKING_FILE = "ranking.json"
HISTORY_FILE = "history.json"
TMDB_DETAIL_FILE = "tmdb.json"

# 새로 추가되는 영구 TMDB 검색/번역 캐시
TMDB_SEARCH_CACHE_FILE = "tmdb_cache.json"

TMDB_DETAIL_CACHE_DAYS = 7
TMDB_SEARCH_CACHE_DAYS = 30

TMDB_API_KEY = os.environ.get("TMDB_API_KEY")

TMDB_LANGUAGE = "ko-KR"
TMDB_REGION = "KR"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0 Safari/537.36"
)

REQUEST_TIMEOUT = 20


# ============================================================
# 전역 캐시
# ============================================================

TMDB_CACHE = {
    "search": {},
    "translation": {},
}


# ============================================================
# 공통 유틸
# ============================================================

def now_utc():
    return datetime.now(timezone.utc)


def iso_now():
    return now_utc().isoformat()


def parse_iso(value):
    if not value:
        return None

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def is_cache_fresh(value, days):
    dt = parse_iso(value)

    if not dt:
        return False

    return now_utc() - dt < timedelta(days=days)


def load_json(filename, default):
    if not os.path.exists(filename):
        return default

    try:
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(filename, data):
    tmp = filename + ".tmp"

    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(
                data,
                f,
                ensure_ascii=False,
                indent=2,
            )

        os.replace(tmp, filename)

    except Exception as e:
        print(f"[WARN] {filename} 저장 실패: {e}")


def normalize_title(value):
    if value is None:
        return ""

    value = html.unescape(str(value))
    value = value.lower()
    value = re.sub(r"[\u200b-\u200d\ufeff]", "", value)
    value = re.sub(r"[^0-9a-z가-힣]+", "", value)

    return value.strip()


def normalize_compare(value):
    if value is None:
        return ""

    value = html.unescape(str(value))
    value = value.lower()

    value = re.sub(
        r"[\u200b-\u200d\ufeff]",
        "",
        value,
    )

    value = re.sub(
        r"[^0-9a-z가-힣]+",
        " ",
        value,
    )

    value = re.sub(r"\s+", " ", value)

    return value.strip()


def has_korean(value):
    if not value:
        return False

    return bool(re.search(r"[가-힣]", str(value)))


def clean_title(value):
    if not value:
        return ""

    value = html.unescape(str(value))
    value = re.sub(r"[\u200b-\u200d\ufeff]", "", value)
    value = re.sub(r"\s+", " ", value)

    return value.strip(" \t\r\n|•·")


# ============================================================
# HTTP
# ============================================================

def fetch_text(url, timeout=REQUEST_TIMEOUT):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
        },
    )

    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read()

        charset = response.headers.get_content_charset()

        if not charset:
            charset = "utf-8"

        return raw.decode(charset, errors="replace")


def fetch_json(url, timeout=REQUEST_TIMEOUT):
    text = fetch_text(url, timeout=timeout)
    return json.loads(text)


# ============================================================
# TMDB 캐시
# ============================================================

def load_tmdb_cache():
    global TMDB_CACHE

    data = load_json(
        TMDB_SEARCH_CACHE_FILE,
        {},
    )

    if not isinstance(data, dict):
        TMDB_CACHE = {
            "search": {},
            "translation": {},
        }
        return

    TMDB_CACHE = {
        "search": data.get("search", {}),
        "translation": data.get("translation", {}),
    }

    if not isinstance(TMDB_CACHE["search"], dict):
        TMDB_CACHE["search"] = {}

    if not isinstance(TMDB_CACHE["translation"], dict):
        TMDB_CACHE["translation"] = {}

    print(
        "[TMDB CACHE] "
        f"검색 {len(TMDB_CACHE['search'])}개 / "
        f"번역 {len(TMDB_CACHE['translation'])}개"
    )


def save_tmdb_cache():
    save_json(
        TMDB_SEARCH_CACHE_FILE,
        TMDB_CACHE,
    )


def cleanup_tmdb_cache():
    cutoff = now_utc() - timedelta(
        days=TMDB_SEARCH_CACHE_DAYS
    )

    search_cache = TMDB_CACHE.get("search", {})

    remove_keys = []

    for key, value in search_cache.items():

        if not isinstance(value, dict):
            remove_keys.append(key)
            continue

        cached_at = parse_iso(
            value.get("cached_at")
        )

        if not cached_at or cached_at < cutoff:
            remove_keys.append(key)

    for key in remove_keys:
        search_cache.pop(key, None)

    translation_cache = TMDB_CACHE.get(
        "translation",
        {},
    )

    remove_keys = []

    for key, value in translation_cache.items():

        if not isinstance(value, dict):
            remove_keys.append(key)
            continue

        cached_at = parse_iso(
            value.get("cached_at")
        )

        if not cached_at or cached_at < cutoff:
            remove_keys.append(key)

    for key in remove_keys:
        translation_cache.pop(key, None)


# ============================================================
# TMDB API
# ============================================================

def tmdb_request(path, params=None):

    if not TMDB_API_KEY:
        return None

    if params is None:
        params = {}

    params = dict(params)

    params["api_key"] = TMDB_API_KEY

    url = (
        "https://api.themoviedb.org/3"
        + path
        + "?"
        + urllib.parse.urlencode(params)
    )

    try:
        return fetch_json(url)

    except Exception as e:
        print(
            f"[TMDB ERROR] "
            f"{path}: {e}"
        )
        return None


def tmdb_match_score(original_title, result):

    if not result:
        return 0

    original = normalize_compare(
        original_title
    )

    if not original:
        return 0

    candidates = []

    for key in (
        "title",
        "name",
        "original_title",
        "original_name",
    ):
        value = result.get(key)

        if value:
            candidates.append(
                normalize_compare(value)
            )

    candidates = [
        x for x in candidates if x
    ]

    if not candidates:
        return 0

    best = 0

    for candidate in candidates:

        if candidate == original:
            best = max(best, 100)
            continue

        if (
            original in candidate
            or candidate in original
        ):
            best = max(best, 85)
            continue

        a = set(original.split())
        b = set(candidate.split())

        if a and b:
            overlap = len(a & b)
            total = max(len(a), len(b))

            if total:
                score = int(
                    70 * overlap / total
                )

                best = max(best, score)

    popularity = result.get(
        "popularity",
        0,
    )

    try:
        popularity = float(popularity)
    except Exception:
        popularity = 0

    best += min(
        int(popularity / 100),
        10,
    )

    return min(best, 100)


def tmdb_search(
    endpoint,
    original_title,
    allowed_media_types=None,
):
    """
    TMDB 검색 결과를 30일간 영구 캐시한다.

    같은 제목을 다시 검색할 경우
    실제 TMDB API 요청을 하지 않는다.
    """

    title = clean_title(original_title)

    if not title:
        return None

    normalized = normalize_compare(title)

    cache_key = (
        f"{endpoint}|"
        f"{normalized}|"
        f"{TMDB_LANGUAGE}|"
        f"{TMDB_REGION}"
    )

    cache = TMDB_CACHE.setdefault(
        "search",
        {},
    )

    cached = cache.get(cache_key)

    if isinstance(cached, dict):
        if is_cache_fresh(
            cached.get("cached_at"),
            TMDB_SEARCH_CACHE_DAYS,
        ):
            return cached.get("result")

    data = tmdb_request(
        endpoint,
        {
            "query": title,
            "language": TMDB_LANGUAGE,
            "region": TMDB_REGION,
            "include_adult": "false",
            "page": 1,
        },
    )

    best = None
    best_score = 0

    if data:

        results = data.get(
            "results",
            [],
        )

        if allowed_media_types:
            results = [
                x
                for x in results
                if x.get("media_type")
                in allowed_media_types
            ]

        # TMDB 검색 결과 전체를 과도하게 훑지 않는다.
        for result in results[:20]:

            if endpoint == "/search/multi":

                media_type = result.get(
                    "media_type"
                )

                if media_type not in (
                    "movie",
                    "tv",
                ):
                    continue

            score = tmdb_match_score(
                title,
                result,
            )

            if score > best_score:
                best_score = score
                best = result

    if best_score < 35:
        best = None

    cache[cache_key] = {
        "cached_at": iso_now(),
        "result": best,
    }

    return best


def tmdb_find_match(
    original_title,
    media_type=None,
):
    """
    media_type이 지정되면 해당 endpoint 1회.

    media_type이 없으면
    기존의 /search/tv + /search/movie 2회 대신
    /search/multi 1회만 사용한다.
    """

    if media_type == "movie":

        return tmdb_search(
            "/search/movie",
            original_title,
            {"movie"},
        )

    if media_type == "tv":

        return tmdb_search(
            "/search/tv",
            original_title,
            {"tv"},
        )

    # 영화/TV 구분이 없는 경우
    return tmdb_search(
        "/search/multi",
        original_title,
        {"movie", "tv"},
    )


def tmdb_translation_title(
    media_type,
    tmdb_id,
    fallback_title,
):
    """
    번역 API도 영구 캐시한다.
    """

    if not media_type or not tmdb_id:
        return fallback_title

    cache_key = (
        f"{media_type}:{tmdb_id}"
    )

    cache = TMDB_CACHE.setdefault(
        "translation",
        {},
    )

    cached = cache.get(cache_key)

    if isinstance(cached, dict):
        if is_cache_fresh(
            cached.get("cached_at"),
            TMDB_SEARCH_CACHE_DAYS,
        ):
            return (
                cached.get("title")
                or fallback_title
            )

    data = tmdb_request(
        f"/{media_type}/{tmdb_id}/translations"
    )

    title = fallback_title

    if data:

        translations = data.get(
            "translations",
            [],
        )

        korean = []

        for item in translations:

            iso_639 = item.get(
                "iso_639_1"
            )

            iso_3166 = item.get(
                "iso_3166_1"
            )

            translated = (
                item.get("data", {})
                .get("title")
                or item.get("data", {})
                .get("name")
            )

            if (
                iso_639 == "ko"
                and iso_3166 == "KR"
                and translated
            ):
                korean.append(
                    translated
                )

        if not korean:

            for item in translations:

                if item.get(
                    "iso_639_1"
                ) != "ko":
                    continue

                translated = (
                    item.get("data", {})
                    .get("title")
                    or item.get("data", {})
                    .get("name")
                )

                if translated:
                    korean.append(
                        translated
                    )

        if korean:
            title = clean_title(
                korean[0]
            )

    cache[cache_key] = {
        "cached_at": iso_now(),
        "title": title,
    }

    return title


def tmdb_resolve(
    original_title,
    media_type=None,
):
    """
    제목 → TMDB 매칭.

    검색 결과 자체에 한글 제목이 있으면
    번역 API를 호출하지 않는다.
    """

    original_title = clean_title(
        original_title
    )

    if not original_title:
        return None

    result = tmdb_find_match(
        original_title,
        media_type,
    )

    if not result:
        return None

    resolved_type = (
        media_type
        or result.get("media_type")
    )

    if resolved_type not in (
        "movie",
        "tv",
    ):
        return None

    tmdb_id = result.get("id")

    if not tmdb_id:
        return None

    if resolved_type == "movie":
        localized_title = (
            result.get("title")
            or result.get("original_title")
            or original_title
        )
        tmdb_title = result.get(
            "title"
        )
        tmdb_original_title = result.get(
            "original_title"
        )

    else:
        localized_title = (
            result.get("name")
            or result.get("original_name")
            or original_title
        )
        tmdb_title = result.get(
            "name"
        )
        tmdb_original_title = result.get(
            "original_name"
        )

    localized_title = clean_title(
        localized_title
    )

    # 검색 결과에 한글이 없을 때만
    # 번역 API를 호출한다.
    if not has_korean(
        localized_title
    ):
        translated = (
            tmdb_translation_title(
                resolved_type,
                tmdb_id,
                localized_title,
            )
        )

        if translated:
            localized_title = translated

    return {
        "title": localized_title,
        "tmdb_id": tmdb_id,
        "media_type": resolved_type,
        "tmdb_title": tmdb_title,
        "tmdb_original_title":
            tmdb_original_title,
    }


def tmdb_title(
    original_title,
    media_type=None,
):
    """
    기존 코드 호환용.
    """

    result = tmdb_resolve(
        original_title,
        media_type,
    )

    if not result:
        return original_title

    return result.get(
        "title"
    ) or original_title


# ============================================================
# Netflix
# ============================================================

class NetflixLinkParser(HTMLParser):

    def __init__(self):
        super().__init__()

        self.current_href = None
        self.current_text = []

        self.items = []

    def handle_starttag(
        self,
        tag,
        attrs,
    ):

        if tag.lower() != "a":
            return

        attrs = dict(attrs)

        href = attrs.get("href")

        if href and "/title/" in href:
            self.current_href = href
            self.current_text = []

    def handle_data(self, data):

        if self.current_href:
            self.current_text.append(
                data
            )

    def handle_endtag(self, tag):

        if tag.lower() != "a":
            return

        if self.current_href:

            title = clean_title(
                "".join(
                    self.current_text
                )
            )

            if title:
                self.items.append(
                    (
                        self.current_href,
                        title,
                    )
                )

        self.current_href = None
        self.current_text = []


def get_netflix_korean_titles():

    result = {}

    for url in (
        NETFLIX_KR_MOVIE_URL,
        NETFLIX_KR_TV_URL,
    ):

        try:
            text = fetch_text(url)

        except Exception as e:
            print(
                f"[Netflix KR] "
                f"페이지 실패: {e}"
            )
            continue

        parser = NetflixLinkParser()

        try:
            parser.feed(text)
        except Exception:
            continue

        for href, title in parser.items:

            if not has_korean(title):
                continue

            key = normalize_compare(title)

            if key:
                result[key] = title

    return result


def netflix_fix_korean_title(
    title,
    korean_titles,
):
    if has_korean(title):
        return title

    key = normalize_compare(
        title
    )

    if key in korean_titles:
        return korean_titles[key]

    best_title = None
    best_score = 0

    title_words = set(
        key.split()
    )

    for k, value in korean_titles.items():

        if not k:
            continue

        if (
            key in k
            or k in key
        ):
            score = 80

        else:
            words = set(
                k.split()
            )

            if not title_words or not words:
                continue

            score = int(
                70
                * len(
                    title_words & words
                )
                / max(
                    len(title_words),
                    len(words),
                )
            )

        if score > best_score:
            best_score = score
            best_title = value

    if best_score >= 60:
        return best_title

    return title


def get_netflix():

    print(
        "[Netflix] 데이터 수집 중..."
    )

    korean_titles = (
        get_netflix_korean_titles()
    )

    try:
        text = fetch_text(
            NETFLIX_TSV_URL
        )
    except Exception as e:
        print(
            f"[Netflix] TSV 실패: {e}"
        )
        return []

    reader = csv.DictReader(
        io.StringIO(text),
        delimiter="\t",
    )

    rows = []

    for row in reader:

        country = (
            row.get("country_name")
            or row.get("country")
            or ""
        )

        if country.upper() not in (
            "SOUTH KOREA",
            "KOREA",
            "REPUBLIC OF KOREA",
        ):
            continue

        rows.append(row)

    if not rows:
        print(
            "[Netflix] 한국 데이터 없음"
        )
        return []

    weeks = []

    for row in rows:

        week = (
            row.get("week")
            or row.get("week_date")
            or ""
        )

        if week:
            weeks.append(week)

    if not weeks:
        return []

    latest_week = max(weeks)

    latest = [
        row
        for row in rows
        if (
            row.get("week")
            or row.get("week_date")
            or ""
        ) == latest_week
    ]

    movies = []
    tv = []

    for row in latest:

        category = (
            row.get("category")
            or row.get("type")
            or ""
        ).lower()

        title = (
            row.get("show_title")
            or row.get("title")
            or row.get("name")
            or ""
        )

        title = clean_title(title)

        if not title:
            continue

        try:
            rank = int(
                row.get("rank")
                or row.get("rank_number")
                or 999
            )
        except Exception:
            rank = 999

        item = {
            "rank": rank,
            "title": title,
            "original_title": title,
            "season_title": (
                row.get("season_title")
                or ""
            ),
            "platform": "Netflix",
            "week": latest_week,
        }

        if (
            category in (
                "film",
                "movie",
                "movies",
            )
            or "film" in category
            or "movie" in category
        ):
            movies.append(item)

        elif (
            category in (
                "tv",
                "series",
                "show",
            )
            or "tv" in category
            or "series" in category
        ):
            tv.append(item)

    movies.sort(
        key=lambda x: x["rank"]
    )

    tv.sort(
        key=lambda x: x["rank"]
    )

    movies = movies[:10]
    tv = tv[:10]

    result = []

    for item in movies + tv:

        media_type = "movie"

        if item in tv:
            media_type = "tv"

        resolved = tmdb_resolve(
            item["original_title"],
            media_type,
        )

        if resolved:

            item["title"] = (
                resolved["title"]
            )

            item["tmdb_id"] = (
                resolved["tmdb_id"]
            )

            item["media_type"] = (
                resolved["media_type"]
            )

            item["tmdb_title"] = (
                resolved["tmdb_title"]
            )

            item["tmdb_original_title"] = (
                resolved[
                    "tmdb_original_title"
                ]
            )

            if not has_korean(
                item["title"]
            ):
                item["title"] = (
                    netflix_fix_korean_title(
                        item["title"],
                        korean_titles,
                    )
                )

        else:

            item["tmdb_id"] = None
            item["media_type"] = (
                media_type
            )
            item["tmdb_title"] = None
            item[
                "tmdb_original_title"
            ] = None

        result.append(item)

    print(
        f"[Netflix] 영화 {len(movies)}개 / "
        f"TV {len(tv)}개"
    )

    return result


# ============================================================
# Disney+
# ============================================================

class DisneyEntityParser(HTMLParser):

    def __init__(self):
        super().__init__()

        self.items = []
        self.seen = set()

    def handle_starttag(
        self,
        tag,
        attrs,
    ):

        if tag.lower() != "a":
            return

        attrs = dict(attrs)

        href = attrs.get("href")

        if not href:
            return

        if "/browse/entity-" not in href:
            return

        href = html.unescape(href)

        if href in self.seen:
            return

        self.seen.add(href)

        self.items.append(href)


class DisneyDetailParser(HTMLParser):

    def __init__(self):
        super().__init__()

        self.h1 = []
        self.title = []
        self.meta_title = []
        self.meta_og = []
        self.meta_twitter = []

        self.in_h1 = False

    def handle_starttag(
        self,
        tag,
        attrs,
    ):

        attrs = dict(attrs)

        if tag.lower() == "h1":
            self.in_h1 = True
            return

        if tag.lower() != "meta":
            return

        name = (
            attrs.get("name")
            or ""
        ).lower()

        prop = (
            attrs.get("property")
            or ""
        ).lower()

        content = (
            attrs.get("content")
            or ""
        )

        if not content:
            return

        if prop == "og:title":
            self.meta_og.append(
                content
            )

        elif prop == "twitter:title":
            self.meta_twitter.append(
                content
            )

        elif name == "title":
            self.meta_title.append(
                content
            )

    def handle_data(self, data):

        if self.in_h1:
            self.h1.append(data)

    def handle_endtag(self, tag):

        if tag.lower() == "h1":
            self.in_h1 = False


def disney_is_metadata(title):

    if not title:
        return True

    title = clean_title(title)

    if not title:
        return True

    bad_exact = {
        "오스트레일리아",
        "대한민국",
        "미국",
        "한국",
        "일본",
        "영국",
        "프랑스",
        "독일",
        "캐나다",
        "호주",
        "new",
        "신규",
        "더보기",
        "검색",
        "로그인",
        "회원가입",
        "disney+",
        "disney plus",
    }

    if title.lower() in bad_exact:
        return True

    # 순위
    if re.fullmatch(
        r"\d{1,2}",
        title,
    ):
        return True

    if re.fullmatch(
        r"(new|NEW)",
        title,
    ):
        return True

    # 국가명 + NEW 등의 UI 텍스트
    if (
        title in (
            "오스트레일리아",
            "대한민국",
            "미국",
            "일본",
            "영국",
            "프랑스",
            "독일",
            "캐나다",
        )
    ):
        return True

    return False


def disney_is_bad_title(title):

    title = clean_title(title)

    if not title:
        return True

    if disney_is_metadata(title):
        return True

    bad_patterns = [
        r"^\d+$",
        r"^NEW$",
        r"^New$",
        r"^오스트레일리아$",
        r"^대한민국$",
        r"^미국$",
        r"^일본$",
        r"^한국$",
        r"^Disney\+?$",
        r"^Disney Plus$",
    ]

    for pattern in bad_patterns:

        if re.search(
            pattern,
            title,
            re.I,
        ):
            return True

    return False


def choose_disney_title(
    candidates
):

    for title in candidates:

        title = clean_title(title)

        if disney_is_bad_title(title):
            continue

        # UI 텍스트가 섞인 경우
        title = re.sub(
            r"\s+(NEW|New)$",
            "",
            title,
            flags=re.I,
        )

        title = clean_title(title)

        if not disney_is_bad_title(
            title
        ):
            return title

    return ""


def disney_entity_id(href):

    if not href:
        return ""

    match = re.search(
        r"/browse/entity-([^/?#]+)",
        href,
    )

    if match:
        return match.group(1)

    return ""


def get_disney_detail_title(href):

    try:
        text = fetch_text(href)

    except Exception:
        return ""

    parser = DisneyDetailParser()

    try:
        parser.feed(text)

    except Exception:
        return ""

    candidates = []

    if parser.h1:
        candidates.append(
            "".join(parser.h1)
        )

    candidates.extend(
        parser.meta_og
    )

    candidates.extend(
        parser.meta_twitter
    )

    candidates.extend(
        parser.meta_title
    )

    # 일반 HTML <title>
    match = re.search(
        r"<title[^>]*>(.*?)</title>",
        text,
        flags=re.I | re.S,
    )

    if match:
        candidates.append(
            html.unescape(
                re.sub(
                    r"<[^>]+>",
                    "",
                    match.group(1),
                )
            )
        )

    # JSON 내부 headline/name
    for pattern in (
        r'"headline"\s*:\s*"([^"]+)"',
        r'"name"\s*:\s*"([^"]+)"',
    ):

        for match in re.finditer(
            pattern,
            text,
            flags=re.I,
        ):

            candidates.append(
                match.group(1)
            )

    return choose_disney_title(
        candidates
    )


def extract_disney_entities(text):

    parser = DisneyEntityParser()

    try:
        parser.feed(text)

    except Exception:
        return []

    return parser.items


def get_disney():

    print(
        "[Disney+] 데이터 수집 중..."
    )

    try:
        text = fetch_text(
            DISNEY_URL
        )

    except Exception as e:
        print(
            f"[Disney+] 페이지 실패: {e}"
        )
        return []

    # TOP 10 영역을 우선 찾는다.
    markers = [
        "오늘 한국의 TOP 10",
        "한국의 TOP 10",
        "TOP 10",
        "Top 10",
    ]

    start = -1

    for marker in markers:

        pos = text.find(marker)

        if pos >= 0:
            start = pos
            break

    if start >= 0:
        section = text[
            start:start + 120000
        ]
    else:
        section = text[:120000]

    entities = extract_disney_entities(
        section
    )

    if not entities:
        entities = extract_disney_entities(
            text
        )

    result = []

    seen_titles = set()

    # 실제 entity 페이지에서 제목을 가져온다.
    # 잘못된 국가명/NEW/순위 텍스트를
    # 직접 제목으로 사용하지 않는다.
    for href in entities:

        if len(result) >= 10:
            break

        title = get_disney_detail_title(
            urllib.parse.urljoin(
                DISNEY_URL,
                href,
            )
        )

        title = clean_title(title)

        if disney_is_bad_title(title):
            continue

        key = normalize_compare(
            title
        )

        if not key:
            continue

        if key in seen_titles:
            continue

        seen_titles.add(key)

        resolved = tmdb_resolve(
            title,
            None,
        )

        item = {
            "rank": len(result) + 1,
            "title": title,
            "original_title": title,
            "season_title": "",
            "platform": "Disney+",
            "category": "top10",
        }

        if resolved:

            item["title"] = (
                resolved["title"]
            )

            item["tmdb_id"] = (
                resolved["tmdb_id"]
            )

            item["media_type"] = (
                resolved["media_type"]
            )

            item["tmdb_title"] = (
                resolved["tmdb_title"]
            )

            item["tmdb_original_title"] = (
                resolved[
                    "tmdb_original_title"
                ]
            )

        else:

            item["tmdb_id"] = None

            item["media_type"] = None

            item["tmdb_title"] = None

            item[
                "tmdb_original_title"
            ] = None

        result.append(item)

    print(
        f"[Disney+] {len(result)}개"
    )

    return result


# ============================================================
# Coupang Play
# ============================================================

COUPANG_BAD_TITLES = {
    "쿠팡플레이",
    "coupang play",
    "로그인",
    "회원가입",
    "검색",
    "더보기",
    "무료체험",
    "무료 체험",
    "모바일히어로",
    "오토플레이",
    "메인예고",
    "예고편",
    "티저",
    "하이라이트",
    "클립",
    "비하인드",
    "인터뷰",
}


def coupang_is_bad_title(title):

    title = clean_title(title)

    if not title:
        return True

    if title.lower() in {
        x.lower()
        for x in COUPANG_BAD_TITLES
    }:
        return True

    bad_patterns = [
        r"^메인\s*예고",
        r"^예고편",
        r"^티저",
        r"^하이라이트",
        r"^오토\s*플레이",
        r"^모바일\s*히어로",
        r"^로그인",
        r"^회원가입",
        r"^무료\s*체험",
        r"^더보기",
    ]

    for pattern in bad_patterns:

        if re.search(
            pattern,
            title,
            flags=re.I,
        ):
            return True

    if len(title) < 2:
        return True

    return False


def extract_coupang_titles(text):

    patterns = [
        r'"title"\s*:\s*"([^"]+)"',
        r'"name"\s*:\s*"([^"]+)"',
        r'"contentTitle"\s*:\s*"([^"]+)"',
        r'"displayName"\s*:\s*"([^"]+)"',
    ]

    result = []
    seen = set()

    for pattern in patterns:

        for match in re.finditer(
            pattern,
            text,
            flags=re.I,
        ):

            title = clean_title(
                match.group(1)
            )

            if coupang_is_bad_title(
                title
            ):
                continue

            key = normalize_compare(
                title
            )

            if not key:
                continue

            if key in seen:
                continue

            seen.add(key)

            result.append(title)

            if len(result) >= 50:
                return result

    return result


def get_coupang():

    print(
        "[Coupang Play] 데이터 수집 중..."
    )

    try:
        text = fetch_text(
            COUPANG_URL
        )

    except Exception as e:
        print(
            f"[Coupang Play] "
            f"페이지 실패: {e}"
        )
        return []

    titles = extract_coupang_titles(
        text
    )

    result = []

    for title in titles:

        if len(result) >= 10:
            break

        resolved = tmdb_resolve(
            title,
            None,
        )

        # TMDB 매칭에 실패하면
        # 홍보문구일 가능성이 있으므로
        # 바로 버리지 않고 원래 제목을 유지한다.
        item = {
            "rank": len(result) + 1,
            "title": title,
            "original_title": title,
            "season_title": "",
            "platform": "Coupang Play",
            "category": "top10",
        }

        if resolved:

            item["title"] = (
                resolved["title"]
            )

            item["tmdb_id"] = (
                resolved["tmdb_id"]
            )

            item["media_type"] = (
                resolved["media_type"]
            )

            item["tmdb_title"] = (
                resolved["tmdb_title"]
            )

            item["tmdb_original_title"] = (
                resolved[
                    "tmdb_original_title"
                ]
            )

        else:

            item["tmdb_id"] = None
            item["media_type"] = None
            item["tmdb_title"] = None
            item[
                "tmdb_original_title"
            ] = None

        result.append(item)

    print(
        f"[Coupang Play] "
        f"{len(result)}개"
    )

    return result


# ============================================================
# TMDB 상세정보
# ============================================================

def load_tmdb_details():

    data = load_json(
        TMDB_DETAIL_FILE,
        {},
    )

    if not isinstance(data, dict):
        return {}

    return data


def save_tmdb_details(data):

    save_json(
        TMDB_DETAIL_FILE,
        data,
    )


def tmdb_get_detail(
    media_type,
    tmdb_id,
):
    """
    상세정보는 한 번만 호출한다.

    credits,videos를 append_to_response로 합쳐
    별도의 credits/videos 요청을 만들지 않는다.
    """

    if not media_type or not tmdb_id:
        return None

    data = tmdb_request(
        f"/{media_type}/{tmdb_id}",
        {
            "language": TMDB_LANGUAGE,
            "append_to_response":
                "credits,videos",
        },
    )

    if not data:
        return None

    if media_type == "movie":

        title = (
            data.get("title")
            or data.get(
                "original_title"
            )
        )

        original_title = (
            data.get(
                "original_title"
            )
        )

        release_date = (
            data.get("release_date")
        )

    else:

        title = (
            data.get("name")
            or data.get(
                "original_name"
            )
        )

        original_title = (
            data.get(
                "original_name"
            )
        )

        release_date = (
            data.get("first_air_date")
        )

    genres = []

    for genre in data.get(
        "genres",
        [],
    ):
        name = genre.get("name")

        if name:
            genres.append(name)

    runtime = data.get(
        "runtime"
    )

    if not runtime:
        runtimes = data.get(
            "episode_run_time",
            [],
        )

        if runtimes:
            runtime = runtimes[0]

    director = ""

    credits = data.get(
        "credits",
        {},
    )

    for crew in credits.get(
        "crew",
        [],
    ):

        if crew.get("job") == "Director":

            director = (
                crew.get("name")
                or ""
            )

            break

    cast = []

    for person in credits.get(
        "cast",
        [],
    )[:10]:

        name = person.get("name")

        if name:
            cast.append(name)

    trailer_key = ""

    videos = data.get(
        "videos",
        {},
    )

    videos_list = videos.get(
        "results",
        [],
    )

    for video in videos_list:

        if (
            video.get("site")
            == "YouTube"
            and video.get("type")
            in (
                "Trailer",
                "Teaser",
            )
        ):

            trailer_key = (
                video.get("key")
                or ""
            )

            if (
                video.get("type")
                == "Trailer"
            ):
                break

    return {
        "id": data.get("id"),
        "media_type": media_type,
        "title": title,
        "original_title":
            original_title,
        "poster_path":
            data.get("poster_path"),
        "backdrop_path":
            data.get("backdrop_path"),
        "vote_average":
            data.get("vote_average"),
        "vote_count":
            data.get("vote_count"),
        "release_date":
            release_date,
        "genres": genres,
        "runtime": runtime,
        "overview":
            data.get("overview")
            or "",
        "director": director,
        "cast": cast,
        "trailer_key":
            trailer_key,
        "homepage":
            data.get("homepage")
            or "",
        "cached_at": iso_now(),
    }


def build_tmdb_details(
    current_items
):
    existing = load_tmdb_details()

    if not isinstance(existing, dict):
        existing = {}

    result = dict(existing)

    # 같은 실행 안에서 동일 ID를
    # 절대로 두 번 요청하지 않는다.
    requested_this_run = set()

    for item in current_items:

        tmdb_id = item.get(
            "tmdb_id"
        )

        media_type = item.get(
            "media_type"
        )

        if not tmdb_id or not media_type:
            continue

        key = (
            f"{media_type}:{tmdb_id}"
        )

        # 같은 실행에서 이미 처리
        if key in requested_this_run:
            continue

        requested_this_run.add(key)

        old = result.get(key)

        if isinstance(old, dict):

            if is_cache_fresh(
                old.get("cached_at"),
                TMDB_DETAIL_CACHE_DAYS,
            ):

                # 현재 랭킹 제목으로 최신화
                old["title"] = (
                    item.get("title")
                    or old.get("title")
                )

                result[key] = old

                continue

        print(
            f"[TMDB DETAIL] "
            f"{media_type}:{tmdb_id}"
        )

        detail = tmdb_get_detail(
            media_type,
            tmdb_id,
        )

        if detail:

            # 랭킹에서 확보한 한글 제목을
            # 상세 API의 제목보다 우선
            if item.get("title"):
                detail["title"] = (
                    item["title"]
                )

            result[key] = detail

        elif isinstance(old, dict):

            # 실패하면 기존 데이터 유지
            result[key] = old

    save_tmdb_details(result)

    return result


# ============================================================
# 랭킹 / 히스토리
# ============================================================

def same_content(a, b):

    a_id = a.get("tmdb_id")
    b_id = b.get("tmdb_id")

    a_type = a.get("media_type")
    b_type = b.get("media_type")

    if (
        a_id
        and b_id
        and a_type
        and b_type
    ):
        return (
            str(a_id) == str(b_id)
            and a_type == b_type
        )

    keys = [
        "title",
        "original_title",
        "tmdb_title",
        "tmdb_original_title",
    ]

    for key in keys:

        av = normalize_compare(
            a.get(key)
        )

        bv = normalize_compare(
            b.get(key)
        )

        if av and bv and av == bv:
            return True

    return False


def find_previous_rank(
    item,
    previous_items,
):

    for previous in previous_items:

        if same_content(
            item,
            previous,
        ):
            return previous.get(
                "rank"
            )

    return None


def find_history_rank(
    item,
    history_items,
):

    for history in history_items:

        if same_content(
            item,
            history,
        ):
            return history.get(
                "rank"
            )

    return None


def calculate_changes(
    current,
    previous,
):

    for item in current:

        old_rank = (
            find_previous_rank(
                item,
                previous,
            )
        )

        item["previous_rank"] = old_rank

        if old_rank is None:
            item["change"] = "NEW"

        else:

            current_rank = item.get(
                "rank"
            )

            if current_rank is None:
                item["change"] = 0

            else:
                item["change"] = (
                    old_rank
                    - current_rank
                )


def korea_now():

    return datetime.now(
        timezone(
            timedelta(hours=9)
        )
    )


def today_string():

    return korea_now().strftime(
        "%Y-%m-%d"
    )


def cleanup_history(
    history
):

    cutoff = (
        korea_now()
        - timedelta(
            days=KEEP_DAYS
        )
    )

    result = []

    for entry in history:

        date_value = entry.get(
            "date"
        )

        if not date_value:
            continue

        try:

            dt = datetime.strptime(
                date_value,
                "%Y-%m-%d",
            ).replace(
                tzinfo=timezone(
                    timedelta(hours=9)
                )
            )

        except Exception:
            continue

        if dt >= cutoff:
            result.append(entry)

    return result


# ============================================================
# 출력
# ============================================================

def print_platform(
    items,
    platform
):

    platform_items = [
        x
        for x in items
        if x.get("platform")
        == platform
    ]

    print()
    print(
        f"========== {platform} =========="
    )

    for item in platform_items:

        rank = item.get(
            "rank",
            "",
        )

        title = item.get(
            "title",
            "",
        )

        change = item.get(
            "change",
            "",
        )

        media_type = item.get(
            "media_type",
            "",
        )

        print(
            f"{rank:>2} | "
            f"{title} | "
            f"{media_type} | "
            f"{change}"
        )


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "=" * 60
    )

    print(
        "OTT RANKING COLLECTOR"
    )

    print(
        "=" * 60
    )

    if not TMDB_API_KEY:

        print(
            "[ERROR] "
            "TMDB_API_KEY가 설정되어 있지 않습니다."
        )

        sys.exit(1)

    # --------------------------------------------------------
    # TMDB 영구 캐시 로드
    # --------------------------------------------------------

    load_tmdb_cache()

    cleanup_tmdb_cache()

    # --------------------------------------------------------
    # Netflix
    # --------------------------------------------------------

    netflix = get_netflix()

    # 검색 캐시를 중간 저장
    save_tmdb_cache()

    # --------------------------------------------------------
    # Disney+
    # --------------------------------------------------------

    disney = get_disney()

    save_tmdb_cache()

    # --------------------------------------------------------
    # Coupang Play
    # --------------------------------------------------------

    coupang = get_coupang()

    save_tmdb_cache()

    # --------------------------------------------------------
    # 전체 현재 랭킹
    # --------------------------------------------------------

    current = (
        netflix
        + disney
        + coupang
    )

    # --------------------------------------------------------
    # 이전 랭킹
    # --------------------------------------------------------

    previous_data = load_json(
        RANKING_FILE,
        [],
    )

    if isinstance(
        previous_data,
        dict,
    ):
        previous = (
            previous_data.get(
                "items",
                [],
            )
        )

    elif isinstance(
        previous_data,
        list,
    ):
        previous = previous_data

    else:
        previous = []

    # --------------------------------------------------------
    # 변동 계산
    # --------------------------------------------------------

    calculate_changes(
        current,
        previous,
    )

    # --------------------------------------------------------
    # TMDB 상세정보
    # --------------------------------------------------------

    print()
    print(
        "[TMDB] 상세정보 처리 중..."
    )

    build_tmdb_details(
        current
    )

    # --------------------------------------------------------
    # ranking.json 저장
    # --------------------------------------------------------

    ranking_data = {
        "date": today_string(),
        "items": current,
    }

    save_json(
        RANKING_FILE,
        ranking_data,
    )

    # --------------------------------------------------------
    # history.json
    # --------------------------------------------------------

    history = load_json(
        HISTORY_FILE,
        [],
    )

    if not isinstance(
        history,
        list,
    ):
        history = []

    history.append(
        {
            "date": today_string(),
            "items": current,
        }
    )

    history = cleanup_history(
        history
    )

    save_json(
        HISTORY_FILE,
        history,
    )

    # --------------------------------------------------------
    # TMDB 캐시 최종 저장
    # --------------------------------------------------------

    save_tmdb_cache()

    # --------------------------------------------------------
    # 결과 출력
    # --------------------------------------------------------

    print()
    print(
        "=" * 60
    )

    print(
        f"수집 완료 "
        f"({today_string()})"
    )

    print(
        "=" * 60
    )

    print_platform(
        current,
        "Netflix",
    )

    print_platform(
        current,
        "Disney+",
    )

    print_platform(
        current,
        "Coupang Play",
    )

    print()
    print(
        "=" * 60
    )

    print(
        "[TMDB CACHE]"
    )

    print(
        "검색 캐시:",
        len(
            TMDB_CACHE.get(
                "search",
                {},
            )
        ),
    )

    print(
        "번역 캐시:",
        len(
            TMDB_CACHE.get(
                "translation",
                {},
            )
        ),
    )

    print(
        "=" * 60
    )


if __name__ == "__main__":
    main()
