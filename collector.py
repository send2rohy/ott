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

TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"
TMDB_BACKDROP_BASE = "https://image.tmdb.org/t/p/w1280"

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
# TMDB 요청
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
        "search:"
        + endpoint
        + ":"
        + original_title
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
# TMDB 번역 제목
# ============================================================

def tmdb_translation_title(
    media_type,
    tmdb_id,
    fallback_title,
):

    if not tmdb_id:

        return fallback_title

    cache_key = (
        "translation:"
        + media_type
        + ":"
        + str(tmdb_id)
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
            item.get("iso_639_1")
            == "ko"
            and
            item.get("iso_3166_1")
            == "KR"
        ):

            preferred = item
            break

    if not preferred:

        for item in translations:

            if (
                item.get(
                    "iso_639_1"
                )
                == "ko"
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
# TMDB 상세정보 정리
# ============================================================

def build_tmdb_detail(
    media_type,
    result,
):

    if not result:
        return None

    tmdb_id = result.get(
        "id"
    )

    if not tmdb_id:
        return None

    if media_type == "movie":

        title = normalize_title(
            result.get(
                "title"
            )
            or ""
        )

        original_title = normalize_title(
            result.get(
                "original_title"
            )
            or ""
        )

        release_date = (
            result.get(
                "release_date"
            )
            or ""
        )

    else:

        title = normalize_title(
            result.get(
                "name"
            )
            or ""
        )

        original_title = normalize_title(
            result.get(
                "original_name"
            )
            or ""
        )

        release_date = (
            result.get(
                "first_air_date"
            )
            or ""
        )

    # --------------------------------------------------------
    # 한국 제목 보정
    # --------------------------------------------------------

    korean_title = title

    if not has_korean(
        korean_title
    ):

        translated = (
            tmdb_translation_title(
                media_type,
                tmdb_id,
                title or original_title,
            )
        )

        if translated:

            korean_title = translated

    # --------------------------------------------------------
    # 장르
    # --------------------------------------------------------

    genres = []

    for genre in (
        result.get(
            "genres",
            []
        )
        or []
    ):

        name = normalize_title(
            genre.get(
                "name",
                ""
            )
        )

        if name:

            genres.append(
                name
            )

    # --------------------------------------------------------
    # 러닝타임
    # --------------------------------------------------------

    runtime = result.get(
        "runtime"
    )

    if not runtime:

        runtimes = (
            result.get(
                "episode_run_time",
                []
            )
            or []
        )

        if runtimes:

            try:

                runtime = int(
                    runtimes[0]
                )

            except Exception:

                runtime = None

    # --------------------------------------------------------
    # 포스터
    # --------------------------------------------------------

    poster_path = (
        result.get(
            "poster_path"
        )
        or ""
    )

    backdrop_path = (
        result.get(
            "backdrop_path"
        )
        or ""
    )

    poster_url = (
        TMDB_IMAGE_BASE
        + poster_path
        if poster_path
        else ""
    )

    backdrop_url = (
        TMDB_BACKDROP_BASE
        + backdrop_path
        if backdrop_path
        else ""
    )

    # --------------------------------------------------------
    # 평점
    # --------------------------------------------------------

    vote_average = result.get(
        "vote_average"
    )

    vote_count = result.get(
        "vote_count"
    )

    try:

        vote_average = round(
            float(vote_average),
            1,
        )

    except Exception:

        vote_average = None

    try:

        vote_count = int(
            vote_count
        )

    except Exception:

        vote_count = 0

    # --------------------------------------------------------
    # 줄거리
    # --------------------------------------------------------

    overview = normalize_title(
        result.get(
            "overview",
            ""
        )
    )

    # --------------------------------------------------------
    # 기본 정보
    # --------------------------------------------------------

    return {
        "tmdb_id": int(
            tmdb_id
        ),
        "media_type": media_type,
        "tmdb_title": korean_title,
        "tmdb_original_title": (
            original_title
        ),
        "poster_url": poster_url,
        "backdrop_url": backdrop_url,
        "release_date": release_date,
        "genres": genres,
        "runtime": runtime,
        "overview": overview,
        "vote_average": vote_average,
        "vote_count": vote_count,
    }


# ============================================================
# TMDB 크레딧 / 예고편
# ============================================================

def tmdb_detail_request(
    media_type,
    tmdb_id,
):

    cache_key = (
        "detail:"
        + media_type
        + ":"
        + str(tmdb_id)
    )

    if cache_key in TMDB_CACHE:

        return TMDB_CACHE[
            cache_key
        ]

    data = tmdb_request(
        f"/{media_type}/{tmdb_id}",
        {
            "language": TMDB_LANGUAGE,
            "append_to_response": (
                "credits,videos"
            ),
        },
    )

    TMDB_CACHE[
        cache_key
    ] = data

    return data


def enrich_tmdb_detail(
    detail,
):

    if not detail:
        return None

    media_type = detail.get(
        "media_type"
    )

    tmdb_id = detail.get(
        "tmdb_id"
    )

    if (
        not media_type
        or
        not tmdb_id
    ):

        return detail

    data = tmdb_detail_request(
        media_type,
        tmdb_id,
    )

    if not data:

        return detail

    # --------------------------------------------------------
    # 기본 상세정보
    # --------------------------------------------------------

    basic = build_tmdb_detail(
        media_type,
        data,
    )

    if basic:

        detail.update(
            basic
        )

    # --------------------------------------------------------
    # 출연진
    # --------------------------------------------------------

    credits = data.get(
        "credits",
        {}
    )

    cast = []

    for person in (
        credits.get(
            "cast",
            []
        )
        or []
    ):

        name = normalize_title(
            person.get(
                "name",
                ""
            )
        )

        if name:

            cast.append(
                name
            )

        if len(cast) >= 10:
            break

    detail[
        "cast"
    ] = cast

    # --------------------------------------------------------
    # 감독
    # --------------------------------------------------------

    directors = []

    for person in (
        credits.get(
            "crew",
            []
        )
        or []
    ):

        job = normalize_title(
            person.get(
                "job",
                ""
            )
        )

        if job == "Director":

            name = normalize_title(
                person.get(
                    "name",
                    ""
                )
            )

            if (
                name
                and
                name not in directors
            ):

                directors.append(
                    name
                )

        if len(directors) >= 5:
            break

    detail[
        "director"
    ] = directors

    # --------------------------------------------------------
    # 예고편
    # --------------------------------------------------------

    trailer = ""

    videos = data.get(
        "videos",
        {}
    )

    for video in (
        videos.get(
            "results",
            []
        )
        or []
    ):

        site = (
            video.get(
                "site",
                ""
            )
            or ""
        ).lower()

        key = video.get(
            "key",
            ""
        )

        video_type = (
            video.get(
                "type",
                ""
            )
            or ""
        ).lower()

        official = video.get(
            "official",
            False
        )

        if (
            site == "youtube"
            and
            key
            and
            video_type
            == "trailer"
            and
            official
        ):

            trailer = (
                "https://www.youtube.com/watch?v="
                + key
            )

            break

    if not trailer:

        for video in (
            videos.get(
                "results",
                []
            )
            or []
        ):

            site = (
                video.get(
                    "site",
                    ""
                )
                or ""
            ).lower()

            key = video.get(
                "key",
                ""
            )

            video_type = (
                video.get(
                    "type",
                    ""
                )
                or ""
            ).lower()

            if (
                site == "youtube"
                and
                key
                and
                video_type
                == "trailer"
            ):

                trailer = (
                    "https://www.youtube.com/watch?v="
                    + key
                )

                break

    detail[
        "trailer"
    ] = trailer

    return detail


# ============================================================
# TMDB 작품 찾기
#
# 결과:
# {
#   tmdb_id,
#   media_type,
#   korean_title,
#   original_title
# }
# ============================================================

def tmdb_find_work(
    original_title,
    preferred_media_type=None,
):

    original_title = normalize_title(
        original_title
    )

    if not original_title:
        return None

    if not TMDB_API_KEY:
        return None

    cache_key = (
        "work:"
        + str(preferred_media_type)
        + ":"
        + original_title
    )

    if cache_key in TMDB_CACHE:

        return TMDB_CACHE[
            cache_key
        ]

    candidates = []

    if preferred_media_type == "movie":

        candidates = [
            ("movie", "/search/movie"),
        ]

    elif preferred_media_type == "tv":

        candidates = [
            ("tv", "/search/tv"),
        ]

    else:

        candidates = [
            ("movie", "/search/movie"),
            ("tv", "/search/tv"),
        ]

    best = None
    best_score = -999

    for media_type, endpoint in candidates:

        result = tmdb_search(
            endpoint,
            original_title,
        )

        if not result:
            continue

        score = tmdb_match_score(
            original_title,
            result,
        )

        if score > best_score:

            best_score = score

            best = {
                "media_type": media_type,
                "result": result,
            }

    if (
        not best
        or
        best_score < 35
    ):

        TMDB_CACHE[
            cache_key
        ] = None

        return None

    media_type = best[
        "media_type"
    ]

    result = best[
        "result"
    ]

    tmdb_id = result.get(
        "id"
    )

    if not tmdb_id:

        TMDB_CACHE[
            cache_key
        ] = None

        return None

    if media_type == "movie":

        fallback_title = normalize_title(
            result.get(
                "title"
            )
            or
            result.get(
                "original_title"
            )
            or
            original_title
        )

        result_original_title = (
            normalize_title(
                result.get(
                    "original_title"
                )
                or
                original_title
            )
        )

    else:

        fallback_title = normalize_title(
            result.get(
                "name"
            )
            or
            result.get(
                "original_name"
            )
            or
            original_title
        )

        result_original_title = (
            normalize_title(
                result.get(
                    "original_name"
                )
                or
                original_title
            )
        )

    korean_title = fallback_title

    if not has_korean(
        korean_title
    ):

        korean_title = (
            tmdb_translation_title(
                media_type,
                tmdb_id,
                fallback_title,
            )
        )

    work = {
        "tmdb_id": int(
            tmdb_id
        ),
        "media_type": media_type,
        "korean_title": (
            korean_title
        ),
        "original_title": (
            result_original_title
        ),
    }

    TMDB_CACHE[
        cache_key
    ] = work

    return work


# ============================================================
# 작품 TMDB 상세정보 생성
#
# collector에서는 상세정보까지 저장한다.
# Blogger는 클릭 시 별도 API 호출을 하지 않아도 된다.
# ============================================================

def get_tmdb_metadata(
    original_title,
    preferred_media_type=None,
):

    work = tmdb_find_work(
        original_title,
        preferred_media_type,
    )

    if not work:

        return {}

    tmdb_id = work.get(
        "tmdb_id"
    )

    media_type = work.get(
        "media_type"
    )

    data = tmdb_detail_request(
        media_type,
        tmdb_id,
    )

    if not data:

        return {
            "tmdb_id": tmdb_id,
            "media_type": media_type,
        }

    detail = build_tmdb_detail(
        media_type,
        data,
    )

    if not detail:

        detail = {
            "tmdb_id": tmdb_id,
            "media_type": media_type,
        }

    # --------------------------------------------------------
    # 크레딧 / 영상
    # --------------------------------------------------------

    detail = enrich_tmdb_detail(
        detail
    )

    return detail


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

        if self.current_href is not None:

            self.current_text.append(
                data
            )

    def handle_endtag(
        self,
        tag,
    ):

        if tag.lower() != "a":
            return

        if self.current_href is None:
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
                f"Netflix 한국 페이지 오류: {e}"
            )

            continue

        parser = NetflixLinkParser()

        try:

            parser.feed(text)

        except Exception as e:

            print(
                f"Netflix HTML 파싱 오류: {e}"
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

            if not has_korean(title):
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

        if country.upper() != COUNTRY_CODE:
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
        f"Netflix 최신 주차: {latest_week}"
    )

    latest_rows = [
        row
        for row in rows
        if row.get("week")
        == latest_week
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

            print("")
            print(
                f"Netflix {media_type} "
                f"{rank:02d}: "
                f"{original_title}"
            )

            # ------------------------------------------------
            # TMDB 매칭
            # ------------------------------------------------

            tmdb_meta = get_tmdb_metadata(
                original_title,
                media_type,
            )

            tmdb_id = tmdb_meta.get(
                "tmdb_id"
            )

            matched_media_type = (
                tmdb_meta.get(
                    "media_type"
                )
                or media_type
            )

            korean_title = (
                tmdb_meta.get(
                    "tmdb_title"
                )
                or ""
            )

            # ------------------------------------------------
            # 기존 Netflix 한국 페이지 제목 보정
            # ------------------------------------------------

            if not korean_title:

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

            item = {
                "rank": rank,
                "title": korean_title,
                "original_title": (
                    original_title
                ),
                "season_title": (
                    season_title
                ),
                "platform": "Netflix",
                "category": media_type,
                "week": latest_week,
            }

            # ------------------------------------------------
            # TMDB 정보
            # ------------------------------------------------

            if tmdb_id:

                item.update(
                    {
                        "tmdb_id": int(
                            tmdb_id
                        ),
                        "media_type": (
                            matched_media_type
                        ),
                    }
                )

                for key in (
                    "poster_url",
                    "backdrop_url",
                    "release_date",
                    "genres",
                    "runtime",
                    "overview",
                    "vote_average",
                    "vote_count",
                    "cast",
                    "director",
                    "trailer",
                ):

                    if key in tmdb_meta:

                        item[key] = (
                            tmdb_meta[key]
                        )

            output.append(
                item
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
# Disney parser
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
            r"/browse/entity-[a-zA-Z0-9-]+",
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
# Disney 메타데이터
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
# Disney 잘못된 제목
# ============================================================

def disney_is_bad_title(
    text,
):

    text = normalize_title(
        text
    )

    if not text:
        return True

    if disney_is_metadata(text):
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
# Disney 상세 파서
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
                    ""
                )
                or
                attributes.get(
                    "name",
                    ""
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
# Disney 상세 제목
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

    h1 = parser.get_h1()

    if (
        h1
        and
        not disney_is_bad_title(h1)
    ):

        return h1

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

        pos = text.find(item)

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

        if disney_is_bad_title(title):

            print(
                f"  → 잘못된 제목 제외: {title}"
            )

            continue

        used_ids.add(
            entity_id
        )

        print(
            f"  → 실제 제목: {title}"
        )

        # ----------------------------------------------------
        # TMDB
        # ----------------------------------------------------

        tmdb_meta = get_tmdb_metadata(
            title,
            None,
        )

        korean_title = (
            tmdb_meta.get(
                "tmdb_title"
            )
            or
            title
        )

        if not has_korean(korean_title):

            korean_title = title

        print(
            f"  → 최종 제목: {korean_title}"
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

        item = {
            "rank": rank,
            "title": korean_title,
            "original_title": title,
            "platform": "Disney+",
            "category": "top10",
            "url": href,
        }

        # ----------------------------------------------------
        # TMDB 정보
        # ----------------------------------------------------

        tmdb_id = tmdb_meta.get(
            "tmdb_id"
        )

        if tmdb_id:

            item.update(
                {
                    "tmdb_id": int(
                        tmdb_id
                    ),
                    "media_type": (
                        tmdb_meta.get(
                            "media_type"
                        )
                    ),
                }
            )

            for key in (
                "poster_url",
                "backdrop_url",
                "release_date",
                "genres",
                "runtime",
                "overview",
                "vote_average",
                "vote_count",
                "cast",
                "director",
                "trailer",
            ):

                if key in tmdb_meta:

                    item[key] = (
                        tmdb_meta[key]
                    )

        output.append(
            item
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

        print("")
        print(
            f"Coupang Play {index:02d}: "
            f"{title}"
        )

        # ----------------------------------------------------
        # TMDB는 movie/tv 모두 검색
        # ----------------------------------------------------

        tmdb_meta = get_tmdb_metadata(
            title,
            None,
        )

        korean_title = (
            tmdb_meta.get(
                "tmdb_title"
            )
            or
            title
        )

        item = {
            "rank": index,
            "title": korean_title,
            "original_title": title,
            "platform": "Coupang Play",
            "category": "top10",
        }

        tmdb_id = tmdb_meta.get(
            "tmdb_id"
        )

        if tmdb_id:

            item.update(
                {
                    "tmdb_id": int(
                        tmdb_id
                    ),
                    "media_type": (
                        tmdb_meta.get(
                            "media_type"
                        )
                    ),
                }
            )

            for key in (
                "poster_url",
                "backdrop_url",
                "release_date",
                "genres",
                "runtime",
                "overview",
                "vote_average",
                "vote_count",
                "cast",
                "director",
                "trailer",
            ):

                if key in tmdb_meta:

                    item[key] = (
                        tmdb_meta[key]
                    )

        output.append(
            item
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
            f"{filename} 읽기 오류: {e}"
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
# 작품 식별
#
# 1순위 TMDB ID
# 2순위 제목
# 3순위 원제
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

    current_title = normalize_compare(
        current_item.get(
            "title",
            "",
        )
    )

    old_title = normalize_compare(
        old_item.get(
            "title",
            "",
        )
    )

    if (
        current_title
        and
        current_title == old_title
    ):

        return True

    current_original = normalize_compare(
        current_item.get(
            "original_title",
            "",
        )
    )

    old_original = normalize_compare(
        old_item.get(
            "original_title",
            "",
        )
    )

    if (
        current_original
        and
        current_original == old_original
    ):

        return True

    return False


# ============================================================
# 이전 순위 찾기
#
# 현재 날짜 바로 전 기록만 보지 않는다.
#
# 최근 30일 history를 역순으로 검색해서
# 이 작품이 마지막으로 등장했던 순위를 찾는다.
#
# 따라서:
#
# 월요일 5위
# 화요일 OUT
# 수요일 OUT
# 목요일 8위
#
# → NEW가 아니라 ▼3
# ============================================================

def find_previous_rank_from_history(
    history,
    current_item,
    current_date,
):

    platform = current_item.get(
        "platform",
        "",
    )

    snapshots = sorted(
        history,
        key=lambda x: x.get(
            "date",
            "",
        ),
        reverse=True,
    )

    for snapshot in snapshots:

        snapshot_date = snapshot.get(
            "date",
            "",
        )

        if snapshot_date >= current_date:
            continue

        items = snapshot.get(
            "items",
            []
        )

        if not isinstance(
            items,
            list,
        ):

            continue

        for old_item in items:

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

                        return int(
                            rank
                        )

                    except Exception:

                        return None

    return None


# ============================================================
# 변화 계산
#
# NEW를 사용하지 않는다.
#
# 기록이 없으면:
# change = ""
#
# 기존 기록이 있으면:
# +2 / -2 / 0
# ============================================================

def calculate_changes(
    current,
    history,
    current_date,
):

    for item in current:

        old_rank = (
            find_previous_rank_from_history(
                history,
                item,
                current_date,
            )
        )

        current_rank = item.get(
            "rank"
        )

        if old_rank is None:

            item[
                "previous_rank"
            ] = None

            item[
                "change"
            ] = ""

            continue

        item[
            "previous_rank"
        ] = old_rank

        if current_rank < old_rank:

            item[
                "change"
            ] = (
                f"+{old_rank - current_rank}"
            )

        elif current_rank > old_rank:

            item[
                "change"
            ] = (
                f"-{current_rank - old_rank}"
            )

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
# 중복 날짜 History 제거
# ============================================================

def replace_today_history(
    history,
    current_date,
    current_items,
):

    result = []

    for item in history:

        if item.get(
            "date",
            "",
        ) == current_date:

            continue

        result.append(
            item
        )

    result.append(
        {
            "date": current_date,
            "items": current_items,
        }
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

    current_date = today_string()

    print(
        f"실행일: {current_date}"
    )

    check_tmdb_key()

    # --------------------------------------------------------
    # 기존 History 먼저 읽기
    #
    # 순위 변화 계산에 사용해야 하므로
    # 수집 전에 읽어둔다.
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
    # 순위 변화
    #
    # NEW 없음
    # --------------------------------------------------------

    current = calculate_changes(
        current,
        history,
        current_date,
    )

    # --------------------------------------------------------
    # ranking.json
    # --------------------------------------------------------

    save_json(
        RANKING_FILE,
        current,
    )

    # --------------------------------------------------------
    # history
    # --------------------------------------------------------

    history = replace_today_history(
        history,
        current_date,
        current,
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

            if not change:

                change_text = "변동 없음"

            elif change == "0":

                change_text = "변동 없음"

            elif change.startswith("+"):

                change_text = (
                    "▲"
                    + change[1:]
                )

            elif change.startswith("-"):

                change_text = (
                    "▼"
                    + change[1:]
                )

            else:

                change_text = change

            tmdb_id = item.get(
                "tmdb_id",
                "",
            )

            media_type = item.get(
                "media_type",
                "",
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
                    f"({change_text}) "
                    f"TMDB={tmdb_id} "
                    f"{media_type}"
                )

            else:

                print(
                    f"{item.get('rank'):02d}. "
                    f"{title} "
                    f"({change_text}) "
                    f"TMDB={tmdb_id} "
                    f"{media_type}"
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
