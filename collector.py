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


# ============================================================
# TMDB
# ============================================================

TMDB_API_KEY = os.environ.get("TMDB_API_KEY")

TMDB_BASE_URL = "https://api.themoviedb.org/3"

TMDB_LANGUAGE = "ko-KR"
TMDB_REGION = "KR"

TMDB_CACHE = {}


# ============================================================
# HTTP
# ============================================================

def make_request(url, timeout=30):

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/140.0 Safari/537.36"
            ),
            "Accept-Language": (
                "ko-KR,ko;q=0.9,"
                "en-US;q=0.8,en;q=0.7"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,"
                "application/json;q=0.9,*/*;q=0.8"
            ),
        },
    )

    return urllib.request.urlopen(
        req,
        timeout=timeout,
    )


def fetch_text(url, timeout=30):

    with make_request(
        url,
        timeout=timeout,
    ) as response:

        data = response.read()

        charset = response.headers.get_content_charset()

        if not charset:
            charset = "utf-8"

        return data.decode(
            charset,
            errors="replace",
        )


def fetch_json(url, timeout=30):

    text = fetch_text(
        url,
        timeout=timeout,
    )

    return json.loads(text)


# ============================================================
# 문자열
# ============================================================

def normalize_title(text):

    if not text:
        return ""

    text = html.unescape(
        str(text)
    )

    text = re.sub(
        r"<[^>]+>",
        " ",
        text,
    )

    text = text.replace(
        "\xa0",
        " ",
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


def normalize_compare(text):

    text = normalize_title(
        text
    ).lower()

    text = re.sub(
        r"[^\w가-힣]+",
        "",
        text,
    )

    return text


def has_korean(text):

    return bool(
        text
        and re.search(
            r"[가-힣]",
            text,
        )
    )


# ============================================================
# TMDB
# ============================================================

def check_tmdb_key():

    if TMDB_API_KEY:

        print(
            "TMDB API: 연결 설정됨"
        )

        return True

    print(
        "TMDB API: 키 없음"
    )

    return False


def tmdb_request(
    path,
    params=None,
):

    if not TMDB_API_KEY:
        return None

    if params is None:
        params = {}

    params = dict(params)

    params["api_key"] = TMDB_API_KEY

    url = (
        TMDB_BASE_URL
        + path
        + "?"
        + urllib.parse.urlencode(
            params
        )
    )

    try:

        return fetch_json(
            url,
            timeout=20,
        )

    except Exception as e:

        print(
            f"TMDB 오류: {e}"
        )

        return None


# ============================================================
# TMDB 검색 점수
# ============================================================

def tmdb_match_score(
    original_title,
    result,
):

    if not result:
        return -999

    original_title = normalize_title(
        original_title
    )

    target = normalize_compare(
        original_title
    )

    if not target:
        return -999

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
                normalize_title(
                    value
                )
            )

    best = 0

    for candidate in candidates:

        candidate_normalized = (
            normalize_compare(
                candidate
            )
        )

        if not candidate_normalized:
            continue

        if candidate_normalized == target:

            best = max(
                best,
                100,
            )

        elif (
            target in candidate_normalized
            or
            candidate_normalized in target
        ):

            best = max(
                best,
                85,
            )

        else:

            target_words = set(
                re.findall(
                    r"[a-z0-9가-힣]+",
                    original_title.lower(),
                )
            )

            candidate_words = set(
                re.findall(
                    r"[a-z0-9가-힣]+",
                    candidate.lower(),
                )
            )

            if (
                target_words
                and candidate_words
            ):

                common = (
                    target_words
                    &
                    candidate_words
                )

                ratio = (
                    len(common)
                    /
                    max(
                        len(target_words),
                        len(candidate_words),
                    )
                )

                best = max(
                    best,
                    int(
                        ratio * 80
                    ),
                )

    try:

        popularity = float(
            result.get(
                "popularity",
                0,
            )
        )

        best += min(
            popularity / 100,
            10,
        )

    except Exception:

        pass

    return best


# ============================================================
# TMDB 검색
# ============================================================

def tmdb_search(
    endpoint,
    original_title,
):

    cache_key = (
        f"search:"
        f"{endpoint}:"
        f"{original_title}"
    )

    if cache_key in TMDB_CACHE:

        return TMDB_CACHE[
            cache_key
        ]

    data = tmdb_request(
        endpoint,
        {
            "query": original_title,
            "language": TMDB_LANGUAGE,
            "region": TMDB_REGION,
            "include_adult": "false",
            "page": 1,
        },
    )

    if not data:

        TMDB_CACHE[
            cache_key
        ] = None

        return None

    results = data.get(
        "results",
        [],
    )

    if not results:

        TMDB_CACHE[
            cache_key
        ] = None

        return None

    best = None
    best_score = -999

    for item in results[:20]:

        score = tmdb_match_score(
            original_title,
            item,
        )

        if score > best_score:

            best_score = score
            best = item

    if best_score < 35:

        best = None

    TMDB_CACHE[
        cache_key
    ] = best

    return best


# ============================================================
# TMDB 작품 정보
#
# 핵심:
# 제목뿐 아니라
# tmdb_id / media_type / original_title 확보
# ============================================================

