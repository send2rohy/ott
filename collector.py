import json
import re
import time
import urllib.request
from datetime import datetime, timezone


# =========================================================
# OTT Ranking Collector
# Netflix / Disney+ / Coupang Play
# =========================================================

OUTPUT_FILE = "test_result.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Connection": "close",
}


# =========================================================
# 공통 함수
# =========================================================

def fetch_url(url, timeout=60, retries=3):

    last_error = None

    for attempt in range(1, retries + 1):

        try:

            print(f"요청 {attempt}/{retries}: {url}")

            req = urllib.request.Request(
                url,
                headers=HEADERS
            )

            with urllib.request.urlopen(
                req,
                timeout=timeout
            ) as response:

                chunks = []

                while True:

                    chunk = response.read(65536)

                    if not chunk:
                        break

                    chunks.append(chunk)

                data = b"".join(chunks)

                print(
                    f"수신 완료: {len(data):,} bytes"
                )

                return data.decode(
                    "utf-8",
                    errors="ignore"
                )

        except Exception as e:

            last_error = e

            print(
                f"요청 실패: {type(e).__name__}: {e}"
            )

            if attempt < retries:
                time.sleep(3)

    raise last_error


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
    )

    text = re.sub(r"\s+", " ", text)

    return text.strip()


def unique_items(items):

    result = []
    seen = set()

    for item in items:

        title = clean_text(
            item.get("title", "")
        )

        if not title:
            continue

        key = title.lower()

        if key in seen:
            continue

        seen.add(key)

        item["title"] = title

        result.append(item)

    return result


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

def collect_netflix_page(url, category):

    print()
    print("=" * 60)
    print(f"NETFLIX {category}")
    print("=" * 60)

    html = fetch_url(url)

    items = []

    # -----------------------------------------------------
    # 공식 페이지의
    #
    # Image#1 ... Image#2 ...
    #
    # 구조를 이용한다.
    # -----------------------------------------------------

    image_pattern = re.compile(
        r"Image#(\d+)\s+(?:in\s+(?:Movies|Shows))?"
        r".*?"
        r"(?:Image:\s*)?"
        r"([^<\n]{2,180})",
        re.IGNORECASE | re.DOTALL
    )

    matches = image_pattern.findall(html)

    for rank, title in matches:

        try:
            rank = int(rank)
        except Exception:
            continue

        if rank < 1 or rank > 10:
            continue

        title = clean_text(title)

        if not title:
            continue

        # 명백한 UI 문구 제거
        bad_words = [
            "my list",
            "watch",
            "explore",
            "limited series",
            "season",
            "button",
        ]

        if title.lower() in bad_words:
            continue

        items.append({
            "rank": rank,
            "title": title
        })

    # -----------------------------------------------------
    # 페이지의 Overview 영역도 보조적으로 검사
    # -----------------------------------------------------

    overview_pattern = re.compile(
        r"0?([1-9]|10)"
        r".{0,80}?"
        r"\[Button:\s*([^\]]{2,180})\]",
        re.IGNORECASE | re.DOTALL
    )

    overview_matches = overview_pattern.findall(
        html
    )

    for rank, title in overview_matches:

        try:
            rank = int(rank)
        except Exception:
            continue

        title = clean_text(title)

        if not title:
            continue

        items.append({
            "rank": rank,
            "title": title
        })

    # -----------------------------------------------------
    # 순위별 정리
    # -----------------------------------------------------

    ranked = {}

    for item in items:

        rank = item["rank"]
        title = item["title"]

        if rank not in ranked:

            ranked[rank] = {
                "rank": rank,
                "title": title
            }

    result = []

    for rank in range(1, 11):

        if rank in ranked:

            result.append(
                ranked[rank]
            )

    print()
    print(
        f"Netflix {category}: "
        f"{len(result)}개"
    )

    for item in result:

        print(
            f"{item['rank']:2d}. "
            f"{item['title']}"
        )

    return {
        "service": "Netflix",
        "category": category,
        "source": url,
        "items": result
    }


def collect_netflix():

    movies_url = (
        "https://www.netflix.com/"
        "tudum/top10/south-korea"
    )

    tv_url = (
        "https://www.netflix.com/"
        "tudum/top10/south-korea/tv"
    )

    return {

        "movies": collect_netflix_page(
            movies_url,
            "영화"
        ),

        "tv": collect_netflix_page(
            tv_url,
            "TV"
        )
    }


# =========================================================
# Disney+
# =========================================================

def disney_bad_title(title):

    title_lower = title.lower()

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

    ]

    for pattern in bad_patterns:

        if pattern in title_lower:
            return True

    return False


def collect_disney():

    url = "https://www.disneyplus.com/ko-kr"

    print()
    print("=" * 60)
    print("DISNEY+")
    print("=" * 60)

    html = fetch_url(url)

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

            if disney_bad_title(title):
                continue

            candidates.append(title)

    # -----------------------------------------------------
    # alt/title
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

            if disney_bad_title(title):
                continue

            candidates.append(title)

    # -----------------------------------------------------
    # 후보 정리
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
    # 너무 짧거나 메뉴성 문구 제거
    # -----------------------------------------------------

    filtered = []

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

    for title in unique:

        if title.lower() in bad_exact:
            continue

        if len(title) < 2:
            continue

        filtered.append(title)

    items = []

    for index, title in enumerate(
        filtered[:10],
        start=1
    ):

        items.append({
            "rank": index,
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

def coupang_bad_title(title):

    lower = title.lower()

    bad_patterns = [

        "모바일히어로",
        "오토플레이",
        "오토",
        "모바일",
        "티저",
        "예고",
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


def collect_coupang():

    url = (
        "https://www.coupangplay.com/catalog"
    )

    print()
    print("=" * 60)
    print("COUPANG PLAY")
    print("=" * 60)

    html = fetch_url(url)

    candidates = []

    # -----------------------------------------------------
    # JSON 데이터
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

            if coupang_bad_title(title):
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

            if coupang_bad_title(title):
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
    # 작품명 정리
    # -----------------------------------------------------

    items = []

    for title in unique:

        if len(items) >= 20:
            break

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
        f"Collected: {collected_at}"
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
            collect_netflix()
        )

    except Exception as e:

        print()
        print(
            f"Netflix 오류: "
            f"{type(e).__name__}: {e}"
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
            f"Disney+ 오류: "
            f"{type(e).__name__}: {e}"
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
            f"Coupang Play 오류: "
            f"{type(e).__name__}: {e}"
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
    print(
        f"저장 완료: {OUTPUT_FILE}"
    )
    print("=" * 60)


if __name__ == "__main__":

    main()
