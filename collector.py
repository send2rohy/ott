import csv
import html
import io
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
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
TMDB_SEARCH_CACHE_FILE = "tmdb_cache.json"

TMDB_SEARCH_CACHE_DAYS = 30
TMDB_DETAIL_CACHE_DAYS = 7

TMDB_API_KEY = os.environ.get("TMDB_API_KEY")

TMDB_LANGUAGE = "ko-KR"
TMDB_REGION = "KR"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0 Safari/537.36"
)

REQUEST_TIMEOUT = 20

# Disney / Coupang에서 영화 + TV TOP 10을 확보하기 위해
# TMDB에 넘길 원본 후보 수
SOURCE_CANDIDATE_LIMIT = 60

# Disney 상세 페이지 동시 요청 수
PAGE_WORKERS = 6


# ============================================================
# 전역 캐시
# ============================================================

TMDB_CACHE = {
    "search": {},
    "translation": {},
}


# ============================================================
# 공통
# ============================================================

def now_utc():
    return datetime.now(timezone.utc)


def iso_now():
    return now_utc().isoformat()


def parse_iso(value):
    if not value:
        return None

    try:
        return datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )
    except Exception:
        return None


def is_cache_fresh(value, days):
    dt = parse_iso(value)

    if not dt:
        return False

    return (
        now_utc() - dt
        < timedelta(days=days)
    )


def load_json(filename, default):
    if not os.path.exists(filename):
        return default

    try:
        with open(
            filename,
            "r",
            encoding="utf-8",
        ) as f:
            return json.load(f)

    except Exception as e:
        print(
            f"[WARN] {filename} 읽기 실패: {e}"
        )

        return default


def save_json(filename, data):
    tmp = filename + ".tmp"

    try:
        with open(
            tmp,
            "w",
            encoding="utf-8",
        ) as f:

            json.dump(
                data,
                f,
                ensure_ascii=False,
                indent=2,
            )

        os.replace(
            tmp,
            filename,
        )

    except Exception as e:

        print(
            f"[WARN] {filename} 저장 실패: {e}"
        )


def clean_title(value):
    if not value:
        return ""

    value = html.unescape(
        str(value)
    )

    value = re.sub(
        r"[\u200b-\u200d\ufeff]",
        "",
        value,
    )

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value.strip(
        " \t\r\n|•·"
    )


def normalize_title(value):
    if not value:
        return ""

    value = clean_title(value).lower()

    return re.sub(
        r"[^0-9a-z가-힣]+",
        "",
        value,
    )


def normalize_compare(value):
    if not value:
        return ""

    value = clean_title(value).lower()

    value = re.sub(
        r"[^0-9a-z가-힣]+",
        " ",
        value,
    )

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value.strip()


def has_korean(value):
    if not value:
        return False

    return bool(
        re.search(
            r"[가-힣]",
            str(value),
        )
    )


def has_latin(value):
    if not value:
        return False

    return bool(
        re.search(
            r"[a-z]",
            str(value),
            re.I,
        )
    )


# ============================================================
# HTTP
# ============================================================

def fetch_text(
    url,
    timeout=REQUEST_TIMEOUT,
):

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language":
                "ko-KR,ko;q=0.9,en;q=0.8",
        },
    )

    with urllib.request.urlopen(
        req,
        timeout=timeout,
    ) as response:

        raw = response.read()

        charset = (
            response.headers.get_content_charset()
            or "utf-8"
        )

        return raw.decode(
            charset,
            errors="replace",
        )


def fetch_json(
    url,
    timeout=REQUEST_TIMEOUT,
):

    text = fetch_text(
        url,
        timeout,
    )

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

    if not isinstance(
        data,
        dict,
    ):

        TMDB_CACHE = {
            "search": {},
            "translation": {},
        }

        return

    search = data.get(
        "search",
        {},
    )

    translation = data.get(
        "translation",
        {},
    )

    if not isinstance(
        search,
        dict,
    ):
        search = {}

    if not isinstance(
        translation,
        dict,
    ):
        translation = {}

    TMDB_CACHE = {
        "search": search,
        "translation": translation,
    }

    print(
        "[TMDB CACHE] "
        f"검색 {len(search)}개 / "
        f"번역 {len(translation)}개"
    )