def tmdb_find(
    original_title,
    preferred_type=None,
):

    original_title = normalize_title(
        original_title
    )

    if not original_title:
        return None

    if not TMDB_API_KEY:
        return None

    cache_key = (
        "find:"
        + str(preferred_type)
        + ":"
        + original_title
    )

    if cache_key in TMDB_CACHE:

        return TMDB_CACHE[
            cache_key
        ]

    candidates = []

    if preferred_type == "movie":

        result = tmdb_search(
            "/search/movie",
            original_title,
        )

        if result:

            candidates.append(
                (
                    "movie",
                    result,
                )
            )

    elif preferred_type == "tv":

        result = tmdb_search(
            "/search/tv",
            original_title,
        )

        if result:

            candidates.append(
                (
                    "tv",
                    result,
                )
            )

    else:

        movie = tmdb_search(
            "/search/movie",
            original_title,
        )

        tv = tmdb_search(
            "/search/tv",
            original_title,
        )

        if movie:

            candidates.append(
                (
                    "movie",
                    movie,
                )
            )

        if tv:

            candidates.append(
                (
                    "tv",
                    tv,
                )
            )

    if not candidates:

        TMDB_CACHE[
            cache_key
        ] = None

        return None

    best_type = None
    best_result = None
    best_score = -999

    for media_type, result in candidates:

        score = tmdb_match_score(
            original_title,
            result,
        )

        if score > best_score:

            best_score = score
            best_type = media_type
            best_result = result

    if not best_result:

        TMDB_CACHE[
            cache_key
        ] = None

        return None

    tmdb_id = best_result.get(
        "id"
    )

    if not tmdb_id:

        TMDB_CACHE[
            cache_key
        ] = None

        return None

    if best_type == "movie":

        localized_title = normalize_title(
            best_result.get(
                "title"
            )
            or ""
        )

        original_tmdb_title = normalize_title(
            best_result.get(
                "original_title"
            )
            or ""
        )

    else:

        localized_title = normalize_title(
            best_result.get(
                "name"
            )
            or ""
        )

        original_tmdb_title = normalize_title(
            best_result.get(
                "original_name"
            )
            or ""
        )

    result = {
        "tmdb_id": int(tmdb_id),
        "media_type": best_type,
        "localized_title": localized_title,
        "original_title": (
            original_tmdb_title
            or original_title
        ),
    }

    TMDB_CACHE[
        cache_key
    ] = result

    return result


# ============================================================
# TMDB 번역
# ============================================================

def tmdb_translation_title(
    media_type,
    tmdb_id,
    fallback_title,
):

    if not tmdb_id:

        return fallback_title

    cache_key = (
        f"translation:"
        f"{media_type}:"
        f"{tmdb_id}"
    )

    if cache_key in TMDB_CACHE:

        return TMDB_CACHE[
            cache_key
        ]

    data = tmdb_request(
        f"/{media_type}/{tmdb_id}/translations"
    )

    if not data:

        TMDB_CACHE[
            cache_key
        ] = fallback_title

        return fallback_title

    translations = data.get(
        "translations",
        [],
    )

    preferred = None

    for item in translations:

        if (
            item.get(
                "iso_639_1"
            ) == "ko"
            and
            item.get(
                "iso_3166_1"
            ) == "KR"
        ):

            preferred = item
            break

    if not preferred:

        for item in translations:

            if (
                item.get(
                    "iso_639_1"
                ) == "ko"
            ):

                preferred = item
                break

    if preferred:

        data_block = (
            preferred.get(
                "data",
                {}
            )
        )

        title = normalize_title(
            data_block.get(
                "title"
            )
            or
            data_block.get(
                "name"
            )
            or ""
        )

        if title:

            TMDB_CACHE[
                cache_key
            ] = title

            return title

    TMDB_CACHE[
        cache_key
    ] = fallback_title

    return fallback_title


# ============================================================
# TMDB 제목 + ID
# ============================================================

def tmdb_title_info(
    original_title,
    media_type,
):

    original_title = normalize_title(
        original_title
    )

    fallback = {
        "title": original_title,
        "tmdb_id": None,
        "media_type": media_type,
        "tmdb_original_title": original_title,
    }

    if not TMDB_API_KEY:

        return fallback

    print(
        f"TMDB {media_type} 검색: "
        f"{original_title}"
    )

    result = tmdb_find(
        original_title,
        media_type,
    )

    if not result:

        print(
            "  → TMDB 검색 실패"
        )

        return fallback

    tmdb_id = result.get(
        "tmdb_id"
    )

    actual_media_type = (
        result.get(
            "media_type"
        )
        or media_type
    )

    localized = normalize_title(
        result.get(
            "localized_title",
            ""
        )
    )

    tmdb_original = normalize_title(
        result.get(
            "original_title",
            ""
        )
    )

    korean_title = localized

    if (
        not korean_title
        or
        not has_korean(
            korean_title
        )
    ):

        korean_title = (
            tmdb_translation_title(
                actual_media_type,
                tmdb_id,
                original_title,
            )
        )

    if not korean_title:

        korean_title = original_title

    print(
        f"  → 제목: {korean_title}"
    )

    print(
        f"  → TMDB ID: {tmdb_id}"
        f" / {actual_media_type}"
    )

    return {
        "title": korean_title,
        "tmdb_id": tmdb_id,
        "media_type": actual_media_type,
        "tmdb_original_title": (
            tmdb_original
            or original_title
        ),
    }


