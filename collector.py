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
# TMDB 검색
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
            or candidate_normalized in target
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
                    & candidate_words
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

    # 한국 + 한국어
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

    # 한국어만
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
# Netflix 제목 보정
# ============================================================

def tmdb_title(
    original_title,
    media_type,
):

    if not TMDB_API_KEY:

        return original_title

    if media_type == "movie":

        endpoint = "/search/movie"

    else:

        endpoint = "/search/tv"

    print(
        f"TMDB {media_type} 검색: "
        f"{original_title}"
    )

    result = tmdb_search(
        endpoint,
        original_title,
    )

    if not result:

        print(
            f"  → TMDB 검색 실패"
        )

        return original_title

    tmdb_id = result.get(
        "id"
    )

    if media_type == "movie":

        localized = normalize_title(
            result.get(
                "title"
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

    if (
        localized
        and has_korean(localized)
    ):

        translated = (
            tmdb_translation_title(
                media_type,
                tmdb_id,
                localized,
            )
        )

        if has_korean(
            translated
        ):

            print(
                f"  → {translated}"
            )

            return translated

        print(
            f"  → {localized}"
        )

        return localized

    translated = (
        tmdb_translation_title(
            media_type,
            tmdb_id,
            original_title,
        )
    )

    if (
        translated
        != original_title
        and
        has_korean(translated)
    ):

        print(
            f"  → {translated}"
        )

        return translated

    print(
        "  → 한국어 TMDB 제목 없음"
    )

    return original_title


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

        # Netflix 콘텐츠 링크
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
                    "href": self.current_href,
                }
            )

        self.current_href = None
        self.current_text = []


