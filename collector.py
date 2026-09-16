import csv
import io
import json
import os
import re
import sys
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
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

NETFLIX_TITLE_CACHE_FILE = "netflix_title_cache.json"
NETFLIX_TITLE_CACHE_DAYS = 7


# Netflix TSV의 큰 필드 때문에 필요한 설정
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

    with urllib.request.urlopen(req, timeout=timeout) as response:

        raw = response.read()

        charset = response.headers.get_content_charset()

        if charset:
            return raw.decode(charset, errors="replace")

        return raw.decode("utf-8", errors="replace")


# =========================================================
# 문자열 정리
# =========================================================

def normalize_title(value):

    if value is None:
        return ""

    value = str(value)

    value = value.replace("\xa0", " ")
    value = value.replace("\u200b", "")
    value = value.replace("\ufeff", "")

    value = re.sub(r"\s+", " ", value)

    return value.strip()


def normalize_key(value):

    value = normalize_title(value).lower()

    value = re.sub(
        r"[^0-9a-z가-힣]+",
        "",
        value,
    )

    return value


# =========================================================
# Netflix TSV
# =========================================================

def get_netflix_tsv():

    print("Netflix TSV 다운로드 중...")

    return fetch_text(
        NETFLIX_TSV_URL,
        timeout=60,
    )