# ============================================================
# 기존 함수 호환용
# ============================================================

def tmdb_title(
    original_title,
    media_type,
):

    info = tmdb_title_info(
        original_title,
        media_type,
    )

    return info.get(
        "title",
        original_title,
    )


# ============================================================
# Netflix 한국 페이지 파서
# ============================================================

class NetflixLinkParser(
    HTMLParser
):

    def __init__(self):

        super().__init__(
            convert_charrefs=True
        )

        self.links = []

        self.current_href = None
        self.current_text = []

    def handle_starttag(
        self,
        tag,
        attrs,
    ):

        if tag.lower() != "a":
            return

        attributes = dict(
            attrs
        )

        href = attributes.get(
            "href",
            "",
        )

        if not href:
            return

        if "/title/" in href:

            self.current_href = href
            self.current_text = []

    def handle_data(
        self,
        data,
    ):

        if (
            self.current_href
            is not None
        ):

            self.current_text.append(
                data
            )

    def handle_endtag(
        self,
        tag,
    ):

        if tag.lower() != "a":
            return

        if (
            self.current_href
            is None
        ):

            return

        title = normalize_title(
            "".join(
                self.current_text
            )
        )

        if title:

            self.links.append(
                {
                    "title": title,
                    "href": self.current_href,
                }
            )

        self.current_href = None
        self.current_text = []


# ============================================================
# Netflix 한국 페이지 제목
# ============================================================

def get_netflix_korean_titles():

    result = {}

    for url in (
        NETFLIX_KR_MOVIE_URL,
        NETFLIX_KR_TV_URL,
    ):

        try:

            text = fetch_text(
                url,
                timeout=40,
            )

        except Exception as e:

            print(
                f"Netflix 한국 페이지 오류: "
                f"{e}"
            )

            continue

        parser = NetflixLinkParser()

        try:

            parser.feed(text)

        except Exception as e:

            print(
                f"Netflix HTML 파싱 오류: "
                f"{e}"
            )

            continue

        for item in parser.links:

            title = normalize_title(
                item.get(
                    "title",
                    "",
                )
            )

            if not title:
                continue

            if not has_korean(
                title
            ):
                continue

            key = normalize_compare(
                title
            )

            if key:

                result[key] = title

    print(
        f"Netflix 한국 페이지 "
        f"한글 제목 {len(result)}개 확보"
    )

    return result


# ============================================================
# Netflix
# ============================================================

def get_netflix():

    print("")
    print("=" * 60)
    print("NETFLIX")
    print("=" * 60)

    korean_titles = (
        get_netflix_korean_titles()
    )

    try:

        text = fetch_text(
            NETFLIX_TSV_URL,
            timeout=60,
        )

    except Exception as e:

        print(
            f"Netflix TSV 오류: {e}"
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
                "country_iso2"
            )
            or
            row.get(
                "country_code"
            )
            or ""
        )

        if (
            country.upper()
            != COUNTRY_CODE
        ):

            continue

        rows.append(row)

    if not rows:

        print(
            "Netflix 한국 데이터 없음"
        )

        return []

    weeks = sorted(
        {
            row.get("week")
            for row in rows
            if row.get("week")
        },
        reverse=True,
    )

    if not weeks:

        print(
            "Netflix 주차 데이터 없음"
        )

        return []

    latest_week = weeks[0]

    print(
        f"Netflix 최신 주차: "
        f"{latest_week}"
    )

    latest_rows = [
        row
        for row in rows
        if row.get(
            "week"
        ) == latest_week
    ]

    movies = [
        row
        for row in latest_rows
        if "film"
        in row.get(
            "category",
            "",
        ).lower()
    ]

    tv = [
        row
        for row in latest_rows
        if (
            "tv"
            in row.get(
                "category",
                "",
            ).lower()
            or
            "series"
            in row.get(
                "category",
                "",
            ).lower()
        )
    ]

    def process(
        source,
        media_type,
    ):

        source = sorted(
            source,
            key=lambda x: int(
                x.get(
                    "weekly_rank"
                )
                or 999
            ),
        )

        output = []

        for row in source[:10]:

            rank = int(
                row.get(
                    "weekly_rank"
                )
                or 0
            )

            original_title = normalize_title(
                row.get(
                    "show_title"
                )
                or ""
            )

            if not original_title:
                continue

            season_title = normalize_title(
                row.get(
                    "season_title"
                )
                or "N/A"
            )

            # ------------------------------------------------
            # TMDB 정보
            # ------------------------------------------------

            tmdb_info = tmdb_title_info(
                original_title,
                media_type,
            )

            korean_title = tmdb_info.get(
                "title",
                original_title,
            )

            # ------------------------------------------------
            # TMDB가 한국 제목을 못 찾았을 경우
            # Netflix 한국 페이지 제목 사용
            # ------------------------------------------------

            if not has_korean(
                korean_title
            ):

                original_key = normalize_compare(
                    original_title
                )

                if original_key in korean_titles:

                    korean_title = (
                        korean_titles[
                            original_key
                        ]
                    )

                else:

                    found = None

                    for key, value in (
                        korean_titles.items()
                    ):

                        if (
                            key
                            and
                            (
                                key in original_key
                                or
                                original_key in key
                            )
                        ):

                            found = value
                            break

                    if found:

                        korean_title = found

            if not korean_title:

                korean_title = original_title

            output.append(
                {
                    "rank": rank,
                    "title": korean_title,
                    "original_title": original_title,
                    "tmdb_original_title": (
                        tmdb_info.get(
                            "tmdb_original_title",
                            original_title,
                        )
                    ),
                    "tmdb_id": (
                        tmdb_info.get(
                            "tmdb_id"
                        )
                    ),
                    "media_type": (
                        tmdb_info.get(
                            "media_type",
                            media_type,
                        )
                    ),
                    "season_title": season_title,
                    "platform": "Netflix",
                    "category": media_type,
                    "week": latest_week,
                }
            )

        return output

    movie_items = process(
        movies,
        "movie",
    )

    tv_items = process(
        tv,
        "tv",
    )

    print(
        f"Netflix 영화 "
        f"{len(movie_items)}개"
    )

    print(
        f"Netflix TV "
        f"{len(tv_items)}개"
    )

    return (
        movie_items
        + tv_items
    )


