import csv
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta


# =========================================================
# 기본 설정
# =========================================================

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

RANKING_FILE = "ranking.json"

HISTORY_FILE = "history.json"

COUNTRY_CODE = "KR"

KEEP_DAYS = 30


# =========================================================
# TMDB 설정
# =========================================================

TMDB_API_KEY = os.environ.get("TMDB_API_KEY")

TMDB_BASE_URL = "https://api.themoviedb.org/3"

TMDB_LANGUAGE = "ko-KR"

TMDB_REGION = "KR"


# =========================================================
# Netflix TSV
# =========================================================

csv.field_size_limit(sys.maxsize)


# =========================================================
# HTTP
# =========================================================

def fetch_text(url, timeout=30):

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/140.0 Safari/537.36"
            ),
            "Accept-Language": (
                "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7"
            ),
        },
    )

    with urllib.request.urlopen(
        req,
        timeout=timeout,
    ) as response:

        raw = response.read()

        charset = response.headers.get_content_charset()

        if charset:

            return raw.decode(
                charset,
                errors="replace",
            )

        return raw.decode(
            "utf-8",
            errors="replace",
        )


# =========================================================
# JSON HTTP
# =========================================================

def fetch_json(
    url,
    timeout=30,
):

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "OTT-Ranking-Collector/2.0"
            ),
            "Accept": "application/json",
        },
    )

    with urllib.request.urlopen(
        req,
        timeout=timeout,
    ) as response:

        raw = response.read()

        return json.loads(
            raw.decode(
                "utf-8",
                errors="replace",
            )
        )


# =========================================================
# 문자열 정리
# =========================================================

def normalize_title(value):

    if value is None:

        return ""

    value = str(value)

    value = value.replace(
        "\xa0",
        " ",
    )

    value = value.replace(
        "\u200b",
        "",
    )

    value = value.replace(
        "\ufeff",
        "",
    )

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value.strip()


def normalize_key(value):

    value = normalize_title(
        value
    ).lower()

    value = re.sub(
        r"[^0-9a-z가-힣]+",
        "",
        value,
    )

    return value


# =========================================================
# TMDB 키 확인
# =========================================================

def check_tmdb_key():

    if not TMDB_API_KEY:

        print(
            "TMDB API: 키 없음"
        )

        return False

    print(
        "TMDB API: 연결 설정됨"
    )

    return True


# =========================================================
# TMDB 요청
# =========================================================

def tmdb_request(
    endpoint,
    params,
):

    if not TMDB_API_KEY:

        return None

    query = dict(
        params
    )

    query["api_key"] = TMDB_API_KEY

    url = (
        TMDB_BASE_URL
        + endpoint
        + "?"
        + urllib.parse.urlencode(
            query
        )
    )

    try:

        return fetch_json(
            url,
            timeout=30,
        )

    except Exception as e:

        print(
            "TMDB API 요청 실패:",
            endpoint,
            e,
        )

        return None


# =========================================================
# TMDB 검색 결과 점수
# =========================================================

def tmdb_match_score(
    query_title,
    result,
):

    query_title = normalize_title(
        query_title
    )

    query_key = normalize_key(
        query_title
    )

    if not query_key:

        return 0

    candidates = []

    for field in [
        "title",
        "name",
        "original_title",
        "original_name",
    ]:

        value = normalize_title(
            result.get(
                field,
                "",
            )
        )

        if value:

            candidates.append(
                value
            )

    best = 0

    for candidate in candidates:

        candidate_key = normalize_key(
            candidate
        )

        if not candidate_key:

            continue

        if candidate_key == query_key:

            if candidate in {
                result.get(
                    "title",
                    "",
                ),
                result.get(
                    "name",
                    "",
                ),
            }:

                best = max(
                    best,
                    120,
                )

            else:

                best = max(
                    best,
                    115,
                )

        elif (
            query_key in candidate_key
            or candidate_key in query_key
        ):

            best = max(
                best,
                85,
            )

        else:

            query_words = set(
                re.findall(
                    r"[0-9a-z가-힣]+",
                    query_title.lower(),
                )
            )

            candidate_words = set(
                re.findall(
                    r"[0-9a-z가-힣]+",
                    candidate.lower(),
                )
            )

            if (
                query_words
                and candidate_words
            ):

                overlap = (
                    len(
                        query_words
                        & candidate_words
                    )
                    / max(
                        len(query_words),
                        1,
                    )
                )

                if overlap >= 0.8:

                    best = max(
                        best,
                        75,
                    )

                elif overlap >= 0.5:

                    best = max(
                        best,
                        50,
                    )

    try:

        popularity = float(
            result.get(
                "popularity",
                0,
            )
        )

    except Exception:

        popularity = 0

    best += min(
        popularity / 100,
        5,
    )

    return best


