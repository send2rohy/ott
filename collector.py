
import csv
import io
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone, timedelta


# =========================================================
# 설정
# =========================================================

NETFLIX_TSV_URL = (
    "https://www.netflix.com/tudum/top10/data/all-weeks-countries.tsv"
)

DISNEY_URL = "https://www.disneyplus.com/ko-kr"

COUPANG_URL = "https://www.coupangplay.com/catalog"

RANKING_FILE = "ranking.json"
HISTORY_FILE = "history.json"

HISTORY_DAYS = 30

csv.field_size_limit(sys.maxsize)


# =========================================================
# HTTP
# =========================================================

USER_AGENT = (
    "Mozilla/5.0 "
    "(Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 "
    "(KHTML, like Gecko) "
    "Chrome/140.0.0.0 Safari/537.36"
)


def fetch_text(url):

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
        }
    )

    with urllib.request.urlopen(
        request,
        timeout=60
    ) as response:

        data = response.read()

    return data.decode(
        "utf-8-sig",
        errors="replace"
    )


# =========================================================
# 공통
# =========================================================

def clean_title(title):

    if not title:
        return ""

    title = re.sub(
        r"\s+",
        " ",
        title
    )

    return title.strip()


def normalize_key(title):

    return re.sub(
        r"\s+",
        " ",
        title.lower().strip()
    )


# =========================================================
# Netflix
# =========================================================

def collect_netflix():

    print("Netflix 데이터 수집 중...")

    text = fetch_text(
        NETFLIX_TSV_URL
    )

    reader = csv.DictReader(
        io.StringIO(text),
        delimiter="\t"
    )

    rows = []

    for row in reader:

        if (
            row.get(
                "country_iso2",
                ""
            ).upper()
            != "KR"
        ):
            continue

        rows.append(row)

    if not rows:

        raise RuntimeError(
            "Netflix Korea 데이터를 찾지 못했습니다."
        )

    weeks = sorted(
        {
            row.get("week", "")
            for row in rows
            if row.get("week")
        }
    )

    if not weeks:

        raise RuntimeError(
            "Netflix 주간 데이터를 찾지 못했습니다."
        )

    latest_week = weeks[-1]

    print(
        "Netflix 최신 주:",
        latest_week
    )

    latest = [
        row
        for row in rows
        if row.get("week") == latest_week
    ]

    movies = []
    tv = []

    for row in latest:

        category = (
            row.get(
                "category",
                ""
            )
            .strip()
            .lower()
        )

        try:

            rank = int(
                row.get(
                    "weekly_rank",
                    "0"
                )
            )

        except ValueError:

            continue

        title = clean_title(
            row.get(
                "show_title",
                ""
            )
        )

        season = clean_title(
            row.get(
                "season_title",
                ""
            )
        )

        if not title:
            continue

        if rank <= 0:
            continue

        item = {
            "r": rank,
            "t": title
        }

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

    movies.sort(
        key=lambda x: x["r"]
    )

    tv.sort(
        key=lambda x: x["r"]
    )

    if len(movies) < 5:

        raise RuntimeError(
            "Netflix 영화 데이터가 비정상적으로 적습니다."
        )

    if len(tv) < 5:

        raise RuntimeError(
            "Netflix TV 데이터가 비정상적으로 적습니다."
        )

    return {
        "week": latest_week,
        "movies": movies[:10],
        "tv": tv[:10]
    }


# =========================================================
# Disney+
# =========================================================

DISNEY_BAD_WORDS = [

    # 사이트 / 시스템
    "window.location",
    "/unsupported",

    # 계정 / 메뉴
    "로그인",
    "가입",
    "구독",
    "번들",
    "privacy",
    "terms",
    "help",
    "watch now",
    "sign up",
    "login",
    "parental",
    "account",

    # TOP 영역 제목 자체
    "오늘 한국의 TOP 10",

    # 내부 링크
    "link -",
    "bundle & save",
    "view all plan details",
    "cancellation and refund",
    "legal disclaimer",
    "tving bundle",
    "cta",

    # 장르
    "action and adventure",
    "science fiction",
    "drama",
    "comedy",
    "thriller",
    "crime",

    "어드벤처",
    "액션",
    "코미디",
    "드라마",
    "스릴러",
    "범죄",
    "호러",
    "로맨스",
    "리얼리티",
]