# ============================================================
# Netflix 한국 페이지 제목 찾기
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

    # --------------------------------------------------------
    # Netflix 한국 페이지에서 한글 제목 확보
    # --------------------------------------------------------

    korean_titles = (
        get_netflix_korean_titles()
    )

    # --------------------------------------------------------
    # TSV
    # --------------------------------------------------------

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

            korean_title = ""

            # ------------------------------------------------
            # 1차: TMDB
            # ------------------------------------------------

            korean_title = tmdb_title(
                original_title,
                media_type,
            )

            # ------------------------------------------------
            # 2차:
            # TMDB에서 한국어를 못 찾았으면
            # Netflix 한국 페이지와 비교
            # ------------------------------------------------

            if not has_korean(
                korean_title
            ):

                original_key = (
                    normalize_compare(
                        original_title
                    )
                )

                # 제목 전체 비교
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

                    # 한국 제목과 영문 제목을
                    # 일부 비교
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

            # ------------------------------------------------
            # 3차: 그래도 없으면 원제
            # ------------------------------------------------

            if not korean_title:

                korean_title = (
                    original_title
                )

            output.append(
                {
                    "rank": rank,
                    "title": korean_title,
                    "original_title": (
                        original_title
                    ),
                    "season_title": (
                        season_title
                    ),
                    "platform": "Netflix",
                    "category": (
                        media_type
                    ),
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

class DisneyTopParser(
    HTMLParser
):

    def __init__(self):

        super().__init__(
            convert_charrefs=True
        )

        self.items = []

        self.active = None
        self.depth = 0

    def handle_starttag(
        self,
        tag,
        attrs,
    ):

        if (
            tag.lower()
            != "a"
        ):

            if self.active:
                self.depth += 1

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

        match = re.search(
            r"/browse/entity-"
            r"([a-zA-Z0-9-]+)",
            href,
        )

        if not match:
            return

        self.active = {
            "href": href,
            "texts": [],
        }

        self.depth = 0

    def handle_data(
        self,
        data,
    ):

        if self.active:

            self.active[
                "texts"
            ].append(data)

    def handle_endtag(
        self,
        tag,
    ):

        if not self.active:
            return

        if tag.lower() == "a":

            texts = [
                normalize_title(x)
                for x
                in self.active[
                    "texts"
                ]
            ]

            texts = [
                x
                for x in texts
                if x
            ]

            self.items.append(
                {
                    "href": self.active[
                        "href"
                    ],
                    "texts": texts,
                }
            )

            self.active = None
            self.depth = 0


# ============================================================
# Disney+ 제목 판별
# ============================================================

def disney_is_metadata(
    text,
):

    text = normalize_title(
        text
    )

    if not text:
        return True

    # 예:
    # 2025•스릴러, 범죄
    # 2024•어드벤처, 액션
    if re.match(
        r"^\d{4}\s*[•·|]",
        text,
    ):

        return True

    # 장르만 있는 경우
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

    # 너무 짧고 장르 단어만 있는 경우
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
            == len(parts)
        ):

            return True

    return False


def choose_disney_title(
    texts,
):

    clean = []

    for text in texts:

        text = normalize_title(
            text
        )

        if not text:
            continue

        if disney_is_metadata(
            text
        ):

            continue

        if text in clean:
            continue

        clean.append(text)

    # 제목처럼 보이는 첫 번째 문자열
    if clean:

        return clean[0]

    return ""


# ============================================================
# Disney+ 상세 페이지 제목
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
            f"Disney 상세 페이지 오류: "
            f"{e}"
        )

        return ""

    # --------------------------------------------------------
    # JSON-LD
    # --------------------------------------------------------

    jsonld_patterns = [
        r'"name"\s*:\s*"([^"]+)"',
        r'"headline"\s*:\s*"([^"]+)"',
    ]

    for pattern in (
        jsonld_patterns
    ):

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

            if disney_is_metadata(
                value
            ):

                continue

            # 명백한 UI 문구 제거
            bad = [
                "Disney+",
                "Disney Plus",
                "Standard Monthly",
                "Premium Monthly",
                "Link -",
                "toggle",
            ]

            if any(
                b.lower()
                in value.lower()
                for b in bad
            ):

                continue

            return value

    # --------------------------------------------------------
    # OG title
    # --------------------------------------------------------

    og_patterns = [
        r'<meta[^>]+property=["\']og:title'
        r'["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+content=["\']([^"\']+)'
        r'["\'][^>]+property=["\']og:title',
    ]

    for pattern in (
        og_patterns
    ):

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
                not disney_is_metadata(
                    value
                )
            ):

                return value

    # --------------------------------------------------------
    # title 태그
    # --------------------------------------------------------

    title_match = re.search(
        r"<title[^>]*>"
        r"(.*?)"
        r"</title>",
        text,
        flags=re.I | re.S,
    )

    if title_match:

        value = normalize_title(
            title_match.group(1)
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
            not disney_is_metadata(
                value
            )
        ):

            return value

    return ""


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
            f"Disney+ 페이지 오류: "
            f"{e}"
        )

        return []

    # --------------------------------------------------------
    # TOP 10 위치
    # --------------------------------------------------------

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

    # TOP 10 뒤 일정 범위
    section = text[
        position:
        position + 180000
    ]

    parser = DisneyTopParser()

    try:

        parser.feed(
            section
        )

    except Exception as e:

        print(
            f"Disney HTML 파싱 오류: "
            f"{e}"
        )

        return []

    # --------------------------------------------------------
    # entity 링크 중복 제거
    # --------------------------------------------------------

    entities = []

    seen = set()

    for item in parser.items:

        href = item.get(
            "href",
            "",
        )

        entity_match = re.search(
            r"/browse/entity-"
            r"([a-zA-Z0-9-]+)",
            href,
        )

        if not entity_match:
            continue

        entity_id = (
            entity_match.group(1)
        )

        if entity_id in seen:
            continue

        seen.add(
            entity_id
        )

        entities.append(
            {
                "id": entity_id,
                "href": href,
                "texts": item.get(
                    "texts",
                    [],
                ),
            }
        )

        if len(entities) >= 10:
            break

    print(
        f"Disney+: entity "
        f"{len(entities)}개 발견"
    )

    output = []

    for index, entity in enumerate(
        entities,
        start=1,
    ):

        # ----------------------------------------------------
        # 1차: 링크 내부에서 실제 제목 찾기
        # ----------------------------------------------------

        title = choose_disney_title(
            entity.get(
                "texts",
                [],
            )
        )

        # ----------------------------------------------------
        # 2차: 상세 페이지
        # ----------------------------------------------------

        detail_title = (
            get_disney_detail_title(
                entity.get(
                    "href",
                    "",
                )
            )
        )

        if detail_title:

            # 상세 페이지 제목이
            # 정상 콘텐츠 제목이면 사용
            if (
                not disney_is_metadata(
                    detail_title
                )
            ):

                title = detail_title

        # ----------------------------------------------------
        # 제목을 못 찾은 경우
        # ----------------------------------------------------

        if not title:

            print(
                f"Disney+ {index:02d}: "
                f"제목 추출 실패"
            )

            continue

        # ----------------------------------------------------
        # 이미 한국어라면 그대로 사용
        # ----------------------------------------------------

        if has_korean(title):

            korean_title = title

            print(
                f"Disney+ {index:02d}: "
                f"{korean_title}"
            )

        else:

            # 영어 제목인 경우만 TMDB
            korean_title = (
                tmdb_title(
                    title,
                    "tv",
                )
            )

            if (
                korean_title
                == title
            ):

                korean_title = (
                    tmdb_title(
                        title,
                        "movie",
                    )
                )

            print(
                f"Disney+ {index:02d}: "
                f"{korean_title}"
            )

        output.append(
            {
                "rank": index,
                "title": korean_title,
                "original_title": title,
                "platform": "Disney+",
                "category": "top10",
                "url": entity.get(
                    "href",
                    "",
                ),
            }
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

        output.append(
            {
                "rank": index,
                "title": title,
                "original_title": title,
                "platform": "Coupang Play",
                "category": "top10",
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
# 이전 순위
# ============================================================

def find_previous_rank(
    previous_items,
    current_item,
):

    current_title = (
        normalize_compare(
            current_item.get(
                "title",
                "",
            )
        )
    )

    original_title = (
        normalize_compare(
            current_item.get(
                "original_title",
                "",
            )
        )
    )

    for old in previous_items:

        old_title = (
            normalize_compare(
                old.get(
                    "title",
                    "",
                )
            )
        )

        old_original = (
            normalize_compare(
                old.get(
                    "original_title",
                    "",
                )
            )
        )

        if (
            current_title
            and
            current_title
            == old_title
        ):

            return old.get(
                "rank"
            )

        if (
            original_title
            and
            original_title
            == old_original
        ):

            return old.get(
                "rank"
            )

    return None


# ============================================================
# 변화
# ============================================================

def calculate_changes(
    current,
    previous,
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
        ).append(item)

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

        old_rank = (
            find_previous_rank(
                old_items,
                item,
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
            ] = "NEW"

        else:

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
    # 기존 ranking.json 읽기
    # --------------------------------------------------------

    previous_data = load_json(
        RANKING_FILE,
        [],
    )

    # 과거에 잘못 저장된
    # {"items": [...]} 형식도 읽을 수 있게 처리
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
    # 순위 변화
    # --------------------------------------------------------

    current = (
        calculate_changes(
            current,
            previous,
        )
    )

    # --------------------------------------------------------
    # 중요
    #
    # ranking.json은 Blogger가
    # 기존에 읽던 배열 형식으로 저장
    # --------------------------------------------------------

    save_json(
        RANKING_FILE,
        current,
    )

    # --------------------------------------------------------
    # history
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
                "NEW",
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
