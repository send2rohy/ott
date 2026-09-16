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


# 실행 중 TMDB 캐시
TMDB_CACHE = {}


# ============================================================
# HTTP
# ============================================================

def fetch_text(url, timeout=30):
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
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        },
    )

    with urllib.request.urlopen(req, timeout=timeout) as response:
        data = response.read()

        charset = response.headers.get_content_charset()

        if not charset:
            charset = "utf-8"

        return data.decode(charset, errors="replace")


def fetch_json(url, timeout=30):
    text = fetch_text(url, timeout=timeout)
    return json.loads(text)


# ============================================================
# 문자열 정리
# ============================================================

def normalize_title(text):
    if not text:
        return ""

    text = html.unescape(text)

    text = re.sub(r"<[^>]+>", " ", text)

    text = text.replace("\xa0", " ")

    text = re.sub(r"\s+", " ", text)

    return text.strip()


def normalize_compare(text):
    text = normalize_title(text).lower()

    # 시즌/파트 표기 등을 비교할 때 어느 정도 무시
    text = re.sub(
        r"\b(season|part|limited series|series|movie|tv)\b",
        " ",
        text,
        flags=re.I,
    )

    text = re.sub(r"[^\w가-힣]+", "", text)

    return text


def has_korean(text):
    if not text:
        return False

    return bool(re.search(r"[가-힣]", text))


# ============================================================
# TMDB API
# ============================================================

def check_tmdb_key():
    if TMDB_API_KEY:
        print("TMDB API: 연결 설정됨")
        return True

    print("TMDB API: 키 없음")
    print("TMDB 보정 없이 원래 제목을 사용합니다.")

    return False


def tmdb_request(path, params=None):
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
        + urllib.parse.urlencode(params)
    )

    try:
        return fetch_json(url, timeout=20)

    except Exception as e:
        print(f"TMDB 오류: {e}")
        return None


# ============================================================
# TMDB 검색 점수
# ============================================================

def tmdb_match_score(original_title, result):
    if not result:
        return -999

    original_title = normalize_title(original_title)

    candidates = []

    for key in (
        "title",
        "name",
        "original_title",
        "original_name",
    ):
        value = result.get(key)

        if value:
            candidates.append(normalize_title(value))

    target = normalize_compare(original_title)

    if not target:
        return -999

    best = 0

    for candidate in candidates:

        c = normalize_compare(candidate)

        if not c:
            continue

        if c == target:
            best = max(best, 100)

        elif target in c or c in target:
            best = max(best, 85)

        else:
            # 단어 단위 비교
            target_words = set(
                re.findall(r"[a-z0-9가-힣]+", original_title.lower())
            )

            candidate_words = set(
                re.findall(r"[a-z0-9가-힣]+", candidate.lower())
            )

            if target_words and candidate_words:

                common = target_words & candidate_words

                ratio = len(common) / max(
                    len(target_words),
                    len(candidate_words),
                )

                best = max(best, int(ratio * 80))

    popularity = result.get("popularity", 0)

    try:
        popularity_bonus = min(float(popularity) / 100, 10)
    except Exception:
        popularity_bonus = 0

    return best + popularity_bonus


# ============================================================
# TMDB 검색
# ============================================================

def tmdb_search(endpoint, original_title):

    cache_key = f"search:{endpoint}:{original_title}"

    if cache_key in TMDB_CACHE:
        return TMDB_CACHE[cache_key]

    result = tmdb_request(
        endpoint,
        {
            "query": original_title,
            "language": TMDB_LANGUAGE,
            "region": TMDB_REGION,
            "include_adult": "false",
            "page": 1,
        },
    )

    if not result:
        TMDB_CACHE[cache_key] = None
        return None

    results = result.get("results", [])

    if not results:
        TMDB_CACHE[cache_key] = None
        return None

    best_result = None
    best_score = -999

    for item in results[:20]:

        score = tmdb_match_score(
            original_title,
            item,
        )

        if score > best_score:
            best_score = score
            best_result = item

    # 너무 엉뚱한 검색 결과 방지
    if best_score < 35:
        best_result = None

    TMDB_CACHE[cache_key] = best_result

    return best_result


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

    cache_key = f"translation:{media_type}:{tmdb_id}"

    if cache_key in TMDB_CACHE:
        return TMDB_CACHE[cache_key]

    data = tmdb_request(
        f"/{media_type}/{tmdb_id}/translations"
    )

    if not data:
        TMDB_CACHE[cache_key] = fallback_title
        return fallback_title

    translations = data.get("translations", [])

    # 한국 KR 우선
    preferred = None

    for item in translations:
        iso = item.get("iso_639_1")
        country = item.get("iso_3166_1")

        if iso == "ko" and country == "KR":
            preferred = item
            break

    # 한국어면 국가코드 상관없이 검색
    if not preferred:
        for item in translations:
            if item.get("iso_639_1") == "ko":
                preferred = item
                break

    if preferred:

        data_block = preferred.get("data", {})

        title = (
            data_block.get("title")
            or data_block.get("name")
            or ""
        )

        title = normalize_title(title)

        if title:
            TMDB_CACHE[cache_key] = title
            return title

    TMDB_CACHE[cache_key] = fallback_title

    return fallback_title