# =========================================================
# TMDB 한국어 번역 가져오기
#
# 핵심:
# 검색 결과의 title만 믿지 않고
# 실제 작품의 translations에서 ko 번역을 찾는다.
# =========================================================

def tmdb_translation_title(
    media_type,
    tmdb_id,
    fallback_title,
):

    if not tmdb_id:

        return fallback_title

    if media_type not in {
        "movie",
        "tv",
    }:

        return fallback_title

    endpoint = (
        "/"
        + media_type
        + "/"
        + str(tmdb_id)
        + "/translations"
    )

    data = tmdb_request(
        endpoint,
        {},
    )

    if not data:

        return fallback_title

    translations = data.get(
        "translations",
        [],
    )

    # -----------------------------------------------------
    # 한국어 번역 찾기
    # -----------------------------------------------------

    for translation in translations:

        iso_639_1 = normalize_title(
            translation.get(
                "iso_639_1",
                "",
            )
        ).lower()

        iso_3166_1 = normalize_title(
            translation.get(
                "iso_3166_1",
                "",
            )
        ).upper()

        if (
            iso_639_1 == "ko"
            and (
                iso_3166_1 == "KR"
                or not iso_3166_1
            )
        ):

            data_block = translation.get(
                "data",
                {},
            )

            if media_type == "movie":

                title = normalize_title(
                    data_block.get(
                        "title",
                        "",
                    )
                )

            else:

                title = normalize_title(
                    data_block.get(
                        "name",
                        "",
                    )
                )

            if title:

                return title

    # -----------------------------------------------------
    # 한국어가 있지만 국가코드가 다른 경우
    # -----------------------------------------------------

    for translation in translations:

        iso_639_1 = normalize_title(
            translation.get(
                "iso_639_1",
                "",
            )
        ).lower()

        if iso_639_1 != "ko":

            continue

        data_block = translation.get(
            "data",
            {},
        )

        if media_type == "movie":

            title = normalize_title(
                data_block.get(
                    "title",
                    "",
                )
            )

        else:

            title = normalize_title(
                data_block.get(
                    "name",
                    "",
                )
            )

        if title:

            return title

    return fallback_title


# =========================================================
# TMDB 작품 검색
# =========================================================

def tmdb_search_best(
    endpoint,
    original_title,
):

    original_title = normalize_title(
        original_title
    )

    if not original_title:

        return None

    data = tmdb_request(
        endpoint,
        {
            "query": original_title,
            "language": "ko-KR",
            "region": TMDB_REGION,
            "include_adult": "false",
            "page": 1,
        },
    )

    if not data:

        return None

    results = data.get(
        "results",
        [],
    )

    if not results:

        return None

    best_result = None
    best_score = -1

    for result in results[:20]:

        score = tmdb_match_score(
            original_title,
            result,
        )

        if score > best_score:

            best_score = score
            best_result = result

    if not best_result:

        return None

    return best_result


# =========================================================
# TMDB 영화 한국어 제목
# =========================================================