# ============================================================
# Disney+ HTML parser
# ============================================================

class DisneyEntityParser(
    HTMLParser
):

    def __init__(self):

        super().__init__(
            convert_charrefs=True
        )

        self.links = []

        self.in_anchor = False
        self.current_href = ""
        self.current_attrs = {}

    def handle_starttag(
        self,
        tag,
        attrs,
    ):

        if tag.lower() != "a":
            return

        attributes = dict(
            attrs
        )

        href = attributes.get(
            "href",
            "",
        )

        if not href:
            return

        if not re.search(
            r"/browse/entity-"
            r"[a-zA-Z0-9-]+",
            href,
        ):

            return

        self.in_anchor = True

        self.current_href = href

        self.current_attrs = attributes

    def handle_endtag(
        self,
        tag,
    ):

        if tag.lower() != "a":
            return

        if not self.in_anchor:
            return

        self.links.append(
            {
                "href": self.current_href,
                "attrs": dict(
                    self.current_attrs
                ),
            }
        )

        self.in_anchor = False
        self.current_href = ""
        self.current_attrs = {}


# ============================================================
# Disney 메타데이터 판별
# ============================================================

def disney_is_metadata(
    text,
):

    text = normalize_title(
        text
    )

    if not text:
        return True

    if re.match(
        r"^\d{4}\s*[•·|]",
        text,
    ):

        return True

    metadata_words = [
        "드라마",
        "코미디",
        "액션",
        "어드벤처",
        "모험",
        "스릴러",
        "범죄",
        "리얼리티",
        "로맨스",
        "판타지",
        "호러",
        "공포",
        "SF",
        "다큐멘터리",
        "경찰/탐정",
        "애니메이션",
        "슈퍼 히어로",
    ]

    parts = re.split(
        r"[•·,]",
        text,
    )

    parts = [
        p.strip()
        for p in parts
        if p.strip()
    ]

    if parts:

        genre_count = 0

        for part in parts:

            if part in metadata_words:

                genre_count += 1

        if genre_count == len(parts):

            return True

    return False


# ============================================================
# Disney 잘못된 제목 차단
# ============================================================

def disney_is_bad_title(
    text,
):

    text = normalize_title(
        text
    )

    if not text:
        return True

    if disney_is_metadata(
        text
    ):

        return True

    bad_titles = {
        "오스트레일리아",
        "대한민국",
        "한국",
        "미국",
        "일본",
        "중국",
        "캐나다",
        "영국",
        "프랑스",
        "독일",
        "호주",
        "Australia",
        "South Korea",
        "Korea",
        "United States",
        "Japan",
        "China",
        "Canada",
        "United Kingdom",
        "France",
        "Germany",
    }

    if text in bad_titles:

        return True

    bad_patterns = [
        r"^Disney\+?$",
        r"^Disney Plus$",
        r"^로그인$",
        r"^가입$",
        r"^더 알아보기$",
        r"^NEW$",
        r"^New$",
        r"^toggle$",
        r"^standard monthly$",
        r"^premium monthly$",
    ]

    for pattern in bad_patterns:

        if re.match(
            pattern,
            text,
            flags=re.I,
        ):

            return True

    return False


# ============================================================
# Disney 상세 페이지 제목 파서
# ============================================================