# ============================================================
# TMDB 영화 제목
# ============================================================

def tmdb_movie_title(original_title):

    if not TMDB_API_KEY:
        return original_title

    print(f"TMDB 영화 검색: {original_title}")

    result = tmdb_search(
        "/search/movie",
        original_title,
    )

    if not result:
        print(f"  → 검색 실패: {original_title}")
        return original_title

    tmdb_id = result.get("id")

    # 검색 결과의 한국어 제목
    localized = normalize_title(
        result.get("title")
        or ""
    )

    # 원문과 다른 한국어 제목이 있으면 우선
    if localized and has_korean(localized):

        translated = tmdb_translation_title(
            "movie",
            tmdb_id,
            localized,
        )

        if has_korean(translated):
            print(
                f"  → {translated} "
                f"(TMDB: {tmdb_id})"
            )

            return translated

        print(
            f"  → {localized} "
            f"(TMDB: {tmdb_id})"
        )

        return localized

    translated = tmdb_translation_title(
        "movie",
        tmdb_id,
        original_title,
    )

    if translated != original_title:
        print(
            f"  → {translated} "
            f"(TMDB: {tmdb_id})"
        )
        return translated

    print(
        f"  → 한국어 번역 없음 "
        f"(TMDB: {tmdb_id})"
    )

    return original_title


# ============================================================
# TMDB TV 제목
# ============================================================

def tmdb_tv_title(original_title):

    if not TMDB_API_KEY:
        return original_title

    print(f"TMDB TV 검색: {original_title}")

    result = tmdb_search(
        "/search/tv",
        original_title,
    )

    if not result:
        print(f"  → 검색 실패: {original_title}")
        return original_title

    tmdb_id = result.get("id")

    localized = normalize_title(
        result.get("name")
        or ""
    )

    if localized and has_korean(localized):

        translated = tmdb_translation_title(
            "tv",
            tmdb_id,
            localized,
        )

        if has_korean(translated):
            print(
                f"  → {translated} "
                f"(TMDB: {tmdb_id})"
            )

            return translated

        print(
            f"  → {localized} "
            f"(TMDB: {tmdb_id})"
        )

        return localized

    translated = tmdb_translation_title(
        "tv",
        tmdb_id,
        original_title,
    )

    if translated != original_title:
        print(
            f"  → {translated} "
            f"(TMDB: {tmdb_id})"
        )

        return translated

    print(
        f"  → 한국어 번역 없음 "
        f"(TMDB: {tmdb_id})"
    )

    return original_title


# ============================================================
# TMDB 다중 검색
# Disney+ 보정용
# ============================================================

def tmdb_multi_title(original_title):

    if not TMDB_API_KEY:
        return original_title

    original_title = normalize_title(original_title)

    print(f"TMDB 통합 검색: {original_title}")

    result = tmdb_search(
        "/search/multi",
        original_title,
    )

    if not result:
        print(f"  → 검색 실패")
        return original_title

    media_type = result.get("media_type")

    tmdb_id = result.get("id")

    if media_type not in ("movie", "tv"):
        return original_title

    if media_type == "movie":

        localized = normalize_title(
            result.get("title")
            or ""
        )

    else:

        localized = normalize_title(
            result.get("name")
            or ""
        )

    if localized and has_korean(localized):

        translated = tmdb_translation_title(
            media_type,
            tmdb_id,
            localized,
        )

        if has_korean(translated):

            print(
                f"  → {translated} "
                f"(TMDB: {tmdb_id}, {media_type})"
            )

            return translated

        print(
            f"  → {localized} "
            f"(TMDB: {tmdb_id}, {media_type})"
        )

        return localized

    translated = tmdb_translation_title(
        media_type,
        tmdb_id,
        original_title,
    )

    if translated != original_title:

        print(
            f"  → {translated} "
            f"(TMDB: {tmdb_id}, {media_type})"
        )

        return translated

    print(
        f"  → 한국어 번역 없음 "
        f"(TMDB: {tmdb_id})"
    )

    return original_title


