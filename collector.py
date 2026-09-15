
import csv
import io
import json
import os
import re
import sys
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

REGION = "South Korea"
COUNTRY_CODE = "KR"

KEEP_DAYS = 30


# Python CSV field limit
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
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
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
        value
    )

    return value


# =========================================================
# Netflix TSV
# =========================================================

def get_netflix_tsv():

    print("Netflix TSV 다운로드 중...")

    text = fetch_text(NETFLIX_TSV_URL, timeout=60)

    return text


def parse_netflix_tsv(text):

    reader = csv.DictReader(
        io.StringIO(text),
        delimiter="\t"
    )

    rows = list(reader)

    if not rows:
        raise RuntimeError(
            "Netflix TSV 데이터가 없습니다."
        )

    # KR만 필터
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

    # 가장 최신 주차
    weeks = sorted(
        {
            normalize_title(row.get("week", ""))
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
        if normalize_title(row.get("week", "")) == latest_week
    ]

    movies = []
    tv = []

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

        # 시즌명이 실제 작품명과 다를 경우만 저장
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

    movies.sort(key=lambda x: x["r"])
    tv.sort(key=lambda x: x["r"])

    return {
        "week": latest_week,
        "movies": movies[:10],
        "tv": tv[:10],
    }


# =========================================================
# Netflix 한국 공식 페이지 제목 추출
#
# 중요:
# 공식 페이지에서 제공하는 제목만 사용한다.
# 자동 번역하지 않는다.
# =========================================================

def extract_netflix_titles_from_page(html):

    titles = []

    if not html:
        return titles

    # -----------------------------------------------------
    # 1. Button / Image 주변 제목
    # -----------------------------------------------------

    patterns = [

        r'\[Button:\s*([^\]]+)\]',

        r'Image#\d+\s*(?:in Movies|in Shows)?\s*'
        r'(?:Image#\d+\s*)?([A-Z][^\n]{1,200})',

    ]

    for pattern in patterns:

        try:

            matches = re.findall(
                pattern,
                html,
                flags=re.IGNORECASE
            )

            for value in matches:

                value = normalize_title(value)

                if not value:
                    continue

                if len(value) > 200:
                    continue

                if value.lower() in {
                    "my list",
                    "watch",
                    "explore",
                    "image",
                    "movies",
                    "shows",
                }:
                    continue

                if value not in titles:
                    titles.append(value)

        except Exception:
            pass

    # -----------------------------------------------------
    # 2. JSON-LD title
    # -----------------------------------------------------

    json_patterns = [

        r'"name"\s*:\s*"([^"]{1,200})"',

        r'"title"\s*:\s*"([^"]{1,200})"',

    ]

    for pattern in json_patterns:

        try:

            matches = re.findall(
                pattern,
                html,
                flags=re.IGNORECASE
            )

            for value in matches:

                value = normalize_title(value)

                if not value:
                    continue

                if len(value) > 200:
                    continue

                if value not in titles:
                    titles.append(value)

        except Exception:
            pass

    return titles


# =========================================================
# Netflix 제목 매칭
# =========================================================

def build_title_map(page_titles):

    mapping = {}

    for title in page_titles:

        title = normalize_title(title)

        if not title:
            continue

        key = normalize_key(title)

        if not key:
            continue

        mapping[key] = title

    return mapping


def find_official_title(original_title, title_map):

    original_title = normalize_title(
        original_title
    )

    if not original_title:
        return original_title

    key = normalize_key(original_title)

    if key in title_map:
        return title_map[key]

    return original_title


# =========================================================
# Netflix 제목 매칭 실행
# =========================================================

def apply_netflix_official_titles(data):

    print("Netflix 한국 공식 페이지 제목 확인 중...")

    movie_titles = []
    tv_titles = []

    try:

        movie_html = fetch_text(
            NETFLIX_KR_MOVIE_URL,
            timeout=30
        )

        movie_titles = extract_netflix_titles_from_page(
            movie_html
        )

        print(
            "Netflix 영화 페이지 제목:",
            len(movie_titles)
        )

    except Exception as e:

        print(
            "Netflix 영화 제목 페이지 확인 실패:",
            e
        )


    try:

        tv_html = fetch_text(
            NETFLIX_KR_TV_URL,
            timeout=30
        )

        tv_titles = extract_netflix_titles_from_page(
            tv_html
        )

        print(
            "Netflix TV 페이지 제목:",
            len(tv_titles)
        )

    except Exception as e:

        print(
            "Netflix TV 제목 페이지 확인 실패:",
            e
        )


    movie_map = build_title_map(
        movie_titles
    )

    tv_map = build_title_map(
        tv_titles
    )


    # -----------------------------------------------------
    # 영화
    # -----------------------------------------------------

    for item in data.get("movies", []):

        original = item.get("t", "")

        matched = find_official_title(
            original,
            movie_map
        )

        item["t"] = matched


    # -----------------------------------------------------
    # TV
    # -----------------------------------------------------

    for item in data.get("tv", []):

        original = item.get("t", "")

        matched = find_official_title(
            original,
            tv_map
        )

        item["t"] = matched


    return data


# =========================================================
# Disney+
#
# 현재 페이지의 TOP 10 주변 제목을 추출한다.
# =========================================================

def get_disney():

    print("Disney+ 데이터 수집 중...")

    html = fetch_text(
        DISNEY_URL,
        timeout=30
    )

    titles = []

    # 한글 제목 중심으로 추출
    patterns = [

        r'"title"\s*:\s*"([^"]+)"',

        r'"name"\s*:\s*"([^"]+)"',

        r'aria-label="([^"]+)"',

    ]

    for pattern in patterns:

        matches = re.findall(
            pattern,
            html,
            flags=re.IGNORECASE
        )

        for value in matches:

            value = normalize_title(value)

            if not value:
                continue

            if len(value) > 100:
                continue

            if value not in titles:
                titles.append(value)


    # 불필요한 UI 문자열
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

    }


    filtered = []

    for title in titles:

        if title in bad_words:
            continue

        if title not in filtered:
            filtered.append(title)


    # 현재 페이지 구조가 변경될 수 있으므로
    # TOP10 영역 주변에서 흔히 나오는 제목을 우선 사용
    result = []

    for title in filtered:

        # 너무 짧은 UI 문구 제거
        if len(title) <= 1:
            continue

        # URL이나 CSS/JS 형태 제거
        if "http://" in title.lower():
            continue

        if "javascript" in title.lower():
            continue

        result.append(title)


    # 실제 TOP10을 찾지 못한 경우 빈 목록
    # 임의의 데이터를 만들지 않는다.

    return [
        {
            "r": index + 1,
            "t": title,
            "c": 0
        }

        for index, title
        in enumerate(result[:10])
    ]