def valid_disney_title(title):

    if not title:
        return False

    title = clean_title(title)

    lower = title.lower()

    if len(title) < 2:
        return False

    if len(title) > 100:
        return False

    for word in DISNEY_BAD_WORDS:

        if word.lower() in lower:
            return False

    if "http://" in lower:
        return False

    if "https://" in lower:
        return False

    # 연도만 있는 경우
    if re.fullmatch(
        r"(19|20)\d{2}",
        title
    ):
        return False

    # 장르 묶음
    if title.count(",") >= 2:
        return False

    return True


def extract_disney_candidates(text):

    candidates = []

    patterns = [

        r'"title"\s*:\s*"([^"]{2,120})"',

        r'"name"\s*:\s*"([^"]{2,120})"',

        r'"displayName"\s*:\s*"([^"]{2,120})"',

        r'"localizedTitle"\s*:\s*"([^"]{2,120})"',

        r'"contentTitle"\s*:\s*"([^"]{2,120})"',

    ]

    for pattern in patterns:

        for match in re.finditer(
            pattern,
            text,
            flags=re.I
        ):

            candidates.append(
                match.group(1)
            )

    # 이미지 alt
    for match in re.finditer(
        r'<img[^>]+alt=["\']([^"\']{2,120})["\']',
        text,
        flags=re.I
    ):

        candidates.append(
            match.group(1)
        )

    # aria-label
    for match in re.finditer(
        r'aria-label=["\']([^"\']{2,120})["\']',
        text,
        flags=re.I
    ):

        candidates.append(
            match.group(1)
        )

    return candidates


def collect_disney():

    print(
        "Disney+ 데이터 수집 중..."
    )

    text = fetch_text(
        DISNEY_URL
    )

    candidates = extract_disney_candidates(
        text
    )

    result = []
    seen = set()

    for raw in candidates:

        # JSON escape
        title = raw.replace(
            "\\u0026",
            "&"
        )

        title = clean_title(title)

        if not valid_disney_title(title):
            continue

        key = normalize_key(title)

        if key in seen:
            continue

        seen.add(key)

        result.append({
            "r": len(result) + 1,
            "t": title
        })

        if len(result) >= 10:
            break

    if len(result) < 5:

        raise RuntimeError(
            "Disney+ TOP 10을 정상적으로 찾지 못했습니다."
        )

    print(
        "Disney+:",
        len(result)
    )

    for item in result:

        print(
            item["r"],
            item["t"]
        )

    return result[:10]


# =========================================================
# Coupang Play
# =========================================================

COUPANG_BAD_WORDS = [

    # 사이트 / 푸터
    "쿠팡플레이",
    "coupang play",
    "coupangplay",

    "쿠팡 계정",
    "쿠팡 시작하기",
    "시작하기",

    "광고 문의",
    "제휴 문의",

    "자주 묻는 질문",

    "개인정보 처리방침",
    "쿠팡 이용 약관",
    "와우 멤버십 서비스 이용 약관",
    "쿠팡플레이 이용 기준",
    "쿠팡플레이 유료서비스 이용 약관",

    "버전:",

    "playrepresent@",

    "사업자 등록번호",
    "대표이사",

    "sorry, coupang play is not available",
    "not available in your region",

    "window.location",

    # UI
    "next",
    "arrow-icon",

    # 프로모션 / 예고편
    "오토플레이",
    "autoplay",
    "히어로",
    "hero",
    "티저",
    "teaser",
    "예고",
    "예고편",
    "트레일러",
    "trailer",
    "official trailer",
    "official teaser",
]