class DisneyDetailParser(
    HTMLParser
):

    def __init__(self):

        super().__init__(
            convert_charrefs=True
        )

        self.h1_text = []
        self.title_text = []
        self.meta_title = ""

        self.in_h1 = False
        self.in_title = False

    def handle_starttag(
        self,
        tag,
        attrs,
    ):

        tag = tag.lower()

        attributes = dict(
            attrs
        )

        if tag == "h1":

            self.in_h1 = True
            self.h1_text = []

        elif tag == "title":

            self.in_title = True
            self.title_text = []

        elif tag == "meta":

            prop = (
                attributes.get(
                    "property",
                    "",
                )
                or
                attributes.get(
                    "name",
                    "",
                )
            ).lower()

            if prop in (
                "og:title",
                "twitter:title",
            ):

                content = attributes.get(
                    "content",
                    "",
                )

                if content:

                    self.meta_title = normalize_title(
                        content
                    )

    def handle_data(
        self,
        data,
    ):

        if self.in_h1:

            self.h1_text.append(
                data
            )

        if self.in_title:

            self.title_text.append(
                data
            )

    def handle_endtag(
        self,
        tag,
    ):

        tag = tag.lower()

        if tag == "h1":

            self.in_h1 = False

        elif tag == "title":

            self.in_title = False

    def get_h1(self):

        return normalize_title(
            "".join(
                self.h1_text
            )
        )

    def get_title(self):

        return normalize_title(
            "".join(
                self.title_text
            )
        )


# ============================================================
# Disney 상세 페이지 제목
# ============================================================

def get_disney_detail_title(
    href,
):

    if not href:
        return ""

    if href.startswith("/"):

        url = (
            "https://www.disneyplus.com"
            + href
        )

    elif href.startswith("https://"):

        url = href

    else:

        url = (
            "https://www.disneyplus.com/"
            + href.lstrip("/")
        )

    try:

        text = fetch_text(
            url,
            timeout=25,
        )

    except Exception as e:

        print(
            f"  상세 페이지 오류: {e}"
        )

        return ""

    parser = DisneyDetailParser()

    try:

        parser.feed(text)

    except Exception as e:

        print(
            f"  상세 HTML 파싱 오류: {e}"
        )

    # --------------------------------------------------------
    # 1. H1
    # --------------------------------------------------------

    h1 = parser.get_h1()

    if (
        h1
        and
        not disney_is_bad_title(h1)
    ):

        return h1

    # --------------------------------------------------------
    # 2. OG title
    # --------------------------------------------------------

    if (
        parser.meta_title
        and
        not disney_is_bad_title(
            parser.meta_title
        )
    ):

        value = parser.meta_title

        value = re.sub(
            r"\s*\|\s*Disney\+.*$",
            "",
            value,
            flags=re.I,
        )

        value = normalize_title(
            value
        )

        if (
            value
            and
            not disney_is_bad_title(value)
        ):

            return value

    # --------------------------------------------------------
    # 3. title 태그
    # --------------------------------------------------------

    page_title = parser.get_title()

    if page_title:

        page_title = re.sub(
            r"\s*\|\s*Disney\+.*$",
            "",
            page_title,
            flags=re.I,
        )

        page_title = re.sub(
            r"\s*-\s*Disney\+.*$",
            "",
            page_title,
            flags=re.I,
        )

        page_title = normalize_title(
            page_title
        )

        if (
            page_title
            and
            not disney_is_bad_title(
                page_title
            )
        ):

            return page_title

    # --------------------------------------------------------
    # 4. JSON
    # --------------------------------------------------------

    patterns = [
        r'"headline"\s*:\s*"([^"]+)"',
        r'"name"\s*:\s*"([^"]+)"',
    ]

    for pattern in patterns:

        matches = re.findall(
            pattern,
            text,
            flags=re.I,
        )

        for value in matches:

            value = normalize_title(
                value
            )

            if (
                value
                and
                not disney_is_bad_title(
                    value
                )
            ):

                return value

    return ""


# ============================================================
# Disney entity ID
# ============================================================

def disney_entity_id(
    href,
):

    if not href:
        return ""

    match = re.search(
        r"/browse/entity-"
        r"([a-zA-Z0-9-]+)",
        href,
    )

    if not match:
        return ""

    return match.group(1)


# ============================================================
# Disney entity 추출
# ============================================================

def extract_disney_entities(
    section,
):

    parser = DisneyEntityParser()

    try:

        parser.feed(section)

    except Exception as e:

        print(
            f"Disney entity 파싱 오류: {e}"
        )

        return []

    result = []

    seen = set()

    for item in parser.links:

        href = item.get(
            "href",
            "",
        )

        entity_id = disney_entity_id(
            href
        )

        if not entity_id:
            continue

        if entity_id in seen:
            continue

        seen.add(
            entity_id
        )

        result.append(
            {
                "id": entity_id,
                "href": href,
            }
        )

    return result


# ============================================================
# Disney+
# ============================================================

