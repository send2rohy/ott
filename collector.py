import csv
import io
import json
import re
import urllib.request
from datetime import datetime, timezone, timedelta


# =========================================================
# 기본 설정
# =========================================================

NETFLIX_TSV_URL = (
    "https://www.netflix.com/tudum/top10/data/all-weeks-countries.tsv"
)

RANKING_FILE = "ranking.json"
HISTORY_FILE = "history.json"

HISTORY_DAYS = 30

KST = timezone(timedelta(hours=9))


# =========================================================
# 공통 HTTP
# =========================================================

def fetch_text(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "Chrome/140 Safari/537.36"
            ),
            "Accept": "*/*",
        },
    )

    with urllib.request.urlopen(req, timeout=60) as response:
        data = response.read()

    return data.decode("utf-8-sig", errors="replace")


# =========================================================
# Netflix
# =========================================================

def collect_netflix():
    text = fetch_text(NETFLIX_TSV_URL)

    reader = csv.DictReader(io.StringIO(text), delimiter="\t")

    rows = []

    for row in reader:
        if row.get("country_iso2", "").upper() != "KR":
            continue

        rows.append(row)

    if not rows:
        raise RuntimeError("Netflix Korea 데이터를 찾지 못했습니다.")

    weeks = sorted(
        {
            row.get("week", "")
            for row in rows
            if row.get("week")
        }
    )

    if not weeks:
        raise RuntimeError("Netflix 주간 데이터를 찾지 못했습니다.")

    latest_week = weeks[-1]

    latest = [
        row
        for row in rows
        if row.get("week") == latest_week
    ]

    movies = []
    tv = []

    for row in latest:
        category = row.get("category", "").lower()

        try:
            rank = int(row.get("weekly_rank", "0"))
        except ValueError:
            continue

        title = (row.get("show_title") or "").strip()
        season = (row.get("season_title") or "").strip()

        if not title or rank <= 0:
            continue

        item = {
            "r": rank,
            "t": title
        }

        # 시즌 정보는 필요할 때 사용할 수 있도록 저장
        # 단, 화면 제목에는 중복 표시하지 않음
        if season and season != title:
            item["s"] = season

        if category == "films":
            movies.append(item)

        elif category == "tv":
            tv.append(item)

    movies.sort(key=lambda x: x["r"])
    tv.sort(key=lambda x: x["r"])

    return {
        "week": latest_week,
        "movies": movies[:10],
        "tv": tv[:10]
    }


# =========================================================
# Disney+
# =========================================================

DISNEY_URL = "https://www.disneyplus.com/ko-kr"

DISNEY_BAD_WORDS = [
    "로그인",
    "가입",
    "구독",
    "번들",
    "디즈니+",
    "disney+",
    "privacy",
    "terms",
    "help",
    "watch now",
    "sign up",
    "login",
    "bundle",
    "parental",
    "originals",
]


def clean_title(title):
    title = re.sub(r"\s+", " ", title).strip()
    return title


def is_valid_disney_title(title):
    if not title:
        return False

    lower = title.lower()

    for word in DISNEY_BAD_WORDS:
        if word.lower() in lower:
            return False

    if len(title) < 2:
        return False

    if len(title) > 100:
        return False

    return True


def collect_disney():
    text = fetch_text(DISNEY_URL)

    # 페이지에서 제목처럼 보이는 텍스트 추출
    candidates = re.findall(
        r'>([^<>]{2,100})<',
        text
    )

    result = []
    seen = set()

    for raw in candidates:
        title = clean_title(raw)

        if not is_valid_disney_title(title):
            continue

        # URL / HTML 관련 문자열 제거
        if "http://" in title.lower():
            continue

        if "https://" in title.lower():
            continue

        if "/" in title and len(title) > 30:
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

    return result


# =========================================================
# Coupang Play
# =========================================================

COUPANG_URL = "https://www.coupangplay.com/"

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
    "1차 예고편",
    "2차 예고편",
    "메인 예고",
    "official trailer",
    "official teaser",
]


def is_valid_coupang_title(title):
    if not title:
        return False

    lower = title.lower()

    for word in COUPANG_BAD_WORDS:
        if word.lower() in lower:
            return False

    # 너무 긴 문장은 메뉴/설명문일 가능성이 높음
    if len(title) > 80:
        return False

    # URL 제거
    if "http://" in lower or "https://" in lower:
        return False

    return True


def collect_coupang():
    text = fetch_text(COUPANG_URL)

    candidates = re.findall(
        r'>([^<>]{2,80})<',
        text
    )

    result = []
    seen = set()

    for raw in candidates:
        title = clean_title(raw)

        if not is_valid_coupang_title(title):
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

    return result


