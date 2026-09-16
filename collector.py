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

# TMDB 상세정보 파일
TMDB_DETAILS_FILE = "tmdb.json"

# 상세정보 캐시 기간
TMDB_DETAIL_CACHE_DAYS = 7


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
                normalize_title(value)
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
                    / max(
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
# TMDB 양쪽 검색
# ============================================================

def tmdb_find_match(
    original_title,
    media_type=None,
):

    original_title = normalize_title(
        original_title
    )

    if not original_title:
        return None

    if not TMDB_API_KEY:
        return None

    if media_type == "movie":

        result = tmdb_search(
            "/search/movie",
            original_title,
        )

        if not result:
            return None

        return {
            "id": result.get("id"),
            "media_type": "movie",
            "result": result,
        }

    if media_type == "tv":

        result = tmdb_search(
            "/search/tv",
            original_title,
        )

        if not result:
            return None

        return {
            "id": result.get("id"),
            "media_type": "tv",
            "result": result,
        }

    # --------------------------------------------------------
    # TV + 영화 둘 다 검색
    # --------------------------------------------------------

    tv_result = tmdb_search(
        "/search/tv",
        original_title,
    )

    movie_result = tmdb_search(
        "/search/movie",
        original_title,
    )

    candidates = []

    if tv_result:

        candidates.append(
            (
                tmdb_match_score(
                    original_title,
                    tv_result,
                ),
                "tv",
                tv_result,
            )
        )

    if movie_result:

        candidates.append(
            (
                tmdb_match_score(
                    original_title,
                    movie_result,
                ),
                "movie",
                movie_result,
            )
        )

    if not candidates:
        return None

    candidates.sort(
        key=lambda x: x[0],
        reverse=True,
    )

    score, result_type, result = (
        candidates[0]
    )

    if score < 35:
        return None

    return {
        "id": result.get("id"),
        "media_type": result_type,
        "result": result,
    }


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
# TMDB 작품 정보 정리
# ============================================================

def tmdb_resolve(
    original_title,
    media_type=None,
):

    original_title = normalize_title(
        original_title
    )

    result_info = tmdb_find_match(
        original_title,
        media_type,
    )

    if not result_info:

        return {
            "title": original_title,
            "tmdb_id": None,
            "media_type": media_type,
            "tmdb_title": "",
            "tmdb_original_title": "",
        }

    tmdb_id = result_info.get(
        "id"
    )

    resolved_type = (
        result_info.get(
            "media_type"
        )
        or media_type
    )

    result = result_info.get(
        "result",
        {},
    )

    if resolved_type == "movie":

        localized = normalize_title(
            result.get(
                "title"
            )
            or ""
        )

        tmdb_original = normalize_title(
            result.get(
                "original_title"
            )
            or ""
        )

    else:

        localized = normalize_title(
            result.get(
                "name"
            )
            or ""
        )

        tmdb_original = normalize_title(
            result.get(
                "original_name"
            )
            or ""
        )

    # --------------------------------------------------------
    # 한국어 제목 확인
    # --------------------------------------------------------

    final_title = localized

    if not has_korean(
        final_title
    ):

        translated = (
            tmdb_translation_title(
                resolved_type,
                tmdb_id,
                localized or original_title,
            )
        )

        if translated:

            final_title = translated

    if not final_title:

        final_title = original_title

    return {
        "title": final_title,
        "tmdb_id": tmdb_id,
        "media_type": resolved_type,
        "tmdb_title": localized,
        "tmdb_original_title": tmdb_original,
    }


# ============================================================
# 기존 호환용 TMDB 제목 함수
# ============================================================

def tmdb_title(
    original_title,
    media_type,
):

    resolved = tmdb_resolve(
        original_title,
        media_type,
    )

    return resolved.get(
        "title",
        original_title,
    )


# ============================================================
# TMDB 상세정보
# ============================================================

def load_tmdb_details():

    if not os.path.exists(
        TMDB_DETAILS_FILE
    ):

        return {}

    try:

        with open(
            TMDB_DETAILS_FILE,
            "r",
            encoding="utf-8",
        ) as f:

            data = json.load(f)

        if isinstance(
            data,
            dict,
        ):

            return data

    except Exception as e:

        print(
            f"[TMDB CACHE] "
            f"불러오기 실패: {e}"
        )

    return {}


def save_tmdb_details(
    data,
):

    try:

        with open(
            TMDB_DETAILS_FILE,
            "w",
            encoding="utf-8",
        ) as f:

            json.dump(
                data,
                f,
                ensure_ascii=False,
                indent=2,
            )

        print(
            f"[TMDB CACHE] "
            f"{TMDB_DETAILS_FILE} 저장 완료 "
            f"({len(data)}개)"
        )

    except Exception as e:

        print(
            f"[TMDB CACHE] "
            f"저장 실패: {e}"
        )


def tmdb_get_detail(
    media_type,
    tmdb_id,
):

    if not TMDB_API_KEY:
        return None

    if not tmdb_id:
        return None

    if media_type not in (
        "tv",
        "movie",
    ):
        return None

    try:

        data = tmdb_request(
            f"/{media_type}/{tmdb_id}",
            {
                "language": "ko-KR",
                "append_to_response":
                    "credits,videos",
            },
        )

        if not data:
            return None

        credits = (
            data.get("credits")
            or {}
        )

        # ----------------------------------------------------
        # 감독
        # ----------------------------------------------------

        directors = []

        for person in credits.get(
            "crew",
            [],
        ):

            if (
                person.get("job")
                == "Director"
            ):

                name = person.get(
                    "name"
                )

                if (
                    name
                    and
                    name not in directors
                ):

                    directors.append(
                        name
                    )

        # TV 감독 정보가 없는 경우 제작자
        if (
            not directors
            and
            media_type == "tv"
        ):

            for person in data.get(
                "created_by",
                [],
            ):

                name = person.get(
                    "name"
                )

                if (
                    name
                    and
                    name not in directors
                ):

                    directors.append(
                        name
                    )

        # ----------------------------------------------------
        # 출연진
        # ----------------------------------------------------

        cast = []

        for person in credits.get(
            "cast",
            [],
        )[:10]:

            name = person.get(
                "name"
            )

            if (
                name
                and
                name not in cast
            ):

                cast.append(
                    name
                )

        # ----------------------------------------------------
        # 장르
        # ----------------------------------------------------

        genres = []

        for genre in data.get(
            "genres",
            [],
        ):

            name = genre.get(
                "name"
            )

            if name:

                genres.append(
                    name
                )

        # ----------------------------------------------------
        # 개봉일 / 첫 방송일
        # ----------------------------------------------------

        if media_type == "tv":

            release_date = (
                data.get(
                    "first_air_date",
                    "",
                )
            )

        else:

            release_date = (
                data.get(
                    "release_date",
                    "",
                )
            )

        # ----------------------------------------------------
        # 러닝타임
        # ----------------------------------------------------

        runtime = data.get(
            "runtime"
        )

        if (
            not runtime
            and
            media_type == "tv"
        ):

            runtimes = (
                data.get(
                    "episode_run_time"
                )
                or []
            )

            if runtimes:

                runtime = runtimes[0]

        # ----------------------------------------------------
        # 예고편
        # ----------------------------------------------------

        trailer_key = None

        videos = (
            data.get("videos")
            or {}
        )

        video_results = (
            videos.get("results")
            or []
        )

        # 공식 YouTube Trailer
        for video in video_results:

            if (
                video.get("site")
                == "YouTube"
                and
                video.get("type")
                == "Trailer"
                and
                video.get("official")
                is True
            ):

                trailer_key = (
                    video.get("key")
                )

                break

        # 일반 Trailer
        if not trailer_key:

            for video in video_results:

                if (
                    video.get("site")
                    == "YouTube"
                    and
                    video.get("type")
                    == "Trailer"
                ):

                    trailer_key = (
                        video.get("key")
                    )

                    break

        # 아무 YouTube 영상
        if not trailer_key:

            for video in video_results:

                if (
                    video.get("site")
                    == "YouTube"
                ):

                    trailer_key = (
                        video.get("key")
                    )

                    break

        # ----------------------------------------------------
        # 제목
        # ----------------------------------------------------

        if media_type == "tv":

            korean_title = (
                data.get("name")
                or
                data.get("original_name")
                or ""
            )

            original_title = (
                data.get("original_name")
                or
                data.get("name")
                or ""
            )

        else:

            korean_title = (
                data.get("title")
                or
                data.get("original_title")
                or ""
            )

            original_title = (
                data.get("original_title")
                or
                data.get("title")
                or ""
            )

        # ----------------------------------------------------
        # Blogger에 필요한 정보만 저장
        # ----------------------------------------------------

        return {

            "id": data.get(
                "id"
            ),

            "media_type": media_type,

            "title": korean_title,

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
                ) or "",

            "director":
                directors,

            "cast":
                cast,

            "trailer_key":
                trailer_key,

            "homepage":
                data.get(
                    "homepage"
                ) or "",
        }

    except Exception as e:

        print(
            f"[TMDB DETAIL ERROR] "
            f"{media_type}/{tmdb_id}: {e}"
        )

        return None