def get_disney():

    print("")
    print("=" * 60)
    print("DISNEY+")
    print("=" * 60)

    try:

        text = fetch_text(
            DISNEY_URL,
            timeout=40,
        )

    except Exception as e:

        print(
            f"Disney+ 페이지 오류: {e}"
        )

        return []

    markers = [
        "오늘 한국의 TOP 10",
        "오늘 한국의 TOP10",
        "한국의 TOP 10",
        "한국의 TOP10",
        "Top 10 in South Korea Today",
    ]

    position = -1
    marker = ""

    for item in markers:

        pos = text.find(
            item
        )

        if pos >= 0:

            position = pos
            marker = item
            break

    if position < 0:

        print(
            "Disney+: TOP 10 영역 없음"
        )

        return []

    print(
        f"Disney+: TOP 10 발견 → {marker}"
    )

    section = text[
        position:
        position + 120000
    ]

    entities = extract_disney_entities(
        section
    )

    print(
        f"Disney+: entity 후보 "
        f"{len(entities)}개 발견"
    )

    if not entities:

        print(
            "Disney+: entity를 찾지 못했습니다."
        )

        return []

    output = []

    used_ids = set()

    for entity in entities:

        if len(output) >= 10:
            break

        entity_id = entity.get(
            "id",
            "",
        )

        href = entity.get(
            "href",
            "",
        )

        if (
            not entity_id
            or
            entity_id in used_ids
        ):

            continue

        print("")

        print(
            f"Disney 후보 "
            f"{len(output) + 1}: "
            f"{entity_id}"
        )

        title = get_disney_detail_title(
            href
        )

        if not title:

            print(
                "  → 제목 확인 실패"
            )

            continue

        if disney_is_bad_title(
            title
        ):

            print(
                f"  → 잘못된 제목 제외: "
                f"{title}"
            )

            continue

        used_ids.add(
            entity_id
        )

        # ----------------------------------------------------
        # TMDB 정보
        # ----------------------------------------------------

        tmdb_info = None

        if has_korean(title):

            # 한국어 제목은 TV → 영화 순서로 찾되
            # 결과의 실제 media_type을 사용
            tmdb_info = tmdb_find(
                title,
                "tv",
            )

            if not tmdb_info:

                tmdb_info = tmdb_find(
                    title,
                    "movie",
                )

        else:

            tmdb_info = tmdb_find(
                title,
                "tv",
            )

            if not tmdb_info:

                tmdb_info = tmdb_find(
                    title,
                    "movie",
                )

        if tmdb_info:

            tmdb_id = tmdb_info.get(
                "tmdb_id"
            )

            media_type = tmdb_info.get(
                "media_type",
                "tv",
            )

            tmdb_original_title = tmdb_info.get(
                "original_title",
                title,
            )

            korean_title = tmdb_info.get(
                "localized_title"
            ) or title

            # 한국 제목이 확실하지 않으면
            # 번역 API를 한 번 더 확인
            if not has_korean(
                korean_title
            ):

                translated = tmdb_translation_title(
                    media_type,
                    tmdb_id,
                    title,
                )

                if has_korean(
                    translated
                ):

                    korean_title = translated

        else:

            tmdb_id = None

            media_type = "tv"

            tmdb_original_title = title

            korean_title = title

        print(
            f"  → 최종 제목: "
            f"{korean_title}"
        )

        print(
            f"  → TMDB ID: "
            f"{tmdb_id}"
            f" / {media_type}"
        )

        if disney_is_bad_title(
            korean_title
        ):

            print(
                f"  → 최종 제목 이상으로 제외: "
                f"{korean_title}"
            )

            continue

        rank = len(output) + 1

        output.append(
            {
                "rank": rank,
                "title": korean_title,
                "original_title": title,
                "tmdb_original_title": (
                    tmdb_original_title
                ),
                "tmdb_id": tmdb_id,
                "media_type": media_type,
                "platform": "Disney+",
                "category": "top10",
                "url": href,
            }
        )

        print(
            f"Disney+ {rank:02d}: "
            f"{korean_title}"
        )

    print("")

    print(
        f"Disney+ 최종 TOP 10 "
        f"{len(output)}개 확보"
    )

    return output


# ============================================================
# Coupang Play
# ============================================================

def get_coupang():

    print("")
    print("=" * 60)
    print("COUPANG PLAY")
    print("=" * 60)

    try:

        text = fetch_text(
            COUPANG_URL,
            timeout=40,
        )

    except Exception as e:

        print(
            f"쿠팡플레이 페이지 오류: {e}"
        )

        return []

    titles = []

    patterns = [
        r'"title"\s*:\s*"([^"]+)"',
        r'"name"\s*:\s*"([^"]+)"',
        r'"contentTitle"\s*:\s*"([^"]+)"',
    ]

    bad_words = [
        "로그인",
        "회원가입",
        "쿠팡플레이",
        "무료체험",
        "검색",
        "더보기",
        "login",
        "sign up",
    ]

    for pattern in patterns:

        matches = re.findall(
            pattern,
            text,
            flags=re.I,
        )

        for value in matches:

            value = normalize_title(
                value
            )

            if not value:
                continue

            if value in titles:
                continue

            if any(
                bad.lower()
                in value.lower()
                for bad in bad_words
            ):

                continue

            titles.append(
                value
            )

            if len(titles) >= 10:
                break

        if len(titles) >= 10:
            break

    output = []

    for index, title in enumerate(
        titles[:10],
        start=1,
    ):

        # ----------------------------------------------------
        # Coupang도 TMDB 연결
        # ----------------------------------------------------

        tmdb_info = tmdb_find(
            title,
            None,
        )

        if tmdb_info:

            tmdb_id = tmdb_info.get(
                "tmdb_id"
            )

            media_type = tmdb_info.get(
                "media_type"
            )

            localized_title = tmdb_info.get(
                "localized_title"
            )

            tmdb_original_title = tmdb_info.get(
                "original_title",
                title,
            )

            if (
                localized_title
                and
                has_korean(
                    localized_title
                )
            ):

                final_title = localized_title

            else:

                translated = tmdb_translation_title(
                    media_type,
                    tmdb_id,
                    title,
                )

                if (
                    translated
                    and
                    has_korean(
                        translated
                    )
                ):

                    final_title = translated

                else:

                    final_title = title

        else:

            tmdb_id = None
            media_type = None
            tmdb_original_title = title
            final_title = title

        output.append(
            {
                "rank": index,
                "title": final_title,
                "original_title": title,
                "tmdb_original_title": (
                    tmdb_original_title
                ),
                "tmdb_id": tmdb_id,
                "media_type": media_type,
                "platform": "Coupang Play",
                "category": "top10",
            }
        )

        print(
            f"Coupang Play "
            f"{index:02d}: "
            f"{final_title}"
            f" / TMDB {tmdb_id}"
        )

    print(
        f"Coupang Play "
        f"{len(output)}개"
    )

    return output