def tmdb_movie_title(
    original_title,
):

    original_title = normalize_title(
        original_title
    )

    if not original_title:

        return original_title, None

    print(
        "  TMDB 영화 검색:",
        original_title,
    )

    result = tmdb_search_best(
        "/search/movie",
        original_title,
    )

    if not result:

        print(
            "    → TMDB 검색 실패"
        )

        return original_title, None

    tmdb_id = result.get(
        "id"
    )

    fallback = normalize_title(
        result.get(
            "title",
            "",
        )
    )

    if not fallback:

        fallback = original_title

    korean_title = tmdb_translation_title(
        "movie",
        tmdb_id,
        fallback,
    )

    # 검색 결과의 한국어 title도 우선 사용
    if (
        korean_title == fallback
        and fallback
    ):

        search_title = normalize_title(
            result.get(
                "title",
                "",
            )
        )

        if search_title:

            korean_title = search_title

    print(
        "    →",
        korean_title,
        "(TMDB:",
        tmdb_id,
        ")",
    )

    return korean_title, tmdb_id


# =========================================================
# TMDB TV 한국어 제목
# =========================================================

def tmdb_tv_title(
    original_title,
):

    original_title = normalize_title(
        original_title
    )

    if not original_title:

        return original_title, None

    print(
        "  TMDB TV 검색:",
        original_title,
    )

    result = tmdb_search_best(
        "/search/tv",
        original_title,
    )

    if not result:

        print(
            "    → TMDB 검색 실패"
        )

        return original_title, None

    tmdb_id = result.get(
        "id"
    )

    fallback = normalize_title(
        result.get(
            "name",
            "",
        )
    )

    if not fallback:

        fallback = original_title

    korean_title = tmdb_translation_title(
        "tv",
        tmdb_id,
        fallback,
    )

    if (
        korean_title == fallback
        and fallback
    ):

        search_title = normalize_title(
            result.get(
                "name",
                "",
            )
        )

        if search_title:

            korean_title = search_title

    print(
        "    →",
        korean_title,
        "(TMDB:",
        tmdb_id,
        ")",
    )

    return korean_title, tmdb_id


# =========================================================
# TMDB 통합 검색
# Disney용
# =========================================================

def tmdb_multi_title(
    original_title,
):

    original_title = normalize_title(
        original_title
    )

    if not original_title:

        return (
            original_title,
            None,
            None,
        )

    print(
        "  TMDB 통합 검색:",
        original_title,
    )

    data = tmdb_request(
        "/search/multi",
        {
            "query": original_title,
            "language": "ko-KR",
            "include_adult": "false",
            "page": 1,
        },
    )

    if not data:

        return (
            original_title,
            None,
            None,
        )

    results = data.get(
        "results",
        [],
    )

    candidates = []

    for result in results[:20]:

        media_type = result.get(
            "media_type"
        )

        if media_type not in {
            "movie",
            "tv",
        }:

            continue

        score = tmdb_match_score(
            original_title,
            result,
        )

        candidates.append(
            (
                score,
                result,
            )
        )

    if not candidates:

        return (
            original_title,
            None,
            None,
        )

    candidates.sort(
        key=lambda x: x[0],
        reverse=True,
    )

    best_score, best_result = candidates[0]

    media_type = best_result.get(
        "media_type"
    )

    tmdb_id = best_result.get(
        "id"
    )

    if media_type == "movie":

        fallback = normalize_title(
            best_result.get(
                "title",
                "",
            )
        )

    else:

        fallback = normalize_title(
            best_result.get(
                "name",
                "",
            )
        )

    if not fallback:

        fallback = original_title

    korean_title = tmdb_translation_title(
        media_type,
        tmdb_id,
        fallback,
    )

    if (
        not korean_title
    ):

        korean_title = fallback

    print(
        "    →",
        korean_title,
        "(",
        media_type,
        "TMDB:",
        tmdb_id,
        "score:",
        round(best_score, 1),
        ")",
    )

    return (
        korean_title,
        tmdb_id,
        media_type,
    )


# =========================================================
# Netflix TMDB 제목 적용
# =========================================================

