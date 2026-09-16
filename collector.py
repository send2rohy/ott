import csv
import io
import json
import os
import re
import sys
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
# =========================================================
# Netflix 공식 한국 페이지 제목 확인
#
# Netflix Tudum은 언어별 페이지를 제공한다.
# 한국어 페이지에서 같은 주차의 순위 제목을 순위 번호로 대응시킨다.
#
# 중요:
# - 기계 번역하지 않는다.
# - 제목별 검색을 하지 않는다.
# - 한국어 공식 페이지를 가져오지 못하면 TSV 원제 유지.
# - Disney+ / Coupang Play 코드는 이 부분에서 건드리지 않는다.
# =========================================================

NETFLIX_KR_LOCAL_MOVIE_URL = (
    "https://www.netflix.com/tudum/top10/ko/south-korea/films.html"
)

NETFLIX_KR_LOCAL_TV_URL = (
    "https://www.netflix.com/tudum/top10/ko/south-korea/tv.html"
)


def extract_netflix_rank_titles_from_page(html):
    """Netflix Tudum 페이지의 [Button: 제목] 순위만 순서대로 추출."""

    titles = []

    if not html:
        return titles

    matches = re.findall(
        r"\[Button:\s*([^\]]+)\]",
        html,
        flags=re.IGNORECASE,
    )

    for value in matches:
        value = normalize_title(value)

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
            "more details",
            "top 10 search",
        }:
            continue

        if value not in titles:
            titles.append(value)

        if len(titles) >= 10:
            break

    return titles[:10]


def apply_netflix_official_titles(data):
    print("Netflix 한국 공식 제목 확인 중...")

    # 한국어 Tudum 페이지를 영화/TV 동시에 요청한다.
    # 하나가 실패해도 다른 쪽에는 영향을 주지 않는다.
    from concurrent.futures import ThreadPoolExecutor

    urls = {
        "movies": NETFLIX_KR_LOCAL_MOVIE_URL,
        "tv": NETFLIX_KR_LOCAL_TV_URL,
    }

    results = {
        "movies": [],
        "tv": [],
    }

    def fetch_one(kind):
        try:
            html = fetch_text(
                urls[kind],
                timeout=20,
            )
            return kind, extract_netflix_rank_titles_from_page(html)
        except Exception as e:
            print(
                "Netflix 한국어 공식 페이지 확인 실패:",
                kind,
                e,
            )
            return kind, []

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(fetch_one, kind)
            for kind in ("movies", "tv")
        ]

        for future in futures:
            kind, titles = future.result()
            results[kind] = titles

    print(
        "Netflix 한국어 영화 제목 확인:",
        len(results["movies"]),
    )
    print(
        "Netflix 한국어 TV 제목 확인:",
        len(results["tv"]),
    )

    # -----------------------------------------------------
    # 순위 번호로 대응
    #
    # Netflix TSV와 Tudum 페이지는 같은 국가/주차의 Top 10이다.
    # 따라서 제목 자체를 억지로 매칭하지 않고 rank 1~10으로 대응한다.
    # -----------------------------------------------------

    for item in data.get("movies", []):
        rank = item.get("r")

        if isinstance(rank, int) and 1 <= rank <= len(results["movies"]):
            official = results["movies"][rank - 1]

            if official:
                item["t"] = official

    for item in data.get("tv", []):
        rank = item.get("r")

        if isinstance(rank, int) and 1 <= rank <= len(results["tv"]):
            official = results["tv"][rank - 1]

            if official:
                item["t"] = official

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
    # Disney+ 페이지 제목 후보
    # -----------------------------------------------------

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
                titles.append(value)

    # -----------------------------------------------------
    # 불필요한 UI 문자열
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