# ============================================================
# JSON
# ============================================================

def load_json(
    filename,
    default,
):

    if not os.path.exists(
        filename
    ):

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
            f"{filename} 읽기 오류: "
            f"{e}"
        )

        return default


def save_json(
    filename,
    data,
):

    with open(
        filename,
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2,
        )


# ============================================================
# 작품 동일성 확인
#
# 1순위: TMDB ID
# 2순위: TMDB 원제
# 3순위: 현재 제목
# 4순위: 기존 원제
# ============================================================

def same_work(
    current_item,
    old_item,
):

    current_tmdb_id = (
        current_item.get(
            "tmdb_id"
        )
    )

    old_tmdb_id = (
        old_item.get(
            "tmdb_id"
        )
    )

    if (
        current_tmdb_id
        and
        old_tmdb_id
    ):

        try:

            if int(current_tmdb_id) == int(
                old_tmdb_id
            ):

                return True

        except Exception:

            pass

    current_candidates = [
        current_item.get(
            "tmdb_original_title",
            "",
        ),
        current_item.get(
            "original_title",
            "",
        ),
        current_item.get(
            "title",
            "",
        ),
    ]

    old_candidates = [
        old_item.get(
            "tmdb_original_title",
            "",
        ),
        old_item.get(
            "original_title",
            "",
        ),
        old_item.get(
            "title",
            "",
        ),
    ]

    current_keys = {
        normalize_compare(x)
        for x in current_candidates
        if normalize_compare(x)
    }

    old_keys = {
        normalize_compare(x)
        for x in old_candidates
        if normalize_compare(x)
    }

    if current_keys & old_keys:

        return True

    return False


# ============================================================
# 최근 History에서 이전 순위 찾기
#
# 전날 데이터만 보는 것이 아니라
# 최근 30일 history를 뒤에서부터 확인한다.
#
# 따라서:
#
# 3위
# ↓
# 순위권 밖
# ↓
# 순위권 밖
# ↓
# 7위
#
# 이런 경우에도
# 이전 3위를 찾아서 -4로 계산한다.
# ============================================================

def find_previous_rank_from_history(
    history,
    current_item,
    current_date=None,
):

    if not history:
        return None

    # 최신 날짜부터 확인
    history_sorted = sorted(
        history,
        key=lambda x: x.get(
            "date",
            "",
        ),
        reverse=True,
    )

    for snapshot in history_sorted:

        snapshot_date = snapshot.get(
            "date",
            "",
        )

        if (
            current_date
            and
            snapshot_date
            == current_date
        ):

            # 오늘 데이터는 아직 비교하지 않음
            continue

        old_items = snapshot.get(
            "items",
            [],
        )

        if not isinstance(
            old_items,
            list,
        ):

            continue

        # 같은 플랫폼끼리만 비교
        platform = current_item.get(
            "platform",
            "",
        )

        for old_item in old_items:

            if old_item.get(
                "platform",
                "",
            ) != platform:

                continue

            if same_work(
                current_item,
                old_item,
            ):

                rank = old_item.get(
                    "rank"
                )

                if rank is not None:

                    try:

                        return int(rank)

                    except Exception:

                        pass

    return None


# ============================================================
# 기존 ranking.json에서도 이전 순위 찾기
#
# 기존 history가 없거나 오래된 경우를 위한 보조 기능
# ============================================================

def find_previous_rank(
    previous_items,
    current_item,
):

    if not previous_items:
        return None

    platform = current_item.get(
        "platform",
        "",
    )

    for old in previous_items:

        if old.get(
            "platform",
            "",
        ) != platform:

            continue

        if same_work(
            current_item,
            old,
        ):

            rank = old.get(
                "rank"
            )

            if rank is not None:

                try:

                    return int(rank)

                except Exception:

                    pass

    return None


# ============================================================
# 변화 계산
#
# NEW를 절대로 만들지 않는다.
#
# 이전 기록이 있으면:
#
# 10위 → 5위 = +5
# 5위 → 8위 = -3
# 동일      = 0
#
# 이전 기록 자체가 없으면:
#
# change = ""
# ============================================================