def apply_tmdb_netflix_titles(
    data,
):

    print("")
    print(
        "Netflix TMDB 한국어 제목 변환 중..."
    )

    if not check_tmdb_key():

        return data

    # -----------------------------------------------------
    # 영화
    # -----------------------------------------------------

    for item in data.get(
        "movies",
        [],
    ):

        original = normalize_title(
            item.get(
                "t",
                "",
            )
        )

        if not original:

            continue

        # 최초 영문 제목을 보존
        item["ot"] = original

        korean_title, tmdb_id = (
            tmdb_movie_title(
                original
            )
        )

        item["t"] = korean_title

        if tmdb_id:

            item["tmdb_id"] = tmdb_id

        time.sleep(0.20)

    # -----------------------------------------------------
    # TV
    # -----------------------------------------------------

    for item in data.get(
        "tv",
        [],
    ):

        original = normalize_title(
            item.get(
                "t",
                "",
            )
        )

        if not original:

            continue

        item["ot"] = original

        korean_title, tmdb_id = (
            tmdb_tv_title(
                original
            )
        )

        item["t"] = korean_title

        if tmdb_id:

            item["tmdb_id"] = tmdb_id

        time.sleep(0.20)

    return data


# =========================================================
# Netflix TSV
# =========================================================

def get_netflix_tsv():

    print(
        "Netflix TSV 다운로드 중..."
    )

    return fetch_text(
        NETFLIX_TSV_URL,
        timeout=60,
    )


def parse_netflix_tsv(
    text,
):

    reader = csv.DictReader(
        io.StringIO(text),
        delimiter="\t",
    )

    rows = list(reader)

    if not rows:

        raise RuntimeError(
            "Netflix TSV 데이터가 없습니다."
        )

    kr_rows = []

    for row in rows:

        country_iso = normalize_title(
            row.get(
                "country_iso2",
                "",
            )
        ).upper()

        country_name = normalize_title(
            row.get(
                "country_name",
                "",
            )
        )

        if (
            country_iso == COUNTRY_CODE
            or country_name.lower()
            == "south korea"
        ):

            kr_rows.append(
                row
            )

    if not kr_rows:

        raise RuntimeError(
            "Netflix 한국 데이터를 찾지 못했습니다."
        )

    weeks = sorted(
        {
            normalize_title(
                row.get(
                    "week",
                    "",
                )
            )
            for row in kr_rows
            if row.get("week")
        }
    )

    if not weeks:

        raise RuntimeError(
            "Netflix 한국 주차 정보를 찾지 못했습니다."
        )

    latest_week = weeks[-1]

    latest_rows = [
        row
        for row in kr_rows
        if normalize_title(
            row.get(
                "week",
                "",
            )
        )
        == latest_week
    ]

    movies = []
    tv = []

    for row in latest_rows:

        category = normalize_title(
            row.get(
                "category",
                "",
            )
        ).lower()

        try:

            rank = int(
                normalize_title(
                    row.get(
                        "weekly_rank",
                        "",
                    )
                )
            )

        except Exception:

            continue

        title = normalize_title(
            row.get(
                "show_title",
                "",
            )
        )

        season = normalize_title(
            row.get(
                "season_title",
                "",
            )
        )

        if not title:

            continue

        item = {
            "r": rank,
            "t": title,
        }

        if (
            season
            and season.upper() != "N/A"
            and season != title
        ):

            item["s"] = season

        if category == "films":

            movies.append(
                item
            )

        elif category == "tv":

            tv.append(
                item
            )

        elif category == "shows":

            tv.append(
                item
            )

        elif "film" in category:

            movies.append(
                item
            )

        elif "tv" in category:

            tv.append(
                item
            )

        elif "show" in category:

            tv.append(
                item
            )

    movies.sort(
        key=lambda x: x["r"]
    )

    tv.sort(
        key=lambda x: x["r"]
    )

    return {
        "week": latest_week,
        "movies": movies[:10],
        "tv": tv[:10],
    }