# ============================================================
# Netflix
# 공식 TSV에서 한국 TOP 10
# ============================================================

def get_netflix():

    print("")
    print("=" * 60)
    print("NETFLIX")
    print("=" * 60)

    print("Netflix TSV 다운로드 중...")

    try:
        text = fetch_text(
            NETFLIX_TSV_URL,
            timeout=60,
        )

    except Exception as e:
        print(f"Netflix TSV 오류: {e}")
        return []

    reader = csv.DictReader(
        io.StringIO(text),
        delimiter="\t",
    )

    rows = []

    for row in reader:

        country = (
            row.get("country_iso2")
            or row.get("country_code")
            or ""
        )

        if country.upper() != COUNTRY_CODE:
            continue

        rows.append(row)

    if not rows:
        print("Netflix 한국 데이터 없음")
        return []

    # 가장 최근 주차
    weeks = sorted(
        {
            row.get("week")
            for row in rows
            if row.get("week")
        },
        reverse=True,
    )

    if not weeks:
        print("Netflix 주차 데이터 없음")
        return []

    latest_week = weeks[0]

    print(f"Netflix 최신 주차: {latest_week}")

    latest_rows = [
        row
        for row in rows
        if row.get("week") == latest_week
    ]

    # 영화 / TV 각각 처리
    movies = [
        row
        for row in latest_rows
        if (
            row.get("category", "")
            .lower()
            in ("films", "film", "movies", "movie")
        )
    ]

    tv = [
        row
        for row in latest_rows
        if (
            row.get("category", "")
            .lower()
            in ("tv", "tv shows", "tv show", "series")
        )
    ]

    # 혹시 category 명칭이 변경됐을 경우
    if not movies:

        movies = [
            row
            for row in latest_rows
            if "film" in row.get("category", "").lower()
        ]

    if not tv:

        tv = [
            row
            for row in latest_rows
            if (
                "tv" in row.get("category", "").lower()
                or "series" in row.get("category", "").lower()
            )
        ]

    def process_rows(source_rows, media_type):

        source_rows = sorted(
            source_rows,
            key=lambda x: int(
                x.get("weekly_rank") or 999
            ),
        )

        output = []

        for row in source_rows[:10]:

            rank = int(
                row.get("weekly_rank") or 0
            )

            original_title = normalize_title(
                row.get("show_title") or ""
            )

            if not original_title:
                continue

            # 시즌명은 원제 보관용으로 별도 저장
            season_title = normalize_title(
                row.get("season_title") or ""
            )

            # 중요:
            # Netflix TSV 원제는 절대 덮어쓰지 않는다.
            # TMDB 검색용으로 사용한다.
            korean_title = original_title

            if media_type == "movie":

                korean_title = tmdb_movie_title(
                    original_title
                )

            else:

                korean_title = tmdb_tv_title(
                    original_title
                )

            item = {
                "rank": rank,
                "title": korean_title,
                "original_title": original_title,
                "season_title": season_title,
                "platform": "Netflix",
                "category": media_type,
                "week": latest_week,
            }

            output.append(item)

        return output

    movie_items = process_rows(
        movies,
        "movie",
    )

    tv_items = process_rows(
        tv,
        "tv",
    )

    print(
        f"Netflix 영화 {len(movie_items)}개"
    )

    print(
        f"Netflix TV {len(tv_items)}개"
    )

    return movie_items + tv_items


# ============================================================
# Disney+ HTML Parser
# ============================================================

