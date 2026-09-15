import csv
import io
import json
import re
import subprocess
import urllib.request
from datetime import datetime, timezone


OUTPUT_FILE = "test_result.json"

NETFLIX_COUNTRIES_URL = (
    "https://www.netflix.com/tudum/top10/data/all-weeks-countries.tsv"
)

DISNEY_URL = "https://www.disneyplus.com/ko-kr"
COUPANG_URL = "https://www.coupangplay.com/catalog"


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7"
}


# =========================================================
# 공통
# =========================================================

def clean_title(title):
    if not title:
        return ""

    title = str(title)

    title = title.replace("\\u0026", "&")
    title = title.replace("\\/", "/")
    title = title.replace("&amp;", "&")
    title = title.replace("&quot;", '"')
    title = title.replace("&#39;", "'")

    title = re.sub(r"\s+", " ", title).strip()

    return title


def curl_page(url):
    cmd = [
        "curl",
        "-L",
        "--compressed",
        "--max-time",
        "60",
        "--retry",
        "3",
        "--retry-delay",
        "2",
        "-H",
        f"User-Agent: {HEADERS['User-Agent']}",
        "-H",
        f"Accept-Language: {HEADERS['Accept-Language']}",
        url
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore"
    )

    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.strip() or "curl failed"
        )

    return result.stdout


# =========================================================
# Netflix
# =========================================================

def download_netflix_tsv():

    request = urllib.request.Request(
        NETFLIX_COUNTRIES_URL,
        headers=HEADERS
    )

    with urllib.request.urlopen(
        request,
        timeout=120
    ) as response:

        data = response.read()

    return data.decode(
        "utf-8-sig",
        errors="replace"
    )


def collect_netflix():

    result = {
        "movies": [],
        "tv": [],
        "week": None,
        "error": None
    }

    try:

        print("Netflix 공식 TSV 다운로드 중...")

        text = download_netflix_tsv()

        reader = csv.DictReader(
            io.StringIO(text),
            delimiter="\t"
        )

        rows = []

        for row in reader:

            country = (
                row.get("country_iso2")
                or ""
            ).upper().strip()

            if country != "KR":
                continue

            week = (
                row.get("week")
                or ""
            ).strip()

            category = (
                row.get("category")
                or ""
            ).strip()

            rank = (
                row.get("weekly_rank")
                or ""
            ).strip()

            title = clean_title(
                row.get("show_title")
                or ""
            )

            season = clean_title(
                row.get("season_title")
                or ""
            )

            if not week:
                continue

            if not rank:
                continue

            if not title:
                continue

            try:
                rank_number = int(float(rank))
            except:
                continue

            rows.append({
                "week": week,
                "category": category,
                "rank": rank_number,
                "title": title,
                "season_title": season
            })

        if not rows:
            raise RuntimeError(
                "Netflix KR 데이터가 없습니다."
            )

        # 가장 최신 주간 찾기
        latest_week = max(
            row["week"]
            for row in rows
        )

        result["week"] = latest_week

        latest = [
            row
            for row in rows
            if row["week"] == latest_week
        ]

        # -------------------------------------------------
        # Films
        # -------------------------------------------------

        movies = [
            row
            for row in latest
            if row["category"].lower() == "films"
        ]

        movies.sort(
            key=lambda x: x["rank"]
        )

        for row in movies[:10]:

            result["movies"].append({
                "rank": row["rank"],
                "title": row["title"]
            })

        # -------------------------------------------------
        # TV
        # -------------------------------------------------

        tv = [
            row
            for row in latest
            if row["category"].lower() == "tv"
        ]

        tv.sort(
            key=lambda x: x["rank"]
        )

        for row in tv[:10]:

            title = row["title"]

            # 시즌명이 있으면 표시
            if row["season_title"]:
                if row["season_title"] not in title:
                    title = (
                        title
                        + ": "
                        + row["season_title"]
                    )

            result["tv"].append({
                "rank": row["rank"],
                "title": title
            })

        return result

    except Exception as e:

        result["error"] = str(e)

        return result


# =========================================================
# Disney+
# =========================================================