def parse_netflix_tsv(text):

    reader = csv.DictReader(
        io.StringIO(text),
        delimiter="\t",
    )

    rows = list(reader)

    if not rows:
        raise RuntimeError(
            "Netflix TSV 데이터가 없습니다."
        )

    # -----------------------------------------------------
    # 한국 데이터만 필터
    # -----------------------------------------------------

    kr_rows = []

    for row in rows:

        country_iso = normalize_title(
            row.get("country_iso2", "")
        ).upper()

        country_name = normalize_title(
            row.get("country_name", "")
        )

        if (
            country_iso == COUNTRY_CODE
            or country_name.lower() == "south korea"
        ):
            kr_rows.append(row)

    if not kr_rows:
        raise RuntimeError(
            "Netflix 한국 데이터를 찾지 못했습니다."
        )

    # -----------------------------------------------------
    # 가장 최신 주차
    # -----------------------------------------------------

    weeks = sorted(
        {
            normalize_title(
                row.get("week", "")
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
            row.get("week", "")
        ) == latest_week
    ]

    movies = []
    tv = []

    # -----------------------------------------------------
    # 최신 주차 데이터 분류
    # -----------------------------------------------------

    for row in latest_rows:

        category = normalize_title(
            row.get("category", "")
        ).lower()

        try:
            rank = int(
                normalize_title(
                    row.get("weekly_rank", "")
                )
            )
        except Exception:
            continue

        title = normalize_title(
            row.get("show_title", "")
        )

        season = normalize_title(
            row.get("season_title", "")
        )

        if not title:
            continue

        item = {
            "r": rank,
            "t": title,
        }

        # 시즌명이 작품명과 실제로 다를 경우만 저장
        if (
            season
            and season.upper() != "N/A"
            and season != title
        ):
            item["s"] = season

        if category == "films":
            movies.append(item)

        elif category == "tv":
            tv.append(item)

        elif category == "shows":
            tv.append(item)

        elif "film" in category:
            movies.append(item)

        elif "tv" in category:
            tv.append(item)

        elif "show" in category:
            tv.append(item)

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
# Netflix 공식 한국 제목 확인
#
# 속도 개선:
# 1. 기존 Tudum 영화/TV 페이지는 그대로 1회씩 확인
# 2. 한국 제목이 필요한 경우에만 Netflix 한국 검색 페이지를 사용
# 3. 영화/TV 제목 조회는 동시에 실행
# 4. 이미 확인한 제목은 netflix_title_cache.json에 저장
# 5. 공식 제목을 확인하지 못하면 TSV 제목을 그대로 유지
# =========================================================

def load_netflix_title_cache():
    if not os.path.exists(NETFLIX_TITLE_CACHE_FILE):
        return {}
    try:
        with open(NETFLIX_TITLE_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_netflix_title_cache(cache):
    try:
        with open(NETFLIX_TITLE_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Netflix 제목 캐시 저장 실패:", e)


def cache_is_fresh(entry):
    if not isinstance(entry, dict):
        return False
    checked = entry.get("checked", "")
    try:
        checked_at = datetime.fromisoformat(checked)
        now = datetime.now(timezone.utc)
        return (now - checked_at).days < NETFLIX_TITLE_CACHE_DAYS
    except Exception:
        return False



def extract_netflix_titles_from_page(html):
    """Tudum Top 10 페이지의 실제 순위 버튼 제목만 추출."""
    titles = []
    if not html:
        return titles

    # Tudum 현재 페이지에 실제 순위 데이터로 표시되는 형태:
    # [Button: Shelter]
    matches = re.findall(r'\[Button:\s*([^\]]+)\]', html, flags=re.IGNORECASE)
    for value in matches:
        value = normalize_title(value)
        if not value:
            continue
        low = value.lower()
        if low in {"more details", "top 10 search", "my list", "watch", "explore"}:
            continue
        if value not in titles:
            titles.append(value)
    return titles


def extract_netflix_search_titles(html):
    """Netflix 한국 검색 HTML에서 콘텐츠 제목 후보를 추출한다."""
    titles = []
    if not html:
        return titles

    # 검색 결과의 title/name/alt/aria-label 후보
    patterns = [
        r'"title"\s*:\s*"([^"\\]{1,200})"',
        r'"name"\s*:\s*"([^"\\]{1,200})"',
        r'aria-label\s*=\s*["\']([^"\']{1,200})["\']',
        r'\balt\s*=\s*["\']([^"\']{1,200})["\']',
    ]

    for pattern in patterns:
        for value in re.findall(pattern, html, flags=re.IGNORECASE):
            value = normalize_title(value)
            if not value or len(value) > 200:
                continue
            low = value.lower()
            if low in {
                "netflix", "home", "movies", "shows", "my list", "watch",
                "explore", "search", "sign in", "sign up", "image"
            }:
                continue
            if "http://" in low or "https://" in low:
                continue
            if value not in titles:
                titles.append(value)

    return titles


def get_netflix_search_title(original_title):
    """Netflix 한국 검색에서 공식 표시 제목을 찾는다.

    검색 결과가 없거나 확실한 결과가 없으면 None을 반환한다.
    """
    original_title = normalize_title(original_title)
    if not original_title:
        return None

    url = (
        "https://www.netflix.com/kr/search?q="
        + urllib.parse.quote(original_title)
    )

    try:
        html = fetch_text(url, timeout=12)
    except Exception:
        return None

    candidates = extract_netflix_search_titles(html)
    if not candidates:
        return None

    original_key = normalize_key(original_title)

    # 원제와 완전히 같은 제목이면 번역된 제목이 아니므로 그대로 사용.
    for candidate in candidates:
        if normalize_key(candidate) == original_key:
            return candidate

    # 한국어가 포함된 후보를 우선한다.
    korean_candidates = [
        x for x in candidates
        if re.search(r'[가-힣]', x)
    ]

    # 검색 결과 첫 후보가 UI 문구일 가능성을 낮추기 위해
    # 지나치게 짧은 값은 제외한다.
    korean_candidates = [x for x in korean_candidates if len(x.strip()) >= 2]

    if korean_candidates:
        return korean_candidates[0]

    # Netflix 한국 페이지에서 영어 제목으로 공식 표시하는 경우
    # 원래 TSV 제목을 유지한다.
    return None


def build_netflix_search_map(data, cache):
    """현재 TOP10 중 최근 7일 이내 확인하지 않은 제목만 병렬로 확인한다."""
    items = []
    for group in ("movies", "tv"):
        for item in data.get(group, []):
            title = normalize_title(item.get("t", ""))
            if not title:
                continue
            entry = cache.get(title)
            if cache_is_fresh(entry):
                continue
            items.append(title)

    items = list(dict.fromkeys(items))
    if not items:
        return cache

    print("Netflix 한국 제목 신규 확인:", len(items), "개")

    max_workers = min(10, len(items))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(get_netflix_search_title, title): title
            for title in items
        }
        for future in as_completed(futures):
            original = futures[future]
            try:
                result = future.result()
            except Exception:
                result = None

            cache[original] = {
                "title": result if result else original,
                "checked": datetime.now(timezone.utc).isoformat(),
            }

    return cache



def apply_netflix_official_titles(data):
    print("Netflix 한국 공식 제목 확인 중...")

    # Tudum 페이지는 실제 공식 Top 10 데이터 확인용으로 유지한다.
    # 영화/TV 페이지를 동시에 요청해 불필요한 대기 시간을 줄인다.
    def fetch_movie():
        try:
            return extract_netflix_titles_from_page(
                fetch_text(NETFLIX_KR_MOVIE_URL, timeout=20)
            )
        except Exception as e:
            print("Netflix 영화 공식 페이지 확인 실패:", e)
            return []

    def fetch_tv():
        try:
            return extract_netflix_titles_from_page(
                fetch_text(NETFLIX_KR_TV_URL, timeout=20)
            )
        except Exception as e:
            print("Netflix TV 공식 페이지 확인 실패:", e)
            return []

    with ThreadPoolExecutor(max_workers=2) as executor:
        movie_future = executor.submit(fetch_movie)
        tv_future = executor.submit(fetch_tv)
        movie_titles = movie_future.result()
        tv_titles = tv_future.result()

    print("Netflix 영화 Top10 공식 제목:", len(movie_titles))
    print("Netflix TV Top10 공식 제목:", len(tv_titles))

    # 현재 TSV의 제목을 기준으로 한국 Netflix 검색에서 공식 표시 제목을 확인한다.
    cache = load_netflix_title_cache()
    cache = build_netflix_search_map(data, cache)
    save_netflix_title_cache(cache)

    for group in ("movies", "tv"):
        for item in data.get(group, []):
            original = normalize_title(item.get("t", ""))
            if not original:
                continue
            entry = cache.get(original)
            if isinstance(entry, dict):
                official = entry.get("title", original)
            else:
                # 이전 버전 캐시 호환
                official = entry if entry else original
            if official and normalize_title(official):
                item["t"] = normalize_title(official)

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

    # -----------------------------------------------------
    # Disney+ 콘텐츠 데이터만 사용
    # -----------------------------------------------------
    # aria-label에는 Nav Link / Log In / 지역코드 등
    # UI 접근성 문구가 섞이므로 사용하지 않는다.
    patterns = [
        r'"title"\s*:\s*"([^"\\]+)"',
        r'"name"\s*:\s*"([^"\\]+)"',
        r'"contentTitle"\s*:\s*"([^"\\]+)"',
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
            value = normalize_title(value)
            if not value:
                continue
            if len(value) > 100:
                continue
            if value not in titles:
                titles.append(value)

    # -----------------------------------------------------
    # UI / 로그인 / 지역코드 / 시스템 문자열 제거
    # -----------------------------------------------------
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
        "log in",
        "search",
        "menu",
        "home",
        "nav link",
        "identity",
        "usuf",
        "latam",
        "emea",
        "aunz",
        "apac",
        "ca",
    }

    bad_fragments = [
        "nav link",
        "/identity/",
        "identity/login",
        "us/uf",
        "usufu",
        "latam",
        "emea",
        "aunz",
        "apac",
        "log in",
        "login",
    ]

    filtered = []

    for title in titles:
        if title in bad_words:
            continue

        if len(title) <= 1:
            continue

        low = title.lower()

        if any(fragment in low for fragment in bad_fragments):
            continue

        if re.search(r'\b(?:USUF|LATAM|EMEA|AUNZ|APAC)\b', title, re.I):
            continue

        if "http://" in low or "https://" in low:
            continue

        if "javascript" in low:
            continue

        if title not in filtered:
            filtered.append(title)

    return [
        {
            "r": index + 1,
            "t": title,
            "c": 0,
        }
        for index, title
        in enumerate(filtered[:10])
    ]


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

    # -----------------------------------------------------
    # 제목 후보
    # -----------------------------------------------------

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
                titles.append(value)

    # -----------------------------------------------------
    # 광고 / UI / 예고편 제거
    # -----------------------------------------------------

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
            filtered.append(title)

    # -----------------------------------------------------
    # TOP 20
    # -----------------------------------------------------

    return [
        {
            "r": index + 1,
            "t": title,
            "c": 0,
        }
        for index, title
        in enumerate(filtered[:20])
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

            return json.load(f)

    except Exception:

        return None


# =========================================================
# 순위 맵
# =========================================================

def previous_rank_map(items):

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
            result[title] = rank

    return result


# =========================================================
# 순위 변동 계산
#
# 이전 5위 → 현재 2위 = +3
# 이전 2위 → 현재 5위 = -3
# 동일 = 0
# 처음 등장 = NEW
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

        current_rank = item.get(
            "r"
        )

        if title not in previous:

            item["c"] = "NEW"

            continue

        old_rank = previous[title]

        try:

            change = (
                int(old_rank)
                - int(current_rank)
            )

            item["c"] = change

        except Exception:

            item["c"] = 0


# =========================================================
# History 생성
# =========================================================

def make_history_entry(
    date_string,
    netflix,
    disney,
    coupang,
):

    def rank_map(items):

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

                result[title] = rank

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

            data = json.load(f)

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

    # 한국 시간
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
        .strftime("%Y-%m-%d")
    )

    entry = make_history_entry(
        today,
        netflix,
        disney,
        coupang,
    )

    # -----------------------------------------------------
    # 같은 날짜 데이터 삭제
    # -----------------------------------------------------

    history["h"] = [
        item
        for item in history["h"]
        if item.get("d") != today
    ]

    # -----------------------------------------------------
    # 오늘 데이터 추가
    # -----------------------------------------------------

    history["h"].append(
        entry
    )

    # -----------------------------------------------------
    # 날짜순 정렬
    # -----------------------------------------------------

    history["h"].sort(
        key=lambda x: x.get(
            "d",
            "",
        )
    )

    # -----------------------------------------------------
    # 최근 30일만 유지
    # -----------------------------------------------------

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
# 최초 실행 시 변동값 설정
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

    # 공식 한국 페이지 제목 확인
    netflix = apply_netflix_official_titles(
        netflix
    )

    # -----------------------------------------------------
    # Disney+
    # -----------------------------------------------------

    print("")
    print("[2/3] Disney+")

    try:

        disney = get_disney()

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
    print("순위 변동 계산 중...")

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

        # Netflix 영화
        calculate_changes(
            netflix["movies"],
            old_netflix.get(
                "movies",
                [],
            ),
        )

        # Netflix TV
        calculate_changes(
            netflix["tv"],
            old_netflix.get(
                "tv",
                [],
            ),
        )

        # Disney+
        calculate_changes(
            disney,
            old_disney,
        )

        # Coupang Play
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
    # 결과 출력
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

    # -----------------------------------------------------
    # Netflix 영화 출력
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # Netflix TV 출력
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # Disney 출력
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # Coupang 출력
    # -----------------------------------------------------

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