class DisneyLinkParser(HTMLParser):

    def __init__(self):
        super().__init__(
            convert_charrefs=True
        )

        self.links = []

        self.current_href = None
        self.current_text = []

    def handle_starttag(self, tag, attrs):

        if tag.lower() != "a":
            return

        attr = dict(attrs)

        href = attr.get("href", "")

        if not href:
            return

        # 실제 Disney 콘텐츠 링크
        if re.search(
            r"/browse/entity-[a-zA-Z0-9-]+",
            href,
        ):

            self.current_href = href
            self.current_text = []

    def handle_data(self, data):

        if self.current_href is not None:
            self.current_text.append(data)

    def handle_endtag(self, tag):

        if tag.lower() != "a":
            return

        if self.current_href is None:
            return

        title = normalize_title(
            "".join(self.current_text)
        )

        href = self.current_href

        if title:

            self.links.append(
                {
                    "title": title,
                    "href": href,
                }
            )

        self.current_href = None
        self.current_text = []


# ============================================================
# Disney+ TOP 10 영역 추출
# ============================================================

def extract_disney_top10_links(text):

    # HTML entity 복원
    text = html.unescape(text)

    # --------------------------------------------------------
    # 한국어 페이지
    # --------------------------------------------------------

    markers = [
        "오늘 한국의 TOP 10",
        "오늘 한국의 TOP10",
        "한국의 TOP 10",
        "한국의 TOP10",
        "Top 10 in South Korea Today",
    ]

    marker_position = -1
    marker_used = None

    for marker in markers:

        pos = text.find(marker)

        if pos >= 0:

            marker_position = pos
            marker_used = marker
            break

    if marker_position < 0:

        print(
            "Disney+: TOP 10 섹션 위치를 찾지 못했습니다."
        )

        return []

    print(
        f"Disney+: TOP 10 영역 발견 → {marker_used}"
    )

    # --------------------------------------------------------
    # TOP 10 이후 영역만 잘라낸다.
    #
    # 다음 주요 섹션인 Disney+ / TVING / Wavve Bundle,
    # Collections, FAQ 등을 너무 많이 포함하지 않도록
    # 적당한 범위만 검사한다.
    # --------------------------------------------------------

    section = text[
        marker_position:
        marker_position + 250000
    ]

    parser = DisneyLinkParser()

    try:
        parser.feed(section)

    except Exception as e:

        print(
            f"Disney HTML 파싱 오류: {e}"
        )

        return []

    links = parser.links

    # --------------------------------------------------------
    # 중복 제거
    # --------------------------------------------------------

    unique = []

    seen_href = set()
    seen_title = set()

    for item in links:

        title = normalize_title(
            item.get("title", "")
        )

        href = item.get("href", "")

        if not title or not href:
            continue

        title_key = normalize_compare(title)

        href_key = href.split("?")[0]

        if href_key in seen_href:
            continue

        if title_key in seen_title:
            continue

        seen_href.add(href_key)
        seen_title.add(title_key)

        unique.append(
            {
                "title": title,
                "href": href,
            }
        )

    return unique[:10]


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

    # --------------------------------------------------------
    # 실제 TOP 10 링크 추출
    # --------------------------------------------------------

    links = extract_disney_top10_links(
        text
    )

    if not links:

        print(
            "Disney+: TOP 10 콘텐츠를 찾지 못했습니다."
        )

        return []

    print(
        f"Disney+: 실제 TOP 10 링크 {len(links)}개 발견"
    )

    output = []

    for index, item in enumerate(
        links[:10],
        start=1,
    ):

        original_title = normalize_title(
            item["title"]
        )

        # ----------------------------------------------------
        # 중요
        #
        # Disney+ 페이지 자체가 한국어 제목을 제공한다.
        # 따라서 여기서는 우선 그 제목을 그대로 사용한다.
        #
        # TMDB는 보정용.
        # ----------------------------------------------------

        korean_title = original_title

        if TMDB_API_KEY:

            # 이미 한글이면 불필요하게 영어로
            # 되돌리지 않도록 한다.
            if not has_korean(original_title):

                korean_title = tmdb_multi_title(
                    original_title
                )

            else:

                print(
                    f"Disney+ {index:02d}: "
                    f"{original_title} "
                    f"(Disney+ 원문 한글 제목)"
                )

        output.append(
            {
                "rank": index,
                "title": korean_title,
                "original_title": original_title,
                "platform": "Disney+",
                "category": "top10",
                "url": item["href"],
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
            f"쿠팡플레이 페이지 오류: {e}"
        )

        return []

    # --------------------------------------------------------
    # 기존 방식과 호환되는 일반적인 제목 추출
    # --------------------------------------------------------

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

            value = normalize_title(value)

            if not value:
                continue

            if value in titles:
                continue

            # 너무 명백한 UI 문자열 제거
            lower = value.lower()

            bad_words = [
                "로그인",
                "회원가입",
                "쿠팡플레이",
                "무료체험",
                "검색",
                "더보기",
                "menu",
                "login",
                "sign up",
            ]

            if any(
                bad.lower() in lower
                for bad in bad_words
            ):
                continue

            titles.append(value)

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
        f"Coupang Play 제목 {len(output)}개"
    )

    return output