def extract_disney_titles(html):

    candidates = []

    patterns = [
        r'"title"\s*:\s*"([^"]+)"',
        r'"name"\s*:\s*"([^"]+)"',
        r'"contentTitle"\s*:\s*"([^"]+)"'
    ]

    for pattern in patterns:

        for match in re.finditer(
            pattern,
            html,
            re.I
        ):

            title = clean_title(
                match.group(1)
            )

            if title:
                candidates.append(title)

    result = []
    seen = set()

    for title in candidates:

        key = title.lower()

        # 메뉴 / 링크 / 내부 데이터 제거
        if key.startswith("nav link"):
            continue

        if key.startswith("link -"):
            continue

        if "login" in key:
            continue

        if "standalone" in key:
            continue

        if "bundle" in key:
            continue

        if "cancellation" in key:
            continue

        if "plan details" in key:
            continue

        if len(title) < 2:
            continue

        if len(title) > 150:
            continue

        if key in seen:
            continue

        seen.add(key)
        result.append(title)

    return result


def collect_disney():

    try:

        html = curl_page(
            DISNEY_URL
        )

        titles = extract_disney_titles(
            html
        )

        return {
            "items": [
                {
                    "rank": i + 1,
                    "title": title
                }
                for i, title in enumerate(
                    titles[:10]
                )
            ],
            "error": None
        }

    except Exception as e:

        return {
            "items": [],
            "error": str(e)
        }


# =========================================================
# Coupang Play
# =========================================================

def extract_coupang_titles(html):

    candidates = []

    patterns = [
        r'"title"\s*:\s*"([^"]+)"',
        r'"name"\s*:\s*"([^"]+)"',
        r'"programTitle"\s*:\s*"([^"]+)"'
    ]

    for pattern in patterns:

        for match in re.finditer(
            pattern,
            html,
            re.I
        ):

            title = clean_title(
                match.group(1)
            )

            if title:
                candidates.append(title)

    result = []
    seen = set()

    for title in candidates:

        key = title.lower()

        # 메뉴 / 내부 UI
        if key in {
            "coupang play",
            "home",
            "search",
            "login",
            "sign up",
            "top 20",
            "trending now",
            "hbo"
        }:
            continue

        # 히어로 / 오토플레이 / 티저 등
        lower = title.lower()

        if "히어로" in lower:
            continue

        if "오토" in lower:
            continue

        if "autoplay" in lower:
            continue

        if "hero" in lower:
            continue

        if "teaser" in lower:
            continue

        if "예고" in lower:
            continue

        if len(title) < 2:
            continue

        if len(title) > 150:
            continue

        if key in seen:
            continue

        seen.add(key)

        result.append(title)

    return result


def collect_coupang():

    try:

        html = curl_page(
            COUPANG_URL
        )

        titles = extract_coupang_titles(
            html
        )

        return {
            "items": [
                {
                    "rank": i + 1,
                    "title": title
                }
                for i, title in enumerate(
                    titles[:20]
                )
            ],
            "error": None
        }

    except Exception as e:

        return {
            "items": [],
            "error": str(e)
        }


# =========================================================
# MAIN
# =========================================================

def main():

    print()
    print("=" * 50)
    print("OTT COLLECTOR TEST")
    print("=" * 50)

    # Netflix
    print()
    print("[1] Netflix")

    netflix = collect_netflix()

    print(
        "Netflix Movies:",
        len(netflix["movies"])
    )

    print(
        "Netflix TV:",
        len(netflix["tv"])
    )

    print(
        "Netflix Week:",
        netflix["week"]
    )

    if netflix["error"]:
        print(
            "Netflix ERROR:",
            netflix["error"]
        )

    # Disney
    print()
    print("[2] Disney+")

    disney = collect_disney()

    print(
        "Disney+:",
        len(disney["items"])
    )

    if disney["error"]:
        print(
            "Disney ERROR:",
            disney["error"]
        )

    # Coupang
    print()
    print("[3] Coupang Play")

    coupang = collect_coupang()

    print(
        "Coupang Play:",
        len(coupang["items"])
    )

    if coupang["error"]:
        print(
            "Coupang ERROR:",
            coupang["error"]
        )

    # 저장
    data = {

        "collected_at":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "netflix": netflix,

        "disney_plus": disney,

        "coupang_play": coupang
    }

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )

    print()
    print("=" * 50)
    print("RESULT SAVED")
    print("=" * 50)
    print(OUTPUT_FILE)


if __name__ == "__main__":
    main()