# =========================================================
# Coupang Play
# =========================================================

def get_coupang():

    print("Coupang Play 데이터 수집 중...")

    html = fetch_text(
        COUPANG_URL,
        timeout=30
    )

    titles = []

    # -----------------------------------------------------
    # 텍스트 기반 제목 후보
    # -----------------------------------------------------

    patterns = [

        r'"title"\s*:\s*"([^"]+)"',

        r'"name"\s*:\s*"([^"]+)"',

        r'"contentTitle"\s*:\s*"([^"]+)"',

    ]

    for pattern in patterns:

        matches = re.findall(
            pattern,
            html,
            flags=re.IGNORECASE
        )

        for value in matches:

            value = normalize_title(value)

            if not value:
                continue

            if len(value) > 100:
                continue

            if value not in titles:
                titles.append(value)


    # -----------------------------------------------------
    # 불필요한 값 제거
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


        if title not in filtered:

            filtered.append(title)


    result = []

    for title in filtered:

        if len(title) <= 1:
            continue

        result.append(title)


    return [
        {
            "r": index + 1,
            "t": title,
            "c": 0
        }

        for index, title
        in enumerate(result[:20])
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
            encoding="utf-8"
        ) as f:

            return json.load(f)

    except Exception:

        return None


# =========================================================
# 순위 변동 계산
# =========================================================

def previous_rank_map(items):

    result = {}

    for item in items or []:

        title = normalize_title(
            item.get("t", "")
        )

        rank = item.get("r")

        if title and rank is not None:

            result[title] = rank

    return result


def calculate_changes(
    current_items,
    previous_items
):

    previous = previous_rank_map(
        previous_items
    )

    for item in current_items:

        title = normalize_title(
            item.get("t", "")
        )

        current_rank = item.get("r")

        if title not in previous:

            item["c"] = "NEW"

            continue

        old_rank = previous[title]

        try:

            change = (
                int(old_rank)
                -
                int(current_rank)
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
    coupang
):

    def rank_map(items):

        result = {}

        for item in items or []:

            title = normalize_title(
                item.get("t", "")
            )

            rank = item.get("r")

            if title and rank is not None:

                result[title] = rank

        return result


    return {

        "d": date_string,

        "n": {

            "m": rank_map(
                netflix.get("movies", [])
            ),

            "t": rank_map(
                netflix.get("tv", [])
            ),

        },

        "d+": rank_map(
            disney
        ),

        "c": rank_map(
            coupang
        ),

    }


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
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        if not isinstance(
            data,
            dict
        ):

            return {
                "h": []
            }

        if not isinstance(
            data.get("h"),
            list
        ):

            data["h"] = []

        return data

    except Exception:

        return {
            "h": []
        }