def save_tmdb_cache():

    save_json(
        TMDB_SEARCH_CACHE_FILE,
        TMDB_CACHE,
    )


def cleanup_tmdb_cache():

    search = TMDB_CACHE.get(
        "search",
        {},
    )

    remove = []

    for key, value in search.items():

        if not isinstance(
            value,
            dict,
        ):
            remove.append(key)
            continue

        if not is_cache_fresh(
            value.get("cached_at"),
            TMDB_SEARCH_CACHE_DAYS,
        ):
            remove.append(key)

    for key in remove:
        search.pop(
            key,
            None,
        )

    translation = TMDB_CACHE.get(
        "translation",
        {},
    )

    remove = []

    for key, value in translation.items():

        if not isinstance(
            value,
            dict,
        ):
            remove.append(key)
            continue

        if not is_cache_fresh(
            value.get("cached_at"),
            TMDB_SEARCH_CACHE_DAYS,
        ):
            remove.append(key)

    for key in remove:
        translation.pop(
            key,
            None,
        )


# ============================================================
# TMDB API
# ============================================================

def tmdb_request(
    path,
    params=None,
):

    if not TMDB_API_KEY:
        return None

    params = dict(
        params or {}
    )

    params["api_key"] = TMDB_API_KEY

    url = (
        "https://api.themoviedb.org/3"
        + path
        + "?"
        + urllib.parse.urlencode(params)
    )

    try:

        return fetch_json(
            url
        )

    except Exception as e:

        print(
            f"[TMDB ERROR] "
            f"{path}: {e}"
        )

        return None


# ============================================================
# TMDB 제목 비교
# ============================================================

def tmdb_match_score(
    original_title,
    result,
):

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
        x for x in candidates
        if x
    ]

    if not candidates:
        return 0

    best = 0

    for candidate in candidates:

        if candidate == original:

            best = max(
                best,
                100,
            )

            continue

        original_compact = (
            original.replace(
                " ",
                "",
            )
        )

        candidate_compact = (
            candidate.replace(
                " ",
                "",
            )
        )

        if (
            original_compact
            == candidate_compact
        ):

            best = max(
                best,
                98,
            )

            continue

        if (
            original_compact
            in candidate_compact
            or candidate_compact
            in original_compact
        ):

            best = max(
                best,
                88,
            )

            continue

        a = set(
            original.split()
        )

        b = set(
            candidate.split()
        )

        if a and b:

            overlap = len(
                a & b
            )

            total = max(
                len(a),
                len(b),
            )

            if total:

                score = int(
                    75
                    * overlap
                    / total
                )

                best = max(
                    best,
                    score,
                )

    popularity = result.get(
        "popularity",
        0,
    )

    try:
        popularity = float(
            popularity
        )
    except Exception:
        popularity = 0

    best += min(
        int(
            popularity / 200
        ),
        5,
    )

    return min(
        best,
        100,
    )


# ============================================================
# TMDB 검색
# ============================================================