def valid_coupang_title(title):

    if not title:
        return False

    title = clean_title(title)

    lower = title.lower()

    if len(title) < 2:
        return False

    if len(title) > 120:
        return False

    for word in COUPANG_BAD_WORDS:

        if word.lower() in lower:
            return False

    if "http://" in lower:
        return False

    if "https://" in lower:
        return False

    if title.startswith("{"):
        return False

    if title.startswith("["):
        return False

    if re.fullmatch(
        r"\d+(\.\d+)?",
        title
    ):
        return False

    if re.fullmatch(
        r"(19|20)\d{2}",
        title
    ):
        return False

    return True


def extract_coupang_section(text):

    markers = [

        "이번 주 TOP 20",

        "이번 주 TOP20",

        "이번주 TOP 20",

        "이번주 TOP20",

    ]

    position = -1

    for marker in markers:

        position = text.find(marker)

        if position >= 0:
            break

    if position < 0:

        raise RuntimeError(
            "쿠팡플레이 '이번 주 TOP 20' 영역을 찾지 못했습니다."
        )

    start = max(
        0,
        position - 20000
    )

    end = min(
        len(text),
        position + 100000
    )

    return text[start:end]


def extract_coupang_candidates(section):

    candidates = []

    patterns = [

        r'"title"\s*:\s*"([^"]{2,120})"',

        r'"name"\s*:\s*"([^"]{2,120})"',

        r'"displayName"\s*:\s*"([^"]{2,120})"',

        r'"contentTitle"\s*:\s*"([^"]{2,120})"',

    ]

    for pattern in patterns:

        for match in re.finditer(
            pattern,
            section,
            flags=re.I
        ):

            candidates.append(
                match.group(1)
            )

    # 이미지 alt
    for match in re.finditer(
        r'<img[^>]+alt=["\']([^"\']{2,120})["\']',
        section,
        flags=re.I
    ):

        candidates.append(
            match.group(1)
        )

    # aria-label
    for match in re.finditer(
        r'aria-label=["\']([^"\']{2,120})["\']',
        section,
        flags=re.I
    ):

        candidates.append(
            match.group(1)
        )

    return candidates


def collect_coupang():

    print(
        "Coupang Play 데이터 수집 중..."
    )

    text = fetch_text(
        COUPANG_URL
    )

    section = extract_coupang_section(
        text
    )

    candidates = extract_coupang_candidates(
        section
    )

    result = []
    seen = set()

    for raw in candidates:

        title = clean_title(raw)

        if not valid_coupang_title(title):
            continue

        key = normalize_key(title)

        if key in seen:
            continue

        seen.add(key)

        result.append({
            "r": len(result) + 1,
            "t": title
        })

        if len(result) >= 20:
            break

    if len(result) < 5:

        raise RuntimeError(
            "쿠팡플레이 이번 주 TOP 20을 정상적으로 찾지 못했습니다."
        )

    print(
        "Coupang Play:",
        len(result)
    )

    for item in result:

        print(
            item["r"],
            item["t"]
        )

    return result[:20]


# =========================================================
# JSON 읽기
# =========================================================

def load_json(
    filename,
    default
):

    try:

        with open(
            filename,
            "r",
            encoding="utf-8"
        ) as file:

            return json.load(file)

    except Exception:

        return default


# =========================================================
# 순위 맵
# =========================================================

def rank_map(items):

    result = {}

    for item in items:

        title = item.get("t")

        if title:

            result[title] = item.get("r")

    return result


def make_previous_maps(data):

    netflix = data.get(
        "netflix",
        {}
    )

    return {

        "nm":
            rank_map(
                netflix.get(
                    "movies",
                    []
                )
            ),

        "nt":
            rank_map(
                netflix.get(
                    "tv",
                    []
                )
            ),

        "d":
            rank_map(
                data.get(
                    "disney",
                    []
                )
            ),

        "c":
            rank_map(
                data.get(
                    "coupang",
                    []
                )
            )
    }