# =========================================================
# 기존 데이터 읽기
# =========================================================

def load_json(filename, default):
    try:
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


# =========================================================
# 순위만 추출
# =========================================================

def rank_map(items):
    result = {}

    for item in items:
        title = item.get("t")

        if title:
            result[title] = item.get("r")

    return result


def make_rank_maps(data):
    netflix = data.get("netflix", {})
    disney = data.get("disney", [])
    coupang = data.get("coupang", [])

    return {
        "nm": rank_map(netflix.get("movies", [])),
        "nt": rank_map(netflix.get("tv", [])),
        "d": rank_map(disney),
        "c": rank_map(coupang)
    }


# =========================================================
# 변동 계산
# =========================================================

def add_change(current_items, previous_map):
    result = []

    for item in current_items:
        title = item["t"]
        current_rank = item["r"]

        old_rank = previous_map.get(title)

        new_item = dict(item)

        if old_rank is None:
            new_item["c"] = "NEW"

        else:
            diff = old_rank - current_rank

            if diff > 0:
                new_item["c"] = diff

            elif diff < 0:
                new_item["c"] = diff

            else:
                new_item["c"] = 0

        result.append(new_item)

    return result


# =========================================================
# 메인
# =========================================================

def main():
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    print("OTT 데이터 수집 시작")

    # -----------------------------------------------------
    # 수집
    # -----------------------------------------------------

    netflix = collect_netflix()
    disney = collect_disney()
    coupang = collect_coupang()

    current = {
        "netflix": netflix,
        "disney": disney,
        "coupang": coupang
    }

    print(
        "Netflix:",
        len(netflix["movies"]),
        "movies /",
        len(netflix["tv"]),
        "TV"
    )

    print("Disney+:", len(disney))
    print("Coupang Play:", len(coupang))

    # -----------------------------------------------------
    # 기존 ranking
    # -----------------------------------------------------

    old_ranking = load_json(
        RANKING_FILE,
        {}
    )

    previous_maps = make_rank_maps(old_ranking)

    # -----------------------------------------------------
    # 현재 순위 + 변동
    # -----------------------------------------------------

    netflix_movies = add_change(
        netflix["movies"],
        previous_maps["nm"]
    )

    netflix_tv = add_change(
        netflix["tv"],
        previous_maps["nt"]
    )

    disney_changed = add_change(
        disney,
        previous_maps["d"]
    )

    coupang_changed = add_change(
        coupang,
        previous_maps["c"]
    )

    ranking = {
        "updated_at": now_iso,

        "netflix": {
            "week": netflix["week"],
            "movies": netflix_movies,
            "tv": netflix_tv
        },

        "disney": disney_changed,

        "coupang": coupang_changed
    }

    # -----------------------------------------------------
    # ranking.json 저장
    # -----------------------------------------------------

    with open(
        RANKING_FILE,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            ranking,
            f,
            ensure_ascii=False,
            separators=(",", ":")
        )

    # -----------------------------------------------------
    # history.json
    # -----------------------------------------------------

    history = load_json(
        HISTORY_FILE,
        {"h": []}
    )

    snapshots = history.get("h", [])

    snapshot = {
        "d": now.strftime("%Y-%m-%d"),

        "n": {
            "m": rank_map(netflix["movies"]),
            "t": rank_map(netflix["tv"])
        },

        "d+": rank_map(disney),

        "c": rank_map(coupang)
    }

    # 같은 날짜가 있으면 교체
    snapshots = [
        item
        for item in snapshots
        if item.get("d") != snapshot["d"]
    ]

    snapshots.append(snapshot)

    # 최근 30일만 유지
    snapshots.sort(
        key=lambda x: x.get("d", ""),
        reverse=True
    )

    snapshots = snapshots[:HISTORY_DAYS]

    snapshots.sort(
        key=lambda x: x.get("d", "")
    )

    history = {
        "h": snapshots
    }

    with open(
        HISTORY_FILE,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            history,
            f,
            ensure_ascii=False,
            separators=(",", ":")
        )

    print("================================")
    print("OTT 수집 완료")
    print("================================")
    print("Netflix week:", netflix["week"])
    print("Netflix movies:", len(netflix["movies"]))
    print("Netflix TV:", len(netflix["tv"]))
    print("Disney+:", len(disney))
    print("Coupang Play:", len(coupang))
    print("History:", len(snapshots), "days")
    print("================================")


if __name__ == "__main__":
    main()