def save_history(
    netflix,
    disney,
    coupang
):

    history = load_history()

    today = datetime.now(
        timezone.utc
    ).astimezone(
        timezone(
            timedelta(hours=9)
        )
    ).strftime("%Y-%m-%d")


    entry = make_history_entry(
        today,
        netflix,
        disney,
        coupang
    )


    # 같은 날짜가 있으면 교체
    history["h"] = [

        item

        for item in history["h"]

        if item.get("d") != today

    ]


    history["h"].append(entry)


    # 날짜순 정렬
    history["h"].sort(
        key=lambda x: x.get("d", "")
    )


    # 최근 30일
    history["h"] = history["h"][
        -KEEP_DAYS:
    ]


    with open(
        HISTORY_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            history,
            f,
            ensure_ascii=False,
            indent=2
        )


# =========================================================
# JSON 저장
# =========================================================

def save_json(
    filename,
    data
):

    with open(
        filename,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )


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
    # 기존 데이터
    # -----------------------------------------------------

    previous = load_ranking()


    # -----------------------------------------------------
    # Netflix
    # -----------------------------------------------------

    netflix_tsv = get_netflix_tsv()

    netflix = parse_netflix_tsv(
            netflix_tsv
        )


    # Netflix 공식 한국 페이지
    # 제목 매칭
    netflix =
        apply_netflix_official_titles(
            netflix
        )


    # -----------------------------------------------------
    # Disney+
    # -----------------------------------------------------

    try:

        disney =
            get_disney()

    except Exception as e:

        print(
            "Disney+ 수집 실패:",
            e
        )

        disney = []


    # -----------------------------------------------------
    # Coupang Play
    # -----------------------------------------------------

    try:

        coupang =
            get_coupang()

    except Exception as e:

        print(
            "Coupang Play 수집 실패:",
            e
        )

        coupang = []


    # -----------------------------------------------------
    # 순위 변동
    # -----------------------------------------------------

    if previous:

        old_netflix =
            previous.get(
                "netflix",
                {}
            )

        old_disney =
            previous.get(
                "disney",
                []
            )

        old_coupang =
            previous.get(
                "coupang",
                []
            )


        calculate_changes(

            netflix["movies"],

            old_netflix.get(
                "movies",
                []
            )

        )


        calculate_changes(

            netflix["tv"],

            old_netflix.get(
                "tv",
                []
            )

        )


        calculate_changes(

            disney,

            old_disney

        )


        calculate_changes(

            coupang,

            old_coupang

        )


    else:

        # 최초 실행
        # 변동 없음으로 시작

        for item in netflix["movies"]:

            item["c"] = 0


        for item in netflix["tv"]:

            item["c"] = 0


        for item in disney:

            item["c"] = 0


        for item in coupang:

            item["c"] = 0


    # -----------------------------------------------------
    # 현재 시간
    # -----------------------------------------------------

    updated_at =
        datetime.now(
            timezone.utc
        ).isoformat()


    # -----------------------------------------------------
    # ranking.json
    # -----------------------------------------------------

    ranking = {

        "updated_at":
            updated_at,

        "netflix": netflix,

        "disney":
            disney,

        "coupang":
            coupang,

    }


    save_json(
        RANKING_FILE,
        ranking
    )


    # -----------------------------------------------------
    # history.json
    # -----------------------------------------------------

    save_history(

        netflix,

        disney,

        coupang

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
        "Netflix 영화:",
        len(netflix["movies"])
    )

    print(
        "Netflix TV:",
        len(netflix["tv"])
    )

    print(
        "Disney+:",
        len(disney)
    )

    print(
        "Coupang Play:",
        len(coupang)
    )

    print("")

    print("Netflix 영화 TOP 10")

    for item in netflix["movies"]:

        print(
            item["r"],
            item["t"]
        )

    print("")

    print("Netflix TV TOP 10")

    for item in netflix["tv"]:

        print(
            item["r"],
            item["t"]
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