def tmdb_search(
    endpoint,
    original_title,
    allowed_media_types=None,
):

    title = clean_title(
        original_title
    )

    if not title:
        return None

    normalized = normalize_compare(
        title
    )

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

    cached = cache.get(
        cache_key
    )

    if isinstance(
        cached,
        dict,
    ):

        if is_cache_fresh(
            cached.get(
                "cached_at"
            ),
            TMDB_SEARCH_CACHE_DAYS,
        ):

            return cached.get(
                "result"
            )

    data = tmdb_request(
        endpoint,
        {
            "query": title,
            "language":
                TMDB_LANGUAGE,
            "region":
                TMDB_REGION,
            "include_adult":
                "false",
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
                if x.get(
                    "media_type"
                )
                in allowed_media_types
                or endpoint != "/search/multi"
            ]

        scored = []

        for result in results[:20]:

            if endpoint == "/search/multi":

                media_type = (
                    result.get(
                        "media_type"
                    )
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

            scored.append(
                (
                    score,
                    result,
                )
            )

        scored.sort(
            key=lambda x: x[0],
            reverse=True,
        )

        if scored:

            best_score, best = (
                scored[0]
            )

    if best_score < 60:

        best = None

    cache[cache_key] = {
        "cached_at": iso_now(),
        "result": best,
        "score":
            best_score,
    }

    return best


def tmdb_find_match(
    original_title,
    media_type=None,
):

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

    return tmdb_search(
        "/search/multi",
        original_title,
        {"movie", "tv"},
    )


# ============================================================
# TMDB 번역
# ============================================================

def tmdb_translation_title(
    media_type,
    tmdb_id,
    fallback_title,
):

    if not media_type or not tmdb_id:
        return fallback_title

    cache_key = (
        f"{media_type}:{tmdb_id}"
    )

    cache = TMDB_CACHE.setdefault(
        "translation",
        {},
    )

    cached = cache.get(
        cache_key
    )

    if isinstance(
        cached,
        dict,
    ):

        if is_cache_fresh(
            cached.get(
                "cached_at"
            ),
            TMDB_SEARCH_CACHE_DAYS,
        ):

            return (
                cached.get(
                    "title"
                )
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

            if (
                item.get(
                    "iso_639_1"
                )
                != "ko"
            ):
                continue

            translated = (
                item.get(
                    "data",
                    {},
                ).get("title")
                or item.get(
                    "data",
                    {},
                ).get("name")
            )

            if translated:

                if (
                    item.get(
                        "iso_3166_1"
                    )
                    == "KR"
                ):

                    korean.insert(
                        0,
                        translated,
                    )

                else:

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


# ============================================================
# TMDB resolve
# ============================================================

def tmdb_resolve(
    original_title,
    media_type=None,
):

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
        or result.get(
            "media_type"
        )
    )

    if resolved_type not in (
        "movie",
        "tv",
    ):
        return None

    tmdb_id = result.get(
        "id"
    )

    if not tmdb_id:
        return None

    if resolved_type == "movie":

        tmdb_title = (
            result.get(
                "title"
            )
        )

        tmdb_original_title = (
            result.get(
                "original_title"
            )
        )

        localized_title = (
            tmdb_title
            or tmdb_original_title
            or original_title
        )

    else:

        tmdb_title = (
            result.get(
                "name"
            )
        )

        tmdb_original_title = (
            result.get(
                "original_name"
            )
        )

        localized_title = (
            tmdb_title
            or tmdb_original_title
            or original_title
        )

    localized_title = clean_title(
        localized_title
    )

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
            localized_title = (
                translated
            )

    return {
        "title":
            localized_title,

        "tmdb_id":
            tmdb_id,

        "media_type":
            resolved_type,

        "tmdb_title":
            tmdb_title,

        "tmdb_original_title":
            tmdb_original_title,
    }


# ============================================================
# Netflix
# ============================================================

class NetflixLinkParser(
    HTMLParser
):

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

        href = attrs.get(
            "href"
        )

        if (
            href
            and "/title/" in href
        ):

            self.current_href = href
            self.current_text = []

    def handle_data(
        self,
        data,
    ):

        if self.current_href:

            self.current_text.append(
                data
            )

    def handle_endtag(
        self,
        tag,
    ):

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

            text = fetch_text(
                url
            )

        except Exception as e:

            print(
                "[Netflix KR] "
                f"페이지 실패: {e}"
            )

            continue

        parser = NetflixLinkParser()

        try:
            parser.feed(text)
        except Exception:
            continue

        for href, title in parser.items:

            if not has_korean(
                title
            ):
                continue

            key = normalize_compare(
                title
            )

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
            "[Netflix] TSV 실패:",
            e,
        )

        return []

    reader = csv.DictReader(
        io.StringIO(text),
        delimiter="\t",
    )

    rows = []

    for row in reader:

        country = (
            row.get(
                "country_name"
            )
            or row.get(
                "country"
            )
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

    latest_week = max(
        weeks
    )

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

        title = clean_title(
            row.get(
                "show_title"
            )
            or row.get(
                "title"
            )
            or row.get(
                "name"
            )
            or ""
        )

        if not title:
            continue

        try:

            rank = int(
                row.get("rank")
                or row.get(
                    "rank_number"
                )
                or 999
            )

        except Exception:

            rank = 999

        item = {
            "rank": rank,
            "title": title,
            "original_title": title,
            "season_title":
                row.get(
                    "season_title"
                )
                or "",
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

    # --------------------------------------------------------
    # Netflix 영화
    # --------------------------------------------------------

    for item in movies:

        item["media_type"] = "movie"

        resolved = tmdb_resolve(
            item["original_title"],
            "movie",
        )

        if resolved:

            item.update(
                {
                    "title":
                        netflix_fix_korean_title(
                            resolved["title"],
                            korean_titles,
                        ),

                    "tmdb_id":
                        resolved["tmdb_id"],

                    "tmdb_title":
                        resolved[
                            "tmdb_title"
                        ],

                    "tmdb_original_title":
                        resolved[
                            "tmdb_original_title"
                        ],
                }
            )

        else:

            item.update(
                {
                    "tmdb_id": None,
                    "tmdb_title": None,
                    "tmdb_original_title":
                        None,
                }
            )

        result.append(item)

    # --------------------------------------------------------
    # Netflix TV
    # --------------------------------------------------------

    for item in tv:

        item["media_type"] = "tv"

        resolved = tmdb_resolve(
            item["original_title"],
            "tv",
        )

        if resolved:

            item.update(
                {
                    "title":
                        netflix_fix_korean_title(
                            resolved["title"],
                            korean_titles,
                        ),

                    "tmdb_id":
                        resolved["tmdb_id"],

                    "tmdb_title":
                        resolved[
                            "tmdb_title"
                        ],

                    "tmdb_original_title":
                        resolved[
                            "tmdb_original_title"
                        ],
                }
            )

        else:

            item.update(
                {
                    "tmdb_id": None,
                    "tmdb_title": None,
                    "tmdb_original_title":
                        None,
                }
            )

        result.append(item)

    print(
        f"[Netflix] 영화 {len(movies)}개 / "
        f"TV {len(tv)}개"
    )

    return result


# ============================================================
# Disney+
# ============================================================

class DisneyEntityParser(
    HTMLParser
):

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

        href = attrs.get(
            "href"
        )

        if not href:
            return

        if (
            "/browse/entity-"
            not in href
        ):
            return

        href = html.unescape(
            href
        )

        if href in self.seen:
            return

        self.seen.add(
            href
        )

        self.items.append(
            href
        )


class DisneyDetailParser(
    HTMLParser
):

    def __init__(self):

        super().__init__()

        self.h1 = []
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
            attrs.get(
                "name"
            )
            or ""
        ).lower()

        prop = (
            attrs.get(
                "property"
            )
            or ""
        ).lower()

        content = (
            attrs.get(
                "content"
            )
            or ""
        )

        if not content:
            return

        if prop == "og:title":

            self.meta_og.append(
                content
            )

        elif (
            prop
            == "twitter:title"
        ):

            self.meta_twitter.append(
                content
            )

        elif name == "title":

            self.meta_title.append(
                content
            )

    def handle_data(
        self,
        data,
    ):

        if self.in_h1:
            self.h1.append(
                data
            )

    def handle_endtag(
        self,
        tag,
    ):

        if tag.lower() == "h1":
            self.in_h1 = False


def disney_is_metadata(
    title
):

    title = clean_title(
        title
    )

    if not title:
        return True

    bad = {
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

    if title.lower() in bad:
        return True

    if re.fullmatch(
        r"\d{1,2}",
        title,
    ):
        return True

    if re.fullmatch(
        r"new",
        title,
        re.I,
    ):
        return True

    # Disney 페이지에서 순위 표시로 들어오는
    # 숫자 + NEW 형태 차단
    if re.fullmatch(
        r"\d{1,2}\s*(NEW)?",
        title,
        re.I,
    ):
        return True

    return False


def disney_is_bad_title(
    title
):

    title = clean_title(
        title
    )

    if not title:
        return True

    if disney_is_metadata(
        title
    ):
        return True

    # 순위/국가 정보가 제목 앞뒤에 붙는 경우
    title = re.sub(
        r"^\d{1,2}\s*",
        "",
        title,
    )

    title = re.sub(
        r"\s+(NEW|New)$",
        "",
        title,
        flags=re.I,
    )

    title = clean_title(
        title
    )

    if not title:
        return True

    if disney_is_metadata(
        title
    ):
        return True

    return False


def choose_disney_title(
    candidates
):

    cleaned = []

    for title in candidates:

        title = clean_title(
            title
        )

        if not title:
            continue

        # HTML title 등에 붙는 NEW 제거
        title = re.sub(
            r"\s+(NEW|New)$",
            "",
            title,
            flags=re.I,
        )

        # 앞쪽 순위 제거
        title = re.sub(
            r"^\d{1,2}\s*",
            "",
            title,
        )

        title = clean_title(
            title
        )

        if disney_is_bad_title(
            title
        ):
            continue

        cleaned.append(
            title
        )

    if not cleaned:
        return ""

    # 한국어 제목이 있으면 우선
    for title in cleaned:

        if has_korean(title):
            return title

    return cleaned[0]


def get_disney_detail_title(
    href
):

    try:

        text = fetch_text(
            href
        )

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
            "".join(
                parser.h1
            )
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

    return choose_disney_title(
        candidates
    )


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
            "[Disney+] 페이지 실패:",
            e,
        )

        return []

    parser = DisneyEntityParser()

    try:
        parser.feed(text)
    except Exception:
        return []

    # --------------------------------------------------------
    # Disney entity URL 확보
    # --------------------------------------------------------

    urls = []
    seen_urls = set()

    for href in parser.items:

        full_url = urllib.parse.urljoin(
            DISNEY_URL,
            href,
        )

        if full_url in seen_urls:
            continue

        seen_urls.add(
            full_url
        )

        urls.append(
            full_url
        )

        if len(urls) >= SOURCE_CANDIDATE_LIMIT:
            break

    print(
        f"[Disney+] 후보 페이지 "
        f"{len(urls)}개"
    )

    if not urls:
        return []

    # --------------------------------------------------------
    # Disney 상세 페이지 병렬 요청
    # --------------------------------------------------------

    page_results = []

    def fetch_candidate(url):

        title = get_disney_detail_title(
            url
        )

        return (
            url,
            title,
        )

    with ThreadPoolExecutor(
        max_workers=PAGE_WORKERS
    ) as executor:

        futures = [
            executor.submit(
                fetch_candidate,
                url,
            )
            for url in urls
        ]

        for future in as_completed(
            futures
        ):

            try:

                url, title = (
                    future.result()
                )

            except Exception:
                continue

            title = clean_title(
                title
            )

            if disney_is_bad_title(
                title
            ):
                continue

            key = normalize_compare(
                title
            )

            if not key:
                continue

            page_results.append(
                (
                    url,
                    title,
                    key,
                )
            )

    # --------------------------------------------------------
    # 원래 페이지 순서를 최대한 유지
    # --------------------------------------------------------

    ordered = []

    result_map = {}

    for url, title, key in page_results:

        if key not in result_map:

            result_map[key] = (
                url,
                title,
            )

    for url in urls:

        title = ""

        for candidate_url, candidate_title in (
            result_map.values()
        ):

            if candidate_url == url:

                title = candidate_title
                break

        if not title:
            continue

        key = normalize_compare(
            title
        )

        if key:

            ordered.append(
                title
            )

    # --------------------------------------------------------
    # 중복 제거
    # --------------------------------------------------------

    candidates = []
    seen_titles = set()

    for title in ordered:

        key = normalize_compare(
            title
        )

        if not key:
            continue

        if key in seen_titles:
            continue

        seen_titles.add(
            key
        )

        candidates.append(
            title
        )

    print(
        f"[Disney+] 유효 제목 "
        f"{len(candidates)}개"
    )

    # --------------------------------------------------------
    # TMDB로 영화 / TV 판별
    #
    # 20개가 모두 채워지면 즉시 중단
    # --------------------------------------------------------

    movies = []
    tv = []

    seen_tmdb = set()

    for title in candidates:

        if (
            len(movies) >= 10
            and len(tv) >= 10
        ):
            break

        resolved = tmdb_resolve(
            title,
            None,
        )

        if not resolved:
            continue

        media_type = resolved.get(
            "media_type"
        )

        tmdb_id = resolved.get(
            "tmdb_id"
        )

        if media_type not in (
            "movie",
            "tv",
        ):
            continue

        if not tmdb_id:
            continue

        key = (
            f"{media_type}:{tmdb_id}"
        )

        if key in seen_tmdb:
            continue

        seen_tmdb.add(
            key
        )

        item = {
            "rank": 0,

            "title":
                resolved["title"],

            "original_title":
                title,

            "season_title":
                "",

            "platform":
                "Disney+",

            "category":
                (
                    "movie"
                    if media_type == "movie"
                    else "tv"
                ),

            "media_type":
                media_type,

            "tmdb_id":
                tmdb_id,

            "tmdb_title":
                resolved.get(
                    "tmdb_title"
                ),

            "tmdb_original_title":
                resolved.get(
                    "tmdb_original_title"
                ),
        }

        if media_type == "movie":

            if len(movies) >= 10:
                continue

            movies.append(
                item
            )

        else:

            if len(tv) >= 10:
                continue

            tv.append(
                item
            )

    # --------------------------------------------------------
    # 영화 / TV 각각 순위 부여
    # --------------------------------------------------------

    for rank, item in enumerate(
        movies,
        1,
    ):
        item["rank"] = rank

    for rank, item in enumerate(
        tv,
        1,
    ):
        item["rank"] = rank

    result = (
        movies
        + tv
    )

    print(
        f"[Disney+] 영화 "
        f"{len(movies)}개 / "
        f"TV {len(tv)}개"
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


def coupang_is_bad_title(
    title
):

    title = clean_title(
        title
    )

    if not title:
        return True

    if title.lower() in {
        x.lower()
        for x in COUPANG_BAD_TITLES
    }:
        return True

    patterns = [
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

    for pattern in patterns:

        if re.search(
            pattern,
            title,
            re.I,
        ):
            return True

    return len(title) < 2


def extract_coupang_titles(
    text
):

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

            if not key or key in seen:
                continue

            seen.add(key)

            result.append(title)

            if len(result) >= SOURCE_CANDIDATE_LIMIT:
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
            "[Coupang Play] 실패:",
            e,
        )

        return []

    titles = extract_coupang_titles(
        text
    )

    print(
        f"[Coupang Play] 후보 "
        f"{len(titles)}개"
    )

    if not titles:
        return []

    # --------------------------------------------------------
    # 영화 / TV 분리
    # --------------------------------------------------------

    movies = []
    tv = []

    seen_title = set()
    seen_tmdb = set()

    for title in titles:

        if (
            len(movies) >= 10
            and len(tv) >= 10
        ):
            break

        title = clean_title(
            title
        )

        if coupang_is_bad_title(
            title
        ):
            continue

        title_key = normalize_compare(
            title
        )

        if not title_key:
            continue

        if title_key in seen_title:
            continue

        seen_title.add(
            title_key
        )

        resolved = tmdb_resolve(
            title,
            None,
        )

        if not resolved:
            continue

        media_type = resolved.get(
            "media_type"
        )

        tmdb_id = resolved.get(
            "tmdb_id"
        )

        if media_type not in (
            "movie",
            "tv",
        ):
            continue

        if not tmdb_id:
            continue

        tmdb_key = (
            f"{media_type}:{tmdb_id}"
        )

        if tmdb_key in seen_tmdb:
            continue

        seen_tmdb.add(
            tmdb_key
        )

        item = {
            "rank": 0,

            "title":
                resolved["title"],

            "original_title":
                title,

            "season_title":
                "",

            "platform":
                "Coupang Play",

            "category":
                (
                    "movie"
                    if media_type == "movie"
                    else "tv"
                ),

            "media_type":
                media_type,

            "tmdb_id":
                tmdb_id,

            "tmdb_title":
                resolved.get(
                    "tmdb_title"
                ),

            "tmdb_original_title":
                resolved.get(
                    "tmdb_original_title"
                ),
        }

        if media_type == "movie":

            if len(movies) >= 10:
                continue

            movies.append(
                item
            )

        else:

            if len(tv) >= 10:
                continue

            tv.append(
                item
            )

    # --------------------------------------------------------
    # 영화 / TV 각각 순위
    # --------------------------------------------------------

    for rank, item in enumerate(
        movies,
        1,
    ):
        item["rank"] = rank

    for rank, item in enumerate(
        tv,
        1,
    ):
        item["rank"] = rank

    result = (
        movies
        + tv
    )

    print(
        f"[Coupang Play] 영화 "
        f"{len(movies)}개 / "
        f"TV {len(tv)}개"
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

    return (
        data
        if isinstance(data, dict)
        else {}
    )


def save_tmdb_details(
    data
):

    save_json(
        TMDB_DETAIL_FILE,
        data,
    )


def tmdb_get_detail(
    media_type,
    tmdb_id,
):

    if not media_type or not tmdb_id:
        return None

    data = tmdb_request(
        f"/{media_type}/{tmdb_id}",
        {
            "language":
                TMDB_LANGUAGE,

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
            data.get(
                "release_date"
            )
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
            data.get(
                "first_air_date"
            )
        )

    genres = []

    for genre in data.get(
        "genres",
        [],
    ):

        name = genre.get(
            "name"
        )

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

    directors = []

    credits = data.get(
        "credits",
        {},
    )

    for crew in credits.get(
        "crew",
        [],
    ):

        if crew.get(
            "job"
        ) == "Director":

            name = crew.get(
                "name"
            )

            if name:
                directors.append(
                    name
                )

    cast = []

    for person in credits.get(
        "cast",
        [],
    )[:10]:

        name = person.get(
            "name"
        )

        if name:
            cast.append(name)

    trailer_key = ""

    videos = data.get(
        "videos",
        {},
    )

    for video in videos.get(
        "results",
        [],
    ):

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
        "id":
            data.get("id"),

        "media_type":
            media_type,

        "title":
            title,

        "original_title":
            original_title,

        "poster_path":
            data.get(
                "poster_path"
            ),

        "backdrop_path":
            data.get(
                "backdrop_path"
            ),

        "vote_average":
            data.get(
                "vote_average"
            ),

        "vote_count":
            data.get(
                "vote_count"
            ),

        "release_date":
            release_date,

        "genres":
            genres,

        "runtime":
            runtime,

        "overview":
            data.get(
                "overview"
            )
            or "",

        "director":
            directors,

        "cast":
            cast,

        "trailer_key":
            trailer_key,

        "homepage":
            data.get(
                "homepage"
            )
            or "",

        "cached_at":
            iso_now(),
    }


def build_tmdb_details(
    current_items
):

    existing = load_tmdb_details()

    result = dict(existing)

    requested = set()

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

        if key in requested:
            continue

        requested.add(key)

        old = result.get(
            key
        )

        if isinstance(
            old,
            dict,
        ):

            if is_cache_fresh(
                old.get(
                    "cached_at"
                ),
                TMDB_DETAIL_CACHE_DAYS,
            ):

                if item.get("title"):
                    old["title"] = (
                        item["title"]
                    )

                result[key] = old

                continue

        print(
            "[TMDB DETAIL]",
            key,
        )

        detail = tmdb_get_detail(
            media_type,
            tmdb_id,
        )

        if detail:

            if item.get("title"):
                detail["title"] = (
                    item["title"]
                )

            result[key] = detail

        elif isinstance(
            old,
            dict,
        ):

            result[key] = old

    save_tmdb_details(
        result
    )

    return result


# ============================================================
# 랭킹 비교
# ============================================================

def same_content(
    a,
    b,
):

    if (
        a.get("platform")
        and b.get("platform")
        and a.get("platform")
        != b.get("platform")
    ):
        return False

    if (
        a.get("media_type")
        and b.get("media_type")
        and a.get("media_type")
        != b.get("media_type")
    ):
        return False

    a_id = a.get(
        "tmdb_id"
    )

    b_id = b.get(
        "tmdb_id"
    )

    if (
        a_id
        and b_id
        and str(a_id)
        == str(b_id)
    ):
        return True

    for key in (
        "original_title",
        "tmdb_original_title",
        "title",
        "tmdb_title",
    ):

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

        item["previous_rank"] = (
            old_rank
        )

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


# ============================================================
# 날짜 / history
# ============================================================

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
    platform,
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

    # 영화
    movie_items = [
        x
        for x in platform_items
        if x.get("media_type")
        == "movie"
    ]

    print()
    print(
        "[영화 TOP 10]"
    )

    for item in movie_items:

        print(
            f"{item.get('rank', ''):>2} | "
            f"{item.get('title', '')} | "
            f"{item.get('change', '')}"
        )

    # TV
    tv_items = [
        x
        for x in platform_items
        if x.get("media_type")
        == "tv"
    ]

    print()
    print(
        "[TV TOP 10]"
    )

    for item in tv_items:

        print(
            f"{item.get('rank', ''):>2} | "
            f"{item.get('title', '')} | "
            f"{item.get('change', '')}"
        )


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)
    print("OTT RANKING COLLECTOR")
    print("=" * 60)

    if not TMDB_API_KEY:

        print(
            "[ERROR] "
            "TMDB_API_KEY가 설정되어 있지 않습니다."
        )

        sys.exit(1)

    # --------------------------------------------------------
    # 캐시
    # --------------------------------------------------------

    load_tmdb_cache()
    cleanup_tmdb_cache()

    # --------------------------------------------------------
    # Netflix
    # --------------------------------------------------------

    netflix = get_netflix()

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
    # 현재 데이터
    # --------------------------------------------------------

    current = (
        netflix
        + disney
        + coupang
    )

    # --------------------------------------------------------
    # 이전 데이터
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
    # 변동
    # --------------------------------------------------------

    calculate_changes(
        current,
        previous,
    )

    # --------------------------------------------------------
    # TMDB 상세
    # --------------------------------------------------------

    print()
    print(
        "[TMDB] 상세정보 처리 중..."
    )

    build_tmdb_details(
        current
    )

    # --------------------------------------------------------
    # ranking.json
    # --------------------------------------------------------

    ranking_data = {
        "date":
            today_string(),

        "items":
            current,
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
            "date":
                today_string(),

            "items":
                current,
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
    # 최종 캐시
    # --------------------------------------------------------

    save_tmdb_cache()

    # --------------------------------------------------------
    # 결과
    # --------------------------------------------------------

    print()
    print("=" * 60)

    print(
        f"수집 완료 "
        f"({today_string()})"
    )

    print("=" * 60)

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
    print("=" * 60)

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
        "TMDB 상세 캐시:",
        len(
            load_tmdb_details()
        ),
    )

    print("=" * 60)


if __name__ == "__main__":
    main()
