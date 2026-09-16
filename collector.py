import csv
import io
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from urllib.parse import quote


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

# Netflix 한국 검색
NETFLIX_KR_SEARCH_URL = (
    "https://www.netflix.com/kr/search?q={}"
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

    with urllib.request.urlopen(
        req,
        timeout=timeout
    ) as response:

        raw = response.read()

        charset = response.headers.get_content_charset()

        if charset:
            return raw.decode(
                charset,
                errors="replace"
            )

        return raw.decode(
            "utf-8",
            errors="replace"
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
        " "
    )

    value = value.replace(
        "\u200b",
        ""
    )

    value = value.replace(
        "\ufeff",
        ""
    )

    value = re.sub(
        r"\s+",
        " ",
        value
    )

    return value.strip()


def normalize_key(value):

    value = normalize_title(
        value
    ).lower()

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

    print(
        "Netflix TSV 다운로드 중..."
    )

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
            row.get(
                "country_iso2",
                ""
            )
        ).upper()

        country_name = normalize_title(
            row.get(
                "country_name",
                ""
            )
        )

        if (
            country_iso == COUNTRY_CODE
            or country_name.lower() == "south korea"
        ):

            kr_rows.append(
                row
            )

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
                row.get(
                    "week",
                    ""
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
                ""
            )
        ) == latest_week
    ]

    movies = []

    tv = []

    # -----------------------------------------------------
    # 최신 주차 데이터 분류
    # -----------------------------------------------------

    for row in latest_rows:

        category = normalize_title(
            row.get(
                "category",
                ""
            )
        ).lower()

        try:

            rank = int(
                normalize_title(
                    row.get(
                        "weekly_rank",
                        ""
                    )
                )
            )

        except Exception:

            continue

        title = normalize_title(
            row.get(
                "show_title",
                ""
            )
        )

        season = normalize_title(
            row.get(
                "season_title",
                ""
            )
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
# Netflix 한국 공식 제목 확인
#
# 원칙
# 1. 자동 번역하지 않는다.
# 2. Netflix 한국 사이트에서 실제로 확인되는 제목만 사용한다.
# 3. Netflix 한국 사이트가 영어 제목을 사용하면 영어 그대로 둔다.
# 4. 확실한 결과가 없으면 Netflix TSV 원래 제목을 유지한다.
# =========================================================


class NetflixSearchParser(HTMLParser):

    def __init__(self):

        super().__init__(
            convert_charrefs=True
        )

        self.results = []

        self.current_href = ""

        self.current_text = []

        self.current_aria = ""

        self.current_title = ""

        self.current_alt = ""


    def handle_starttag(
        self,
        tag,
        attrs
    ):

        attrs = dict(
            attrs
        )

        if tag.lower() == "a":

            href = attrs.get(
                "href",
                ""
            )

            if re.search(
                r"/kr(?:-[a-z]{2})?/title/\d+",
                href,
                flags=re.IGNORECASE
            ):

                self.current_href = href

                self.current_text = []

                self.current_aria = normalize_title(
                    attrs.get(
                        "aria-label",
                        ""
                    )
                )

                self.current_title = normalize_title(
                    attrs.get(
                        "title",
                        ""
                    )
                )

                self.current_alt = ""

        elif tag.lower() == "img":

            if self.current_href:

                self.current_alt = normalize_title(
                    attrs.get(
                        "alt",
                        ""
                    )
                )


    def handle_data(
        self,
        data
    ):

        if self.current_href:

            value = normalize_title(
                data
            )

            if value:

                self.current_text.append(
                    value
                )


    def handle_endtag(
        self,
        tag
    ):

        if tag.lower() == "a":

            if self.current_href:

                values = []

                if self.current_aria:

                    values.append(
                        self.current_aria
                    )

                if self.current_title:

                    values.append(
                        self.current_title
                    )

                if self.current_alt:

                    values.append(
                        self.current_alt
                    )

                if self.current_text:

                    text = normalize_title(
                        " ".join(
                            self.current_text
                        )
                    )

                    if text:

                        values.append(
                            text
                        )

                for value in values:

                    value = normalize_title(
                        value
                    )

                    if (
                        value
                        and value not in self.results
                    ):

                        self.results.append(
                            value
                        )

            self.current_href = ""

            self.current_text = []

            self.current_aria = ""

            self.current_title = ""

            self.current_alt = ""


def is_valid_netflix_title(
    value
):

    value = normalize_title(
        value
    )

    if not value:
        return False

    if len(value) < 2:
        return False

    if len(value) > 200:
        return False

    low = value.lower()

    bad_values = {
        "image",
        "watch",
        "watch now",
        "my list",
        "more",
        "more details",
        "details",
        "play",
        "trailer",
        "teaser",
        "netflix",
        "netflix korea",
        "sign in",
        "sign up",
        "login",
        "search",
        "menu",
        "home",
        "movies",
        "shows",
        "series",
        "movie",
        "tv",
    }

    if low in bad_values:
        return False

    if "http://" in low:
        return False

    if "https://" in low:
        return False

    if "javascript:" in low:
        return False

    return True


def has_korean(
    value
):

    return bool(
        re.search(
            r"[가-힣]",
            value
        )
    )


def netflix_title_similarity(
    original,
    candidate
):

    original = normalize_title(
        original
    )

    candidate = normalize_title(
        candidate
    )

    if not original or not candidate:
        return 0

    original_key = normalize_key(
        original
    )

    candidate_key = normalize_key(
        candidate
    )

    if not original_key or not candidate_key:
        return 0

    # 완전히 같은 제목
    if original_key == candidate_key:

        return 1000

    score = 0

    # 영문 원제가 후보 제목에 그대로 포함
    if original_key in candidate_key:

        score += 500

    if candidate_key in original_key:

        score += 450

    # 한국어 제목 우선
    if has_korean(
        candidate
    ):

        score += 100

    # 지나치게 긴 설명문 방지
    if len(candidate) <= 80:

        score += 20

    return score


def extract_netflix_search_titles(
    html
):

    if not html:
        return []

    parser = NetflixSearchParser()

    try:

        parser.feed(
            html
        )

    except Exception:

        return []

    results = []

    for value in parser.results:

        value = normalize_title(
            value
        )

        if not is_valid_netflix_title(
            value
        ):

            continue

        if value not in results:

            results.append(
                value
            )

    return results


def get_netflix_official_title(
    original_title
):

    original_title = normalize_title(
        original_title
    )

    if not original_title:

        return original_title

    url = NETFLIX_KR_SEARCH_URL.format(
        quote(
            original_title,
            safe=""
        )
    )

    try:

        print(
            "Netflix 한국 제목 검색:",
            original_title
        )

        html = fetch_text(
            url,
            timeout=30,
        )

    except Exception as e:

        print(
            "Netflix 한국 검색 실패:",
            original_title,
            e
        )

        return original_title

    candidates = extract_netflix_search_titles(
        html
    )

    if not candidates:

        print(
            "  → 검색 결과 제목 없음:",
            original_title
        )

        return original_title

    scored = []

    for candidate in candidates:

        score = netflix_title_similarity(
            original_title,
            candidate
        )

        if score > 0:

            scored.append(
                (
                    score,
                    candidate
                )
            )

    if not scored:

        print(
            "  → 일치 제목 없음:",
            original_title
        )

        return original_title

    scored.sort(
        key=lambda x: (
            x[0],
            -len(x[1])
        ),
        reverse=True
    )

    best_score, best_title = scored[0]

    # 정확히 같은 제목
    if best_score >= 1000:

        print(
            "  → Netflix 공식 제목:",
            best_title
        )

        return best_title

    # 원제가 검색 결과에 포함
    if best_score >= 500:

        print(
            "  → Netflix 공식 제목:",
            best_title
        )

        return best_title

    # 한국어 제목
    if (
        has_korean(best_title)
        and best_score >= 100
    ):

        print(
            "  → Netflix 한국 제목:",
            best_title
        )

        return best_title

    print(
        "  → 확실하지 않아 원제 유지:",
        original_title
    )

    return original_title


def apply_netflix_official_titles(
    data
):

    print("")

    print(
        "Netflix 한국 공식 제목 확인 중..."
    )

    # -----------------------------------------------------
    # 영화
    # -----------------------------------------------------

    for item in data.get(
        "movies",
        []
    ):

        original = normalize_title(
            item.get(
                "t",
                ""
            )
        )

        if not original:
            continue

        official = get_netflix_official_title(
            original
        )

        item["t"] = official

    # -----------------------------------------------------
    # TV
    # -----------------------------------------------------

    for item in data.get(
        "tv",
        []
    ):

        original = normalize_title(
            item.get(
                "t",
                ""
            )
        )

        if not original:
            continue

        official = get_netflix_official_title(
            original
        )

        item["t"] = official

    print(
        "Netflix 한국 공식 제목 확인 완료"
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
        timeout=30
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
                flags=re.IGNORECASE
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
# Coupang Play
# =========================================================

def get_coupang():

    print(
        "Coupang Play 데이터 수집 중..."
    )

    html = fetch_text(
        COUPANG_URL,
        timeout=30
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
                flags=re.IGNORECASE
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

            filtered.append(
                title
            )

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
            encoding="utf-8"
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
    items
):

    result = {}

    for item in items or []:

        title = normalize_title(
            item.get(
                "t",
                ""
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
    previous_items
):

    previous = previous_rank_map(
        previous_items
    )

    for item in current_items:

        title = normalize_title(
            item.get(
                "t",
                ""
            )
        )

        current_rank = item.get(
            "r"
        )

        if title not in previous:

            item["c"] = "NEW"

            continue

        old_rank = previous[
            title
        ]

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
    coupang
):

    def rank_map(
        items
    ):

        result = {}

        for item in items or []:

            title = normalize_title(
                item.get(
                    "t",
                    ""
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
                    []
                )
            ),

            "t": rank_map(
                netflix.get(
                    "tv",
                    []
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
            encoding="utf-8"
        ) as f:

            data = json.load(
                f
            )

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


# =========================================================
# History 저장
# =========================================================

def save_history(
    netflix,
    disney,
    coupang
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
        .strftime(
            "%Y-%m-%d"
        )
    )

    entry = make_history_entry(
        today,
        netflix,
        disney,
        coupang
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
            ""
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
# 최초 실행 시 변동값 설정
# =========================================================

def set_initial_changes(
    netflix,
    disney,
    coupang
):

    for item in netflix.get(
        "movies",
        []
    ):

        item["c"] = 0

    for item in netflix.get(
        "tv",
        []
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

    print(
        "=" * 60
    )

    print(
        "OTT RANKING COLLECTOR"
    )

    print(
        "=" * 60
    )

    print("")

    # -----------------------------------------------------
    # 기존 ranking.json
    # -----------------------------------------------------

    previous = load_ranking()

    # -----------------------------------------------------
    # Netflix
    # -----------------------------------------------------

    print("")

    print(
        "[1/3] Netflix"
    )

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

    print(
        "[2/3] Disney+"
    )

    try:

        disney = get_disney()

    except Exception as e:

        print(
            "Disney+ 수집 실패:",
            e
        )

        disney = []

    # -----------------------------------------------------
    # Coupang Play
    # -----------------------------------------------------

    print("")

    print(
        "[3/3] Coupang Play"
    )

    try:

        coupang = get_coupang()

    except Exception as e:

        print(
            "Coupang Play 수집 실패:",
            e
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
            {}
        )

        old_disney = previous.get(
            "disney",
            []
        )

        old_coupang = previous.get(
            "coupang",
            []
        )

        # Netflix 영화
        calculate_changes(
            netflix["movies"],
            old_netflix.get(
                "movies",
                []
            )
        )

        # Netflix TV
        calculate_changes(
            netflix["tv"],
            old_netflix.get(
                "tv",
                []
            )
        )

        # Disney+
        calculate_changes(
            disney,
            old_disney
        )

        # Coupang Play
        calculate_changes(
            coupang,
            old_coupang
        )

    else:

        print(
            "기존 ranking.json이 없어 최초 실행으로 처리합니다."
        )

        set_initial_changes(
            netflix,
            disney,
            coupang
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

        "updated_at":
            updated_at,

        "netflix":
            netflix,

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

    print(
        "=" * 60
    )

    print(
        "수집 완료"
    )

    print(
        "=" * 60
    )

    print("")

    print(
        "Netflix 주차:",
        netflix.get(
            "week",
            ""
        )
    )

    print(
        "Netflix 영화:",
        len(
            netflix.get(
                "movies",
                []
            )
        )
    )

    print(
        "Netflix TV:",
        len(
            netflix.get(
                "tv",
                []
            )
        )
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

    # -----------------------------------------------------
    # Netflix 영화 출력
    # -----------------------------------------------------

    print(
        "Netflix 영화 TOP 10"
    )

    for item in netflix.get(
        "movies",
        []
    ):

        print(
            item.get("r"),
            item.get("t"),
            "change=",
            item.get("c")
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
        []
    ):

        title = item.get(
            "t",
            ""
        )

        season = item.get(
            "s",
            ""
        )

        if season:

            print(
                item.get("r"),
                title,
                "(",
                season,
                ")",
                "change=",
                item.get("c")
            )

        else:

            print(
                item.get("r"),
                title,
                "change=",
                item.get("c")
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
            item.get("c")
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
            item.get("c")
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