def calculate_changes(
    current,
    previous,
    history=None,
    current_date=None,
):

    if history is None:

        history = []

    for item in current:

        old_rank = None

        # ----------------------------------------------------
        # 1. 최근 30일 History 우선
        # ----------------------------------------------------

        old_rank = (
            find_previous_rank_from_history(
                history,
                item,
                current_date,
            )
        )

        # ----------------------------------------------------
        # 2. History에서 못 찾으면
        #    기존 ranking.json 사용
        # ----------------------------------------------------

        if old_rank is None:

            old_rank = (
                find_previous_rank(
                    previous,
                    item,
                )
            )

        current_rank = item.get(
            "rank"
        )

        item[
            "previous_rank"
        ] = old_rank

        # ----------------------------------------------------
        # 이전 기록이 전혀 없는 작품
        # ----------------------------------------------------

        if old_rank is None:

            item[
                "change"
            ] = ""

            continue

        # ----------------------------------------------------
        # 순위 상승
        # ----------------------------------------------------

        if current_rank < old_rank:

            item[
                "change"
            ] = (
                f"+{old_rank - current_rank}"
            )

        # ----------------------------------------------------
        # 순위 하락
        # ----------------------------------------------------

        elif current_rank > old_rank:

            item[
                "change"
            ] = (
                f"-{current_rank - old_rank}"
            )

        # ----------------------------------------------------
        # 동일
        # ----------------------------------------------------

        else:

            item[
                "change"
            ] = "0"

    return current


# ============================================================
# 날짜
# ============================================================

def korea_now():

    return (
        datetime.now(
            timezone.utc
        )
        + timedelta(hours=9)
    )


def today_string():

    return korea_now().strftime(
        "%Y-%m-%d"
    )


# ============================================================
# History 정리
# ============================================================

def cleanup_history(
    history,
):

    cutoff = (
        korea_now()
        - timedelta(
            days=KEEP_DAYS
        )
    ).strftime(
        "%Y-%m-%d"
    )

    result = []

    for item in history:

        if item.get(
            "date",
            "",
        ) >= cutoff:

            result.append(
                item
            )

    return result


# ============================================================
# MAIN
# ============================================================

def main():

    print("")
    print("=" * 60)
    print("OTT RANKING COLLECTOR")
    print("=" * 60)

    today = today_string()

    print(
        f"실행일: {today}"
    )

    check_tmdb_key()

    # --------------------------------------------------------
    # 수집
    # --------------------------------------------------------

    netflix = get_netflix()

    disney = get_disney()

    coupang = get_coupang()

    current = (
        netflix
        + disney
        + coupang
    )

    # --------------------------------------------------------
    # 기존 ranking.json
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

    else:

        previous = previous_data

    # --------------------------------------------------------
    # 기존 history
    # --------------------------------------------------------

    history = load_json(
        HISTORY_FILE,
        [],
    )

    if isinstance(
        history,
        dict,
    ):

        history = history.get(
            "history",
            [],
        )

    if not isinstance(
        history,
        list,
    ):

        history = []

    # --------------------------------------------------------
    # History 정리 전 현재까지의 기록을 사용
    # --------------------------------------------------------

    current = calculate_changes(
        current,
        previous,
        history,
        today,
    )

    # --------------------------------------------------------
    # ranking.json
    # --------------------------------------------------------

    save_json(
        RANKING_FILE,
        current,
    )

    # --------------------------------------------------------
    # History 저장
    # --------------------------------------------------------

    # 같은 날짜에 Actions가 재실행되었을 경우
    # 기존 날짜 기록을 중복으로 쌓지 않는다.
    history = [
        item
        for item in history
        if item.get(
            "date",
            "",
        ) != today
    ]

    history.append(
        {
            "date": today,
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
    # 출력
    # --------------------------------------------------------

    print("")
    print("=" * 30)
    print("OTT RANKING")
    print("=" * 30)

    for platform in (
        "Netflix",
        "Disney+",
        "Coupang Play",
    ):

        print("")

        print(
            f"[{platform}]"
        )

        items = [
            x
            for x in current
            if x.get(
                "platform"
            )
            == platform
        ]

        for item in items:

            title = item.get(
                "title",
                "",
            )

            original = item.get(
                "original_title",
                "",
            )

            change = item.get(
                "change",
                "",
            )

            tmdb_id = item.get(
                "tmdb_id"
            )

            media_type = item.get(
                "media_type"
            )

            if (
                original
                and
                original != title
            ):

                print(
                    f"{item.get('rank'):02d}. "
                    f"{title} "
                    f"[{original}] "
                    f"({change}) "
                    f"TMDB={tmdb_id}/{media_type}"
                )

            else:

                print(
                    f"{item.get('rank'):02d}. "
                    f"{title} "
                    f"({change}) "
                    f"TMDB={tmdb_id}/{media_type}"
                )

    print("")
    print("=" * 30)
    print("저장 완료")
    print("=" * 30)


# ============================================================
# 실행
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except KeyboardInterrupt:

        print(
            "사용자에 의해 중단되었습니다."
        )

        sys.exit(1)

    except Exception as e:

        print(
            f"치명적 오류: {e}"
        )

        raise