# ============================================================
# 플랫폼별 순위 변화 계산
# ============================================================

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
            f"{filename} 읽기 오류: {e}"
        )

        return default


def save_json(filename, data):

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
# 이전 순위 찾기
# ============================================================

def find_previous_rank(
    previous_items,
    current_item,
):

    current_title = normalize_compare(
        current_item.get("title", "")
    )

    original_title = normalize_compare(
        current_item.get("original_title", "")
    )

    for item in previous_items:

        old_title = normalize_compare(
            item.get("title", "")
        )

        old_original = normalize_compare(
            item.get("original_title", "")
        )

        if (
            current_title
            and current_title == old_title
        ):

            return item.get("rank")

        if (
            original_title
            and original_title == old_original
        ):

            return item.get("rank")

    return None


# ============================================================
# 순위 변화
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

        old_items = previous_by_platform.get(
            platform,
            [],
        )

        old_rank = find_previous_rank(
            old_items,
            item,
        )

        current_rank = item.get(
            "rank"
        )

        if old_rank is None:

            item["previous_rank"] = None
            item["change"] = "NEW"

        else:

            item["previous_rank"] = old_rank

            if current_rank < old_rank:

                item["change"] = (
                    f"+{old_rank - current_rank}"
                )

            elif current_rank > old_rank:

                item["change"] = (
                    f"-{current_rank - old_rank}"
                )

            else:

                item["change"] = "0"


    return current


# ============================================================
# 날짜
# ============================================================

def korea_now():

    return datetime.now(
        timezone.utc
    ) + timedelta(hours=9)


def today_string():

    return korea_now().strftime(
        "%Y-%m-%d"
    )


# ============================================================
# 오래된 history 정리
# ============================================================

def cleanup_history(history):

    cutoff = (
        korea_now()
        - timedelta(days=KEEP_DAYS)
    ).strftime("%Y-%m-%d")

    cleaned = []

    for item in history:

        date = item.get(
            "date",
            "",
        )

        if date >= cutoff:
            cleaned.append(item)

    return cleaned


# ============================================================
# MAIN
# ============================================================

def main():

    print("")
    print("=" * 60)
    print("OTT RANKING COLLECTOR")
    print("=" * 60)

    print(
        f"실행일: {today_string()}"
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

    print("")
    print("=" * 60)
    print("수집 결과")
    print("=" * 60)

    print(
        f"Netflix       : {len(netflix)}"
    )

    print(
        f"Disney+       : {len(disney)}"
    )

    print(
        f"Coupang Play  : {len(coupang)}"
    )

    print(
        f"전체           : {len(current)}"
    )

    # --------------------------------------------------------
    # 이전 ranking
    # --------------------------------------------------------

    previous_data = load_json(
        RANKING_FILE,
        [],
    )

    # ranking.json이 객체 형태인 경우
    if isinstance(
        previous_data,
        dict,
    ):

        previous = previous_data.get(
            "items",
            [],
        )

    else:

        previous = previous_data

    current = calculate_changes(
        current,
        previous,
    )

    # --------------------------------------------------------
    # ranking.json
    # --------------------------------------------------------

    ranking_data = {
        "updated_at": korea_now().isoformat(),
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
    # 화면 출력
    # --------------------------------------------------------

    print("")
    print("=" * 60)
    print("OTT RANKING")
    print("=" * 60)

    for platform in (
        "Netflix",
        "Disney+",
        "Coupang Play",
    ):

        print("")
        print(f"[{platform}]")

        platform_items = [
            item
            for item in current
            if item.get(
                "platform"
            ) == platform
        ]

        for item in platform_items:

            change = item.get(
                "change",
                "NEW",
            )

            title = item.get(
                "title",
                "",
            )

            original = item.get(
                "original_title",
                "",
            )

            if (
                original
                and original != title
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
    print("=" * 60)
    print("저장 완료")
    print("=" * 60)


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