# =========================================================
# Netflix 공식 페이지
#
# TMDB 변환 전에 제목을 변경하지 않는다.
# 원래 TSV 제목을 보존하기 위해 보조적으로만 확인한다.
# =========================================================

def extract_netflix_titles_from_page(
    html,
):

    titles = []

    if not html:

        return titles

    patterns = [
        r"\[Button:\s*([^\]]+)\]",
        r'"title"\s*:\s*"([^"]{1,200})"',
        r'"name"\s*:\s*"([^"]{1,200})"',
        r'"show_title"\s*:\s*"([^"]{1,200})"',
    ]

    for pattern in patterns:

        try:

            matches = re.findall(
                pattern,
                html,
                flags=re.IGNORECASE,
            )

        except Exception:

            continue

        for value in matches:

            value = normalize_title(
                value
            )

            if not value:

                continue

            if len(value) > 200:

                continue

            low = value.lower()

            if low in {
                "my list",
                "watch",
                "explore",
                "image",
                "movies",
                "shows",
                "movie",
                "tv",
            }:

                continue

            if value not in titles:

                titles.append(
                    value
                )

    return titles


def apply_netflix_official_titles(
    data,
):

    print(
        "Netflix 한국 공식 페이지 확인 중..."
    )

    # -----------------------------------------------------
    # 중요:
    # 현재 Netflix TSV의 영문 제목을
    # 여기서 변경하지 않는다.
    #
    # TMDB가 정확한 제목 매칭을 해야 하므로
    # 공식 페이지 HTML의 불완전한 제목 추출 결과를
    # ranking title에 직접 적용하지 않는다.
    # -----------------------------------------------------

    try:

        movie_html = fetch_text(
            NETFLIX_KR_MOVIE_URL,
            timeout=30,
        )

        movie_titles = (
            extract_netflix_titles_from_page(
                movie_html
            )
        )

        print(
            "Netflix 영화 공식 페이지 확인:",
            len(movie_titles),
        )

    except Exception as e:

        print(
            "Netflix 영화 공식 페이지 확인 실패:",
            e,
        )

    try:

        tv_html = fetch_text(
            NETFLIX_KR_TV_URL,
            timeout=30,
        )

        tv_titles = (
            extract_netflix_titles_from_page(
                tv_html
            )
        )

        print(
            "Netflix TV 공식 페이지 확인:",
            len(tv_titles),
        )

    except Exception as e:

        print(
            "Netflix TV 공식 페이지 확인 실패:",
            e,
        )

    return data


# =========================================================
# Disney+
# =========================================================

def get_disney():

    print(
        "Disney+ 데이터 수집 중..."
    )

    html = fetch_text(
        DISNEY_URL,
        timeout=30,
    )

    titles = []

    patterns = [
        r'"title"\s*:\s*"([^"]+)"',
        r'"name"\s*:\s*"([^"]+)"',
        r'"contentTitle"\s*:\s*"([^"]+)"',
        r'aria-label="([^"]+)"',
    ]

    for pattern in patterns:

        try:

            matches = re.findall(
                pattern,
                html,
                flags=re.IGNORECASE,
            )

        except Exception:

            continue

        for value in matches:

            value = normalize_title(
                value
            )

            if not value:

                continue

            if len(value) > 100:

                continue

            if value not in titles:

                titles.append(
                    value
                )

    bad_words = {
        "Disney+",
        "Disney Plus",
        "Disney",
        "로그인",
        "가입",
        "검색",
        "메뉴",
        "홈",
        "시리즈",
        "영화",
        "오리지널",
        "프로필",
        "account",
        "login",
        "search",
        "menu",
        "home",
    }

    filtered = []

    for title in titles:

        if title in bad_words:

            continue

        if len(title) <= 1:

            continue

        low = title.lower()

        if "http://" in low:

            continue

        if "https://" in low:

            continue

        if "javascript" in low:

            continue

        if title not in filtered:

            filtered.append(
                title
            )

    return [
        {
            "r": index + 1,
            "t": title,
            "c": 0,
        }
        for index, title
        in enumerate(
            filtered[:10]
        )
    ]


