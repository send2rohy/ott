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
COUPANG_URL = "https://www.coupangplay.com/"

RANKING_FILE = "ranking.json"
HISTORY_FILE = "history.json"

# 최근 30일만 저장
HISTORY_DAYS = 30


# Netflix TSV의 긴 필드 허용
csv.field_size_limit(sys.maxsize)


# =========================================================
# HTTP
# =========================================================

def fetch_text(url):

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/140.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8"
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
# 제목 정리
# =========================================================

def clean_title(title):

    title = re.sub(
        r"\s+",
        " ",
        title
    )

    return title.strip()


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
        if row.get("week")
        == latest_week
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

        # 시즌명이 제목과 다를 때만 저장
        if season and season != title:

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

    return {
        "week": latest_week,
        "movies": movies[:10],
        "tv": tv[:10]
    }


# =========================================================
# Disney+
# =========================================================

DISNEY_BAD_WORDS = [
    "로그인",
    "가입",
    "구독",
    "번들",
    "disney+",
    "디즈니+",
    "privacy",
    "terms",
    "help",
    "watch now",
    "sign up",
    "login",
    "bundle",
    "parental",
    "account"
]


def valid_disney_title(title):

    if not title:
        return False

    lower = title.lower()

    for word in DISNEY_BAD_WORDS:

        if word.lower() in lower:
            return False

    if "http://" in lower:
        return False

    if "https://" in lower:
        return False

    if len(title) < 2:
        return False

    if len(title) > 100:
        return False

    return True


def collect_disney():

    print("Disney+ 데이터 수집 중...")

    text = fetch_text(
        DISNEY_URL
    )

    candidates = re.findall(
        r">([^<>]{2,100})<",
        text
    )

    result = []
    seen = set()

    for raw in candidates:

        title = clean_title(raw)

        if not valid_disney_title(title):
            continue

        key = title.lower()

        if key in seen:
            continue

        seen.add(key)

        result.append({
            "r": len(result) + 1,
            "t": title
        })

        if len(result) >= 10:
            break

    print(
        "Disney+:",
        len(result)
    )

    return result


# =========================================================
# Coupang Play
# =========================================================

COUPANG_BAD_WORDS = [
    "히어로",
    "hero",
    "오토플레이",
    "autoplay",
    "티저",
    "teaser",
    "예고",
    "예고편",
    "트레일러",
    "trailer",
    "1차 티저",
    "2차 티저",
    "3차 티저",
    "1차 예고",
    "2차 예고",
    "3차 예고",
    "1차 예고편",
    "2차 예고편",
    "3차 예고편",
    "메인 예고",
    "메인 예고편",
    "official trailer",
    "official teaser"
]


def valid_coupang_title(title):

    if not title:
        return False

    lower = title.lower()

    for word in COUPANG_BAD_WORDS:

        if word.lower() in lower:
            return False

    if "http://" in lower:
        return False

    if "https://" in lower:
        return False

    if len(title) > 80:
        return False

    if title.startswith("{"):
        return False

    if title.startswith("["):
        return False

    return True


def collect_coupang():

    print(
        "Coupang Play 데이터 수집 중..."
    )

    text = fetch_text(
        COUPANG_URL
    )

    candidates = re.findall(
        r">([^<>]{2,80})<",
        text
    )

    result = []
    seen = set()

    for raw in candidates:

        title = clean_title(raw)

        if not valid_coupang_title(title):
            continue

        key = title.lower()

        if key in seen:
            continue

        seen.add(key)

        result.append({
            "r": len(result) + 1,
            "t": title
        })

        if len(result) >= 20:
            break

    print(
        "Coupang Play:",
        len(result)
    )

    return result


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

        "nm": rank_map(
            netflix.get(
                "movies",
                []
            )
        ),

        "nt": rank_map(
            netflix.get(
                "tv",
                []
            )
        ),

        "d": rank_map(
            data.get(
                "disney",
                []
            )
        ),

        "c": rank_map(
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
    # 기존 데이터
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

    # UTC → 한국시간
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
            rank_map(disney),

        "c":
            rank_map(coupang)
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

    # 최근 30일만
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
