import json
import re
import subprocess
from datetime import datetime, timezone


OUTPUT_FILE = "test_result.json"


# =========================================================
# 공통
# =========================================================

def fetch_with_curl(url):
    """
    GitHub Actions에 설치되어 있는 curl을 이용한다.
    urllib의 IncompleteRead 문제를 피하기 위한 방식이다.
    """

    print()
    print("GET:", url)

    result = subprocess.run(
        [
            "curl",
            "-L",
            "--compressed",
            "--silent",
            "--show-error",
            "--retry",
            "3",
            "--retry-delay",
            "2",
            "--max-time",
            "60",
            "-A",
            (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/140.0.0.0 Safari/537.36"
            ),
            "-H",
            "Accept-Language: ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            url
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore"
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"curl failed: {result.stderr.strip()}"
        )

    html = result.stdout

    if not html:
        raise RuntimeError("빈 응답")

    print(
        "응답 크기:",
        f"{len(html):,}",
        "characters"
    )

    return html


def clean_text(text):

    if not text:
        return ""

    text = (
        text
        .replace("\\u0026", "&")
        .replace("\\/", "/")
        .replace("&amp;", "&")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("&apos;", "'")
    )

    text = re.sub(r"\s+", " ", text)

    return text.strip()


def save_json(data):

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


# =========================================================
# Netflix
# =========================================================

def collect_netflix(url, category):

    print()
    print("=" * 60)
    print("NETFLIX:", category)
    print("=" * 60)

    html = fetch_with_curl(url)

    items = []

    # -----------------------------------------------------
    # 공식 Netflix Top 10 Overview
    #
    # 01Image[Button: 제목]
    # 02Image[Button: 제목]
    #
    # 형태를 직접 추출한다.
    # -----------------------------------------------------

    pattern = re.compile(
        r"(\d{1,2})\s*"
        r"(?:Image)?"
        r"\s*\[Button:\s*"
        r"([^\]]+?)"
        r"\]",
        re.IGNORECASE
    )

    matches = pattern.findall(html)

    for rank_text, title in matches:

        try:
            rank = int(rank_text)
        except ValueError:
            continue

        if rank < 1 or rank > 10:
            continue

        title = clean_text(title)

        if not title:
            continue

        # Netflix 페이지의 일반 버튼은 제외
        bad = {
            "my list",
            "watch",
            "explore",
            "more details",
            "top 10 search",
        }

        if title.lower() in bad:
            continue

        # 동일 순위 중복 방지
        exists = False

        for item in items:

            if item["rank"] == rank:
                exists = True
                break

        if exists:
            continue

        items.append({
            "rank": rank,
            "title": title
        })

    items.sort(
        key=lambda x: x["rank"]
    )

    items = items[:10]

    print()
    print(
        f"Netflix {category}: "
        f"{len(items)}개"
    )

    for item in items:

        print(
            f"{item['rank']:2d}. "
            f"{item['title']}"
        )

    return {
        "service": "Netflix",
        "category": category,
        "source": url,
        "items": items
    }


def collect_netflix_all():

    movies_url = (
        "https://www.netflix.com/"
        "tudum/top10/south-korea"
    )

    tv_url = (
        "https://www.netflix.com/"
        "tudum/top10/south-korea/tv"
    )

    return {

        "movies": collect_netflix(
            movies_url,
            "영화"
        ),

        "tv": collect_netflix(
            tv_url,
            "TV"
        )
    }


# =========================================================
# Disney+
# =========================================================

def is_bad_disney_title(title):

    lower = title.lower()

    bad_patterns = [

        "nav link",
        "link -",
        "cta",
        "bundle",
        "standalone",
        "view all",
        "learn more",
        "cancellation",
        "refund",
        "legal disclaimer",
        "/identity/",
        "/commerce/",
        "official",
        "terms and conditions",
        "login",
        "sign up",
        "subscribe",
        "watch now",
    ]

    for pattern in bad_patterns:

        if pattern in lower:
            return True

    return False


def collect_disney():

    url = "https://www.disneyplus.com/ko-kr"

    print()
    print("=" * 60)
    print("DISNEY+")
    print("=" * 60)

    html = fetch_with_curl(url)

    candidates = []

    # -----------------------------------------------------
    # JSON title/name
    # -----------------------------------------------------

    patterns = [

        r'"title"\s*:\s*"([^"]{2,180})"',

        r'"name"\s*:\s*"([^"]{2,180})"',

        r'"displayName"\s*:\s*"([^"]{2,180})"',

    ]

    for pattern in patterns:

        matches = re.findall(
            pattern,
            html,
            re.IGNORECASE
        )

        for title in matches:

            title = clean_text(title)

            if not title:
                continue

            if is_bad_disney_title(title):
                continue

            candidates.append(title)

    # -----------------------------------------------------
    # img alt/title
    # -----------------------------------------------------

    patterns = [

        r'<img[^>]+alt=["\']([^"\']{2,180})["\']',

        r'<img[^>]+title=["\']([^"\']{2,180})["\']',

    ]

    for pattern in patterns:

        matches = re.findall(
            pattern,
            html,
            re.IGNORECASE
        )

        for title in matches:

            title = clean_text(title)

            if not title:
                continue

            if is_bad_disney_title(title):
                continue

            candidates.append(title)

    # -----------------------------------------------------
    # 중복 제거
    # -----------------------------------------------------

    unique = []
    seen = set()

    for title in candidates:

        key = title.lower()

        if key in seen:
            continue

        seen.add(key)

        unique.append(title)

    # -----------------------------------------------------
    # 명백한 메뉴 제거
    # -----------------------------------------------------

    bad_exact = {
        "home",
        "search",
        "movies",
        "series",
        "shows",
        "login",
        "sign up",
        "subscribe",
        "watch now",
        "learn more",
        "disney+",
    }

    filtered = []

    for title in unique:

        if title.lower() in bad_exact:
            continue

        if len(title) < 2:
            continue

        filtered.append(title)

    items = []

    for title in filtered[:10]:

        items.append({
            "rank": len(items) + 1,
            "title": title
        })

    print()
    print(
        f"Disney+: {len(items)}개"
    )

    for item in items:

        print(
            f"{item['rank']:2d}. "
            f"{item['title']}"
        )

    return {

        "service": "Disney+",

        "category": "한국 TOP 10",

        "source": url,

        "items": items
    }


# =========================================================
# Coupang Play
# =========================================================

def is_bad_coupang_title(title):

    lower = title.lower()

    bad_patterns = [

        "모바일히어로",
        "오토플레이",
        "오토",
        "모바일",
        "트레일러",
        "티저",
        "예고",
        "히어로",
        "trailer",
        "preview",
        "mobile hero",
        "autoplay",
        "hero",

    ]

    for pattern in bad_patterns:

        if pattern.lower() in lower:
            return True

    return False


def normalize_coupang_title(title):

    title = clean_text(title)

    # -----------------------------------------------------
    # 끝에 붙는 파생 콘텐츠 표시 제거
    # -----------------------------------------------------

    suffixes = [

        "_히어로",
        "_트레일러",
        "_티저",
        "_예고",
        " 히어로",
        " 트레일러",
        " 티저",
        " 예고",

    ]

    changed = True

    while changed:

        changed = False

        for suffix in suffixes:

            if title.endswith(suffix):

                title = title[
                    :-len(suffix)
                ].strip()

                changed = True

    return title


def collect_coupang():

    url = (
        "https://www.coupangplay.com/catalog"
    )

    print()
    print("=" * 60)
    print("COUPANG PLAY")
    print("=" * 60)

    html = fetch_with_curl(url)

    candidates = []

    # -----------------------------------------------------
    # JSON
    # -----------------------------------------------------

    patterns = [

        r'"title"\s*:\s*"([^"]{2,180})"',

        r'"name"\s*:\s*"([^"]{2,180})"',

        r'"displayName"\s*:\s*"([^"]{2,180})"',

        r'"programName"\s*:\s*"([^"]{2,180})"',

    ]

    for pattern in patterns:

        matches = re.findall(
            pattern,
            html,
            re.IGNORECASE
        )

        for title in matches:

            title = clean_text(title)

            if not title:
                continue

            if is_bad_coupang_title(title):
                continue

            candidates.append(title)

    # -----------------------------------------------------
    # 이미지 alt/title
    # -----------------------------------------------------

    patterns = [

        r'<img[^>]+alt=["\']([^"\']{2,180})["\']',

        r'<img[^>]+title=["\']([^"\']{2,180})["\']',

    ]

    for pattern in patterns:

        matches = re.findall(
            pattern,
            html,
            re.IGNORECASE
        )

        for title in matches:

            title = clean_text(title)

            if not title:
                continue

            if is_bad_coupang_title(title):
                continue

            candidates.append(title)

    # -----------------------------------------------------
    # 작품명 정규화
    # -----------------------------------------------------

    normalized = []

    seen = set()

    for title in candidates:

        title = normalize_coupang_title(
            title
        )

        if not title:
            continue

        key = title.lower()

        if key in seen:
            continue

        seen.add(key)

        normalized.append(title)

    # -----------------------------------------------------
    # HBO 같은 카테고리/브랜드 제거
    # -----------------------------------------------------

    bad_exact = {
        "hbo",
        "coupang play",
        "쿠팡플레이",
    }

    filtered = []

    for title in normalized:

        if title.lower() in bad_exact:
            continue

        filtered.append(title)

    # -----------------------------------------------------
    # TOP 20
    # -----------------------------------------------------

    items = []

    for title in filtered[:20]:

        items.append({
            "rank": len(items) + 1,
            "title": title
        })

    print()
    print(
        f"Coupang Play: {len(items)}개"
    )

    for item in items:

        print(
            f"{item['rank']:2d}. "
            f"{item['title']}"
        )

    return {

        "service": "Coupang Play",

        "category": "이번 주 TOP 20",

        "source": url,

        "items": items
    }


# =========================================================
# MAIN
# =========================================================

def main():

    collected_at = (
        datetime.now(timezone.utc)
        .isoformat()
    )

    print()
    print("=" * 60)
    print("OTT RANKING COLLECTOR")
    print("=" * 60)

    print(
        "Collected:",
        collected_at
    )

    result = {

        "collectedAt": collected_at,

        "country": "KR",

        "services": {}

    }

    # -----------------------------------------------------
    # Netflix
    # -----------------------------------------------------

    try:

        result["services"]["netflix"] = (
            collect_netflix_all()
        )

    except Exception as e:

        print()
        print(
            "Netflix ERROR:",
            type(e).__name__,
            str(e)
        )

        result["services"]["netflix"] = {
            "error": str(e)
        }

    # -----------------------------------------------------
    # Disney+
    # -----------------------------------------------------

    try:

        result["services"]["disneyplus"] = (
            collect_disney()
        )

    except Exception as e:

        print()
        print(
            "Disney+ ERROR:",
            type(e).__name__,
            str(e)
        )

        result["services"]["disneyplus"] = {
            "error": str(e)
        }

    # -----------------------------------------------------
    # Coupang Play
    # -----------------------------------------------------

    try:

        result["services"]["coupangplay"] = (
            collect_coupang()
        )

    except Exception as e:

        print()
        print(
            "Coupang Play ERROR:",
            type(e).__name__,
            str(e)
        )

        result["services"]["coupangplay"] = {
            "error": str(e)
        }

    # -----------------------------------------------------
    # 저장
    # -----------------------------------------------------

    save_json(result)

    print()
    print("=" * 60)
    print("저장 완료:", OUTPUT_FILE)
    print("=" * 60)


if __name__ == "__main__":
    main()