# =========================================================
# Disney+ TMDB 제목 적용
# =========================================================

def apply_tmdb_disney_titles(
    items,
):

    print("")
    print(
        "Disney+ TMDB 한국어 제목 변환 중..."
    )

    if not check_tmdb_key():

        return items

    for item in items:

        original = normalize_title(
            item.get(
                "t",
                "",
            )
        )

        if not original:

            continue

        item["ot"] = original

        (
            korean_title,
            tmdb_id,
            media_type,
        ) = tmdb_multi_title(
            original
        )

        item["t"] = korean_title

        if tmdb_id:

            item["tmdb_id"] = tmdb_id

        if media_type:

            item["type"] = media_type

        time.sleep(0.20)

    return items


# =========================================================
# Coupang Play
# =========================================================

def get_coupang():

    print(
        "Coupang Play 데이터 수집 중..."
    )

    html = fetch_text(
        COUPANG_URL,
        timeout=30,
    )

    titles = []

    patterns = [
        r'"title"\s*:\s*"([^"]+)"',
        r'"name"\s*:\s*"([^"]+)"',
        r'"contentTitle"\s*:\s*"([^"]+)"',
    ]

    for pattern in patterns:

        try:

            matches = re.findall(
                pattern,
                html,
                flags=re.IGNORECASE,
            )

        except Exception:

            continue

        for value in matches:

            value = normalize_title(
                value
            )

            if not value:

                continue

            if len(value) > 100:

                continue

            if value not in titles:

                titles.append(
                    value
                )

    bad_patterns = [
        "autoplay",
        "auto play",
        "hero",
        "teaser",
        "trailer",
        "preview",
        "예고",
        "예고편",
        "트레일러",
        "next",
        "previous",
        "arrow",
        "icon",
        "오토플레이",
        "official trailer",
        "official teaser",
    ]

    filtered = []

    for title in titles:

        low = title.lower()

        bad = False

        for word in bad_patterns:

            if word.lower() in low:

                bad = True

                break

        if bad:

            continue

        if len(title) <= 1:

            continue

        if title not in filtered:

            filtered.append(
                title
            )

    return [
        {
            "r": index + 1,
            "t": title,
            "c": 0,
        }
        for index, title
        in enumerate(
            filtered[:20]
        )
    ]


# =========================================================
# 기존 ranking.json
# =========================================================

def load_ranking():

    if not os.path.exists(
        RANKING_FILE
    ):

        return None

    try:

        with open(
            RANKING_FILE,
            "r",
            encoding="utf-8",
        ) as f:

            return json.load(
                f
            )

    except Exception:

        return None


# =========================================================
# 순위 맵
# =========================================================

def previous_rank_map(
    items,
):

    result = {}

    for item in items or []:

        title = normalize_title(
            item.get(
                "t",
                "",
            )
        )

        original = normalize_title(
            item.get(
                "ot",
                "",
            )
        )

        rank = item.get(
            "r"
        )

        if rank is None:

            continue

        if title:

            result[
                normalize_key(title)
            ] = rank

        if original:

            result[
                normalize_key(original)
            ] = rank

    return result


# =========================================================
# 순위 변동 계산
# =========================================================

def calculate_changes(
    current_items,
    previous_items,
):

    previous = previous_rank_map(
        previous_items
    )

    for item in current_items:

        title = normalize_title(
            item.get(
                "t",
                "",
            )
        )

        original = normalize_title(
            item.get(
                "ot",
                "",
            )
        )

        current_rank = item.get(
            "r"
        )

        current_key = normalize_key(
            title
        )

        original_key = normalize_key(
            original
        )

        old_rank = None

        if current_key in previous:

            old_rank = previous[
                current_key
            ]

        elif original_key in previous:

            old_rank = previous[
                original_key
            ]

        if old_rank is None:

            item["c"] = "NEW"

            continue

        try:

            change = (
                int(old_rank)
                - int(current_rank)
            )

            item["c"] = change

        except Exception:

            item["c"] = 0