def build_tmdb_details(
    current_items,
):

    existing = (
        load_tmdb_details()
    )

    result = {}

    now = datetime.now(
        timezone.utc
    )

    for item in current_items:

        tmdb_id = item.get(
            "tmdb_id"
        )

        media_type = item.get(
            "media_type"
        )

        if not tmdb_id:
            continue

        if media_type not in (
            "tv",
            "movie",
        ):
            continue

        key = (
            f"{media_type}:"
            f"{tmdb_id}"
        )

        old = existing.get(
            key
        )

        # ----------------------------------------------------
        # 기존 캐시 확인
        # ----------------------------------------------------

        if old:

            cached_at = old.get(
                "cached_at"
            )

            if cached_at:

                try:

                    cached_time = (
                        datetime.fromisoformat(
                            cached_at.replace(
                                "Z",
                                "+00:00",
                            )
                        )
                    )

                    age = (
                        now
                        - cached_time
                    )

                    if (
                        age.days
                        <
                        TMDB_DETAIL_CACHE_DAYS
                    ):

                        # ranking에서 확정한 제목 유지
                        if item.get(
                            "title"
                        ):

                            old["title"] = (
                                item["title"]
                            )

                        result[key] = old

                        print(
                            f"[TMDB CACHE] "
                            f"재사용 {key}"
                        )

                        continue

                except Exception:

                    pass

        # ----------------------------------------------------
        # 새 TMDB 상세정보 요청
        # ----------------------------------------------------

        print(
            f"[TMDB DETAIL] 요청 "
            f"{media_type}/{tmdb_id}"
        )

        detail = tmdb_get_detail(
            media_type,
            tmdb_id,
        )

        if detail:

            # ranking.json에서 이미 확정된 제목을 우선
            if item.get(
                "title"
            ):

                detail["title"] = (
                    item["title"]
                )

            # ranking의 원본 제목도 있으면 유지
            if item.get(
                "original_title"
            ):

                detail[
                    "ranking_original_title"
                ] = item[
                    "original_title"
                ]

            detail[
                "cached_at"
            ] = now.isoformat()

            result[key] = detail

        elif old:

            # API 오류가 발생해도 기존 데이터 유지

            if item.get(
                "title"
            ):

                old["title"] = (
                    item["title"]
                )

            result[key] = old

    return result


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

        if (
            "/title/"
            in href
        ):

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
                    "href":
                        self.current_href,
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

        parser = (
            NetflixLinkParser()
        )

        try:

            parser.feed(
                text
            )

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

        rows.append(
            row
        )

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

            original_title = (
                normalize_title(
                    row.get(
                        "show_title"
                    )
                    or ""
                )
            )

            if not original_title:
                continue

            season_title = (
                normalize_title(
                    row.get(
                        "season_title"
                    )
                    or "N/A"
                )
            )

            print(
                f"TMDB {media_type} 검색: "
                f"{original_title}"
            )

            resolved = tmdb_resolve(
                original_title,
                media_type,
            )

            korean_title = (
                resolved.get(
                    "title",
                    original_title,
                )
            )

            # ------------------------------------------------
            # Netflix 한국 페이지 제목으로 보정
            # ------------------------------------------------

            if not has_korean(
                korean_title
            ):

                original_key = (
                    normalize_compare(
                        original_title
                    )
                )

                if (
                    original_key
                    in korean_titles
                ):

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
                                key
                                in original_key
                                or
                                original_key
                                in key
                            )
                        ):

                            found = value
                            break

                    if found:

                        korean_title = found

            if not korean_title:

                korean_title = (
                    original_title
                )

            output.append(
                {
                    "rank": rank,

                    "title":
                        korean_title,

                    "original_title":
                        original_title,

                    "season_title":
                        season_title,

                    "platform":
                        "Netflix",

                    "category":
                        media_type,

                    "week":
                        latest_week,

                    "tmdb_id":
                        resolved.get(
                            "tmdb_id"
                        ),

                    "media_type":
                        (
                            resolved.get(
                                "media_type"
                            )
                            or
                            media_type
                        ),

                    "tmdb_title":
                        resolved.get(
                            "tmdb_title",
                            "",
                        ),

                    "tmdb_original_title":
                        resolved.get(
                            "tmdb_original_title",
                            "",
                        ),
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
        +
        tv_items
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

        self.current_attrs = (
            attributes
        )

    def handle_endtag(
        self,
        tag,
    ):

        if (
            tag.lower() != "a"
        ):

            return

        if not self.in_anchor:
            return

        self.links.append(
            {
                "href":
                    self.current_href,

                "attrs":
                    dict(
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

        if (
            genre_count
            ==
            len(parts)
        ):

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
# Disney 제목 후보 선택
# ============================================================

def choose_disney_title(
    candidates,
):

    clean = []

    for value in candidates:

        value = normalize_title(
            value
        )

        if not value:
            continue

        if disney_is_bad_title(
            value
        ):

            continue

        if value in clean:
            continue

        clean.append(
            value
        )

    for value in clean:

        if has_korean(
            value
        ):

            return value

    if clean:

        return clean[0]

    return ""


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

                    self.meta_title = (
                        normalize_title(
                            content
                        )
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

    elif href.startswith(
        "https://"
    ):

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

    parser = (
        DisneyDetailParser()
    )

    try:

        parser.feed(
            text
        )

    except Exception as e:

        print(
            f"  상세 HTML 파싱 오류: {e}"
        )

    h1 = parser.get_h1()

    if (
        h1
        and
        not disney_is_bad_title(
            h1
        )
    ):

        return h1

    if (
        parser.meta_title
        and
        not disney_is_bad_title(
            parser.meta_title
        )
    ):

        value = (
            parser.meta_title
        )

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
            not disney_is_bad_title(
                value
            )
        ):

            return value

    page_title = (
        parser.get_title()
    )

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
# Disney entity 링크 추출
# ============================================================

def extract_disney_entities(
    section,
):

    parser = (
        DisneyEntityParser()
    )

    try:

        parser.feed(
            section
        )

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

        entity_id = (
            disney_entity_id(
                href
            )
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
                "id":
                    entity_id,

                "href":
                    href,
            }
        )

    return result


# ============================================================
# Disney
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
            f"Disney+ 페이지 오류: "
            f"{e}"
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
        f"Disney+: TOP 10 발견 → "
        f"{marker}"
    )

    section = text[
        position:
        position + 120000
    ]

    entities = (
        extract_disney_entities(
            section
        )
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

        title = (
            get_disney_detail_title(
                href
            )
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

        print(
            f"  → 원본 제목: {title}"
        )

        # ----------------------------------------------------
        # TMDB TV + 영화 동시 검색
        # ----------------------------------------------------

        resolved = tmdb_resolve(
            title,
            None,
        )

        korean_title = (
            resolved.get(
                "title",
                title,
            )
        )

        if not korean_title:

            korean_title = title

        print(
            f"  → 최종 제목: "
            f"{korean_title}"
        )

        if disney_is_bad_title(
            korean_title
        ):

            print(
                f"  → 최종 제목 이상으로 제외: "
                f"{korean_title}"
            )

            continue

        rank = (
            len(output) + 1
        )

        output.append(
            {
                "rank":
                    rank,

                "title":
                    korean_title,

                "original_title":
                    title,

                "platform":
                    "Disney+",

                "category":
                    "top10",

                "url":
                    href,

                "tmdb_id":
                    resolved.get(
                        "tmdb_id"
                    ),

                "media_type":
                    resolved.get(
                        "media_type"
                    ),

                "tmdb_title":
                    resolved.get(
                        "tmdb_title",
                        "",
                    ),

                "tmdb_original_title":
                    resolved.get(
                        "tmdb_original_title",
                        "",
                    ),
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
            f"쿠팡플레이 페이지 오류: "
            f"{e}"
        )

        return []

    titles = []

    patterns = [
        r'"title"\s*:\s*"([^"]+)"',
        r'"name"\s*:\s*"([^"]+)"',
        r'"contentTitle"\s*:\s*"([^"]+)"',
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

        print(
            f"TMDB 쿠팡 검색: {title}"
        )

        resolved = tmdb_resolve(
            title,
            None,
        )

        final_title = (
            resolved.get(
                "title",
                title,
            )
        )

        output.append(
            {
                "rank":
                    index,

                "title":
                    final_title,

                "original_title":
                    title,

                "platform":
                    "Coupang Play",

                "category":
                    "top10",

                "tmdb_id":
                    resolved.get(
                        "tmdb_id"
                    ),

                "media_type":
                    resolved.get(
                        "media_type"
                    ),

                "tmdb_title":
                    resolved.get(
                        "tmdb_title",
                        "",
                    ),

                "tmdb_original_title":
                    resolved.get(
                        "tmdb_original_title",
                        "",
                    ),
            }
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
# 작품 동일성 판별
# ============================================================

def same_content(
    current_item,
    old_item,
):

    current_id = (
        current_item.get(
            "tmdb_id"
        )
    )

    old_id = (
        old_item.get(
            "tmdb_id"
        )
    )

    current_type = (
        current_item.get(
            "media_type"
        )
    )

    old_type = (
        old_item.get(
            "media_type"
        )
    )

    # --------------------------------------------------------
    # 1. TMDB ID 우선
    # --------------------------------------------------------

    if (
        current_id
        and
        old_id
    ):

        if (
            str(current_id)
            ==
            str(old_id)
        ):

            if (
                current_type
                and
                old_type
            ):

                return (
                    current_type
                    ==
                    old_type
                )

            return True

    # --------------------------------------------------------
    # 2. 제목 비교
    # --------------------------------------------------------

    current_titles = []

    for key in (
        "title",
        "original_title",
        "tmdb_title",
        "tmdb_original_title",
    ):

        value = normalize_compare(
            current_item.get(
                key,
                "",
            )
        )

        if value:

            current_titles.append(
                value
            )

    old_titles = []

    for key in (
        "title",
        "original_title",
        "tmdb_title",
        "tmdb_original_title",
    ):

        value = normalize_compare(
            old_item.get(
                key,
                "",
            )
        )

        if value:

            old_titles.append(
                value
            )

    for current_value in current_titles:

        for old_value in old_titles:

            if (
                current_value
                ==
                old_value
            ):

                return True

    return False


# ============================================================
# 이전 순위
# ============================================================

def find_previous_rank(
    previous_items,
    current_item,
):

    for old in previous_items:

        if same_content(
            current_item,
            old,
        ):

            return (
                old.get("rank"),
                None,
            )

    return (
        None,
        None,
    )


# ============================================================
# History에서 가장 최근 순위
# ============================================================

def find_history_rank(
    history,
    current_item,
    current_date,
):

    snapshots = sorted(
        history,
        key=lambda x: x.get(
            "date",
            "",
        ),
        reverse=True,
    )

    for snapshot in snapshots:

        snapshot_date = (
            snapshot.get(
                "date",
                "",
            )
        )

        if (
            snapshot_date
            ==
            current_date
        ):

            continue

        items = snapshot.get(
            "items",
            [],
        )

        for old in items:

            old_platform = (
                old.get(
                    "platform",
                    "",
                )
            )

            current_platform = (
                current_item.get(
                    "platform",
                    "",
                )
            )

            if (
                old_platform
                !=
                current_platform
            ):

                continue

            if same_content(
                current_item,
                old,
            ):

                return (
                    old.get("rank"),
                    snapshot_date,
                )

    return (
        None,
        None,
    )


# ============================================================
# 변화 계산
# ============================================================

def calculate_changes(
    current,
    previous,
    history,
    current_date,
):

    previous_by_platform = {}

    for item in previous:

        platform = item.get(
            "platform",
            "",
        )

        previous_by_platform.setdefault(
            platform,
            [],
        ).append(
            item
        )

    for item in current:

        platform = item.get(
            "platform",
            "",
        )

        old_items = (
            previous_by_platform.get(
                platform,
                [],
            )
        )

        # ----------------------------------------------------
        # 1. 직전 ranking.json
        # ----------------------------------------------------

        old_rank, old_date = (
            find_previous_rank(
                old_items,
                item,
            )
        )

        # ----------------------------------------------------
        # 2. 없으면 history
        # ----------------------------------------------------

        if old_rank is None:

            (
                old_rank,
                old_date,
            ) = find_history_rank(
                history,
                item,
                current_date,
            )

        current_rank = item.get(
            "rank"
        )

        item[
            "previous_rank"
        ] = old_rank

        item[
            "previous_date"
        ] = old_date

        # ----------------------------------------------------
        # 과거 기록 없음
        # ----------------------------------------------------

        if old_rank is None:

            item[
                "change"
            ] = ""

            continue

        # ----------------------------------------------------
        # 상승
        # ----------------------------------------------------

        if current_rank < old_rank:

            item[
                "change"
            ] = (
                f"+"
                f"{old_rank - current_rank}"
            )

        # ----------------------------------------------------
        # 하락
        # ----------------------------------------------------

        elif current_rank > old_rank:

            item[
                "change"
            ] = (
                f"-"
                f"{current_rank - old_rank}"
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
        +
        timedelta(
            hours=9
        )
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
        -
        timedelta(
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

    print(
        f"실행일: "
        f"{today_string()}"
    )

    check_tmdb_key()

    current_date = (
        today_string()
    )

    # --------------------------------------------------------
    # 수집
    # --------------------------------------------------------

    netflix = get_netflix()

    disney = get_disney()

    coupang = get_coupang()

    current = (
        netflix
        +
        disney
        +
        coupang
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

        previous = (
            previous_data
        )

    # --------------------------------------------------------
    # 기존 history.json
    # --------------------------------------------------------

    history = load_json(
        HISTORY_FILE,
        [],
    )

    if isinstance(
        history,
        dict,
    ):

        history = (
            history.get(
                "history",
                [],
            )
        )

    # --------------------------------------------------------
    # 순위 변화
    # --------------------------------------------------------

    current = (
        calculate_changes(
            current,
            previous,
            history,
            current_date,
        )
    )

    # --------------------------------------------------------
    # TMDB 상세정보 생성
    #
    # 반드시 ranking 확정 후 실행
    # --------------------------------------------------------

    try:

        tmdb_details = (
            build_tmdb_details(
                current
            )
        )

        save_tmdb_details(
            tmdb_details
        )

    except Exception as e:

        print(
            f"[TMDB DETAILS] "
            f"처리 실패: {e}"
        )

    # --------------------------------------------------------
    # ranking.json 저장
    # --------------------------------------------------------

    save_json(
        RANKING_FILE,
        current,
    )

    # --------------------------------------------------------
    # history 추가
    # --------------------------------------------------------

    history.append(
        {
            "date":
                current_date,

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
            ==
            platform
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

            previous_rank = (
                item.get(
                    "previous_rank"
                )
            )

            previous_date = (
                item.get(
                    "previous_date"
                )
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
                    f"({change})"
                )

            else:

                print(
                    f"{item.get('rank'):02d}. "
                    f"{title} "
                    f"({change})"
                )

            print(
                f"    TMDB ID: "
                f"{tmdb_id}"
            )

            if (
                previous_rank
                is not None
            ):

                print(
                    f"    이전 순위: "
                    f"{previous_rank}"
                    f" / "
                    f"{previous_date or '직전 데이터'}"
                )

    print("")
    print("=" * 30)
    print("저장 완료")
    print("=" * 30)

    print("")
    print(
        "생성 파일:"
    )

    print(
        f"  - {RANKING_FILE}"
    )

    print(
        f"  - {HISTORY_FILE}"
    )

    print(
        f"  - {TMDB_DETAILS_FILE}"
    )


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