# =========================================================
# 순위 변동
#
# NEW = 신규 진입
# 양수 = 상승
# 음수 = 하락
# 0 = 동일
# =========================================================

def add_change(
    items,
    previous
):

    result = []

    for item in items:

        title = item["t"]

        current_rank = item["r"]

        old_rank = previous.get(
            title
        )

        new_item = dict(item)

        if old_rank is None:

            new_item["c"] = "NEW"

        else:

            change = (
                old_rank
                - current_rank
            )

            new_item["c"] = change

        result.append(
            new_item
        )

    return result


# =========================================================
# 메인
# =========================================================

def main():

    now = datetime.now(
        timezone.utc
    )

    print("")
    print("==============================")
    print("OTT 데이터 수집 시작")
    print("==============================")

    # -----------------------------------------------------
    # 수집
    # -----------------------------------------------------

    netflix = collect_netflix()

    disney = collect_disney()

    coupang = collect_coupang()

    # -----------------------------------------------------
    # 기존 ranking
    # -----------------------------------------------------

    old_ranking = load_json(
        RANKING_FILE,
        {}
    )

    previous = make_previous_maps(
        old_ranking
    )

    # -----------------------------------------------------
    # 변동 계산
    # -----------------------------------------------------

    netflix_movies = add_change(
        netflix["movies"],
        previous["nm"]
    )

    netflix_tv = add_change(
        netflix["tv"],
        previous["nt"]
    )

    disney_items = add_change(
        disney,
        previous["d"]
    )

    coupang_items = add_change(
        coupang,
        previous["c"]
    )

    # -----------------------------------------------------
    # ranking.json
    # -----------------------------------------------------

    ranking = {

        "updated_at":
            now.isoformat(),

        "netflix": {

            "week":
                netflix["week"],

            "movies":
                netflix_movies,

            "tv":
                netflix_tv
        },

        "disney":
            disney_items,

        "coupang":
            coupang_items
    }

    with open(
        RANKING_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            ranking,
            file,
            ensure_ascii=False,
            separators=(
                ",",
                ":"
            )
        )

    # -----------------------------------------------------
    # history.json
    # -----------------------------------------------------

    history = load_json(
        HISTORY_FILE,
        {"h": []}
    )

    snapshots = history.get(
        "h",
        []
    )

    kst = now + timedelta(
        hours=9
    )

    today = kst.strftime(
        "%Y-%m-%d"
    )

    snapshot = {

        "d": today,

        "n": {

            "m":
                rank_map(
                    netflix["movies"]
                ),

            "t":
                rank_map(
                    netflix["tv"]
                )
        },

        "d+":
            rank_map(
                disney
            ),

        "c":
            rank_map(
                coupang
            )
    }

    # 같은 날짜 데이터 제거
    snapshots = [
        item
        for item in snapshots
        if item.get("d") != today
    ]

    snapshots.append(
        snapshot
    )

    # 날짜순 정렬
    snapshots.sort(
        key=lambda x:
        x.get("d", "")
    )

    # 최근 30일
    snapshots = snapshots[
        -HISTORY_DAYS:
    ]

    history = {
        "h": snapshots
    }

    with open(
        HISTORY_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            history,
            file,
            ensure_ascii=False,
            separators=(
                ",",
                ":"
            )
        )

    # -----------------------------------------------------
    # 결과
    # -----------------------------------------------------

    print("")
    print("==============================")
    print("OTT 수집 완료")
    print("==============================")

    print(
        "Netflix week:",
        netflix["week"]
    )

    print(
        "Netflix movies:",
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

    print(
        "History:",
        len(snapshots),
        "days"
    )

    print("==============================")


# =========================================================
# 실행
# =========================================================

if __name__ == "__main__":
    main()