# =========================================================
# History
# =========================================================

def make_history_entry(
    date_string,
    netflix,
    disney,
    coupang,
):

    def rank_map(
        items,
    ):

        result = {}

        for item in items or []:

            title = normalize_title(
                item.get(
                    "t",
                    "",
                )
            )

            rank = item.get(
                "r"
            )

            if title and rank is not None:

                result[
                    title
                ] = rank

        return result

    return {
        "d": date_string,

        "n": {
            "m": rank_map(
                netflix.get(
                    "movies",
                    [],
                )
            ),

            "t": rank_map(
                netflix.get(
                    "tv",
                    [],
                )
            ),
        },

        "d+": rank_map(
            disney
        ),

        "c": rank_map(
            coupang
        ),
    }


# =========================================================
# History 읽기
# =========================================================

def load_history():

    if not os.path.exists(
        HISTORY_FILE
    ):

        return {
            "h": []
        }

    try:

        with open(
            HISTORY_FILE,
            "r",
            encoding="utf-8",
        ) as f:

            data = json.load(
                f
            )

        if not isinstance(
            data,
            dict,
        ):

            return {
                "h": []
            }

        if not isinstance(
            data.get("h"),
            list,
        ):

            data["h"] = []

        return data

    except Exception:

        return {
            "h": []
        }


# =========================================================
# History 저장
# =========================================================

def save_history(
    netflix,
    disney,
    coupang,
):

    history = load_history()

    korea_timezone = timezone(
        timedelta(hours=9)
    )

    today = (
        datetime.now(
            timezone.utc
        )
        .astimezone(
            korea_timezone
        )
        .strftime(
            "%Y-%m-%d"
        )
    )

    entry = make_history_entry(
        today,
        netflix,
        disney,
        coupang,
    )

    history["h"] = [
        item
        for item in history["h"]
        if item.get("d") != today
    ]

    history["h"].append(
        entry
    )

    history["h"].sort(
        key=lambda x: x.get(
            "d",
            "",
        )
    )

    history["h"] = history["h"][
        -KEEP_DAYS:
    ]

    with open(
        HISTORY_FILE,
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            history,
            f,
            ensure_ascii=False,
            indent=2,
        )


# =========================================================
# JSON 저장
# =========================================================

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


# =========================================================
# 최초 실행
# =========================================================

def set_initial_changes(
    netflix,
    disney,
    coupang,
):

    for item in netflix.get(
        "movies",
        [],
    ):

        item["c"] = 0

    for item in netflix.get(
        "tv",
        [],
    ):

        item["c"] = 0

    for item in disney:

        item["c"] = 0

    for item in coupang:

        item["c"] = 0


# =========================================================
# 메인
# =========================================================

def main():

    print("")
    print("=" * 60)
    print("OTT RANKING COLLECTOR")
    print("=" * 60)
    print("")

    # -----------------------------------------------------
    # TMDB 상태
    # -----------------------------------------------------

    if TMDB_API_KEY:

        print(
            "TMDB API: 연결 설정됨"
        )

    else:

        print(
            "TMDB API: 키 없음"
        )

    # -----------------------------------------------------
    # 기존 ranking.json
    # -----------------------------------------------------

    previous = load_ranking()

    # -----------------------------------------------------
    # Netflix
    # -----------------------------------------------------

    print("")
    print("[1/3] Netflix")

    netflix_tsv = get_netflix_tsv()

    netflix = parse_netflix_tsv(
        netflix_tsv
    )

    netflix = apply_netflix_official_titles(
        netflix
    )

    netflix = apply_tmdb_netflix_titles(
        netflix
    )

    # -----------------------------------------------------
    # Disney+
    # -----------------------------------------------------

    print("")
    print("[2/3] Disney+")

    try:

        disney = get_disney()

        disney = apply_tmdb_disney_titles(
            disney
        )

    except Exception as e:

        print(
            "Disney+ 수집 실패:",
            e,
        )

        disney = []

    # -----------------------------------------------------
    # Coupang Play
    # -----------------------------------------------------

    print("")
    print("[3/3] Coupang Play")

    try:

        coupang = get_coupang()

    except Exception as e:

        print(
            "Coupang Play 수집 실패:",
            e,
        )

        coupang = []

    # -----------------------------------------------------
    # 순위 변동
    # -----------------------------------------------------

    print("")
    print(
        "순위 변동 계산 중..."
    )

    if previous:

        old_netflix = previous.get(
            "netflix",
            {},
        )

        old_disney = previous.get(
            "disney",
            [],
        )

        old_coupang = previous.get(
            "coupang",
            [],
        )

        calculate_changes(
            netflix["movies"],
            old_netflix.get(
                "movies",
                [],
            ),
        )

        calculate_changes(
            netflix["tv"],
            old_netflix.get(
                "tv",
                [],
            ),
        )

        calculate_changes(
            disney,
            old_disney,
        )

        calculate_changes(
            coupang,
            old_coupang,
        )

    else:

        print(
            "기존 ranking.json이 없어 최초 실행으로 처리합니다."
        )

        set_initial_changes(
            netflix,
            disney,
            coupang,
        )

    # -----------------------------------------------------
    # 현재 시간
    # -----------------------------------------------------

    updated_at = datetime.now(
        timezone.utc
    ).isoformat()

    # -----------------------------------------------------
    # ranking.json
    # -----------------------------------------------------

    ranking = {
        "updated_at": updated_at,
        "netflix": netflix,
        "disney": disney,
        "coupang": coupang,
    }

    save_json(
        RANKING_FILE,
        ranking,
    )

    # -----------------------------------------------------
    # history.json
    # -----------------------------------------------------

    save_history(
        netflix,
        disney,
        coupang,
    )

    # -----------------------------------------------------
    # 결과
    # -----------------------------------------------------

    print("")
    print("=" * 60)
    print("수집 완료")
    print("=" * 60)
    print("")

    print(
        "Netflix 주차:",
        netflix.get(
            "week",
            "",
        ),
    )

    print(
        "Netflix 영화:",
        len(
            netflix.get(
                "movies",
                [],
            )
        ),
    )

    print(
        "Netflix TV:",
        len(
            netflix.get(
                "tv",
                [],
            )
        ),
    )

    print(
        "Disney+:",
        len(disney),
    )

    print(
        "Coupang Play:",
        len(coupang),
    )

    print("")

    print(
        "Netflix 영화 TOP 10"
    )

    for item in netflix.get(
        "movies",
        [],
    ):

        print(
            item.get("r"),
            item.get("t"),
            "change=",
            item.get("c"),
        )

    print("")

    print(
        "Netflix TV TOP 10"
    )

    for item in netflix.get(
        "tv",
        [],
    ):

        title = item.get(
            "t",
            "",
        )

        season = item.get(
            "s",
            "",
        )

        if season:

            print(
                item.get("r"),
                title,
                "(",
                season,
                ")",
                "change=",
                item.get("c"),
            )

        else:

            print(
                item.get("r"),
                title,
                "change=",
                item.get("c"),
            )

    print("")

    print(
        "Disney+ TOP 10"
    )

    for item in disney:

        print(
            item.get("r"),
            item.get("t"),
            "change=",
            item.get("c"),
        )

    print("")

    print(
        "Coupang Play TOP 20"
    )

    for item in coupang:

        print(
            item.get("r"),
            item.get("t"),
            "change=",
            item.get("c"),
        )

    print("")

    print(
        "ranking.json 저장 완료"
    )

    print(
        "history.json 저장 완료"
    )

    print("")


# =========================================================
# 실행
# =========================================================

if __name__ == "__main__":

    main()
