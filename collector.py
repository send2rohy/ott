import json
import re
import urllib.request
from datetime import datetime, timezone

# =========================================================
# OTT Ranking Collector - 1차 테스트
# Netflix / Disney+ / Coupang Play
# =========================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}

OUTPUT_FILE = "test_result.json"


# =========================================================
# 공통
# =========================================================

def fetch_url(url, timeout=30):
    req = urllib.request.Request(url, headers=HEADERS)

    with urllib.request.urlopen(req, timeout=timeout) as response:
        data = response.read()

    return data.decode("utf-8", errors="ignore")


def clean_text(text):
    if not text:
        return ""

    text = re.sub(r"\s+", " ", text)
    return text.strip()


def save_json(data):
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# =========================================================
# Netflix
# =========================================================

def collect_netflix_page(url, category):
    print(f"\n[Netflix] {category}")
    print(url)

    html = fetch_url(url)

    print(f"HTML length: {len(html):,}")

    results = []

    # -----------------------------------------------------
    # 방법 1
    # Image#1 / Image#2 형태에서 제목 주변 텍스트 추출
    # -----------------------------------------------------

    pattern = re.compile(
        r"Image#(\d+).*?"
        r"(?:Image:\s*)?"
        r"([^<\n]{2,150})",
        re.IGNORECASE | re.DOTALL
    )

    matches = pattern.findall(html)

    for rank, title in matches:
        try:
            rank_num = int(rank)
        except ValueError:
            continue

        title = clean_text(title)

        if not title:
            continue

        if rank_num < 1 or rank_num > 10:
            continue

        if title.lower() in {
            "button",
            "image",
            "my list",
            "watch",
            "explore",
        }:
            continue

        results.append({
            "rank": rank_num,
            "title": title
        })

    # -----------------------------------------------------
    # 중복 제거
    # -----------------------------------------------------

    unique = {}

    for item in results:
        rank = item["rank"]

        if rank not in unique:
            unique[rank] = item

    results = list(unique.values())
    results.sort(key=lambda x: x["rank"])

    # -----------------------------------------------------
    # 최대 10개
    # -----------------------------------------------------

    results = results[:10]

    print(f"Netflix {category}: {len(results)}개")

    for item in results:
        print(f"  {item['rank']}. {item['title']}")

    return {
        "service": "Netflix",
        "category": category,
        "source": url,
        "items": results
    }


def collect_netflix():

    movie_url = (
        "https://www.netflix.com/tudum/top10/south-korea"
    )

    tv_url = (
        "https://www.netflix.com/tudum/top10/south-korea/tv"
    )

    return {
        "movies": collect_netflix_page(
            movie_url,
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

def extract_possible_titles(html):
    """
    Disney+ 페이지에서 제목 후보를 찾아본다.

    Disney+ 페이지는 JS 렌더링 구조가 자주 바뀔 수 있기 때문에
    여러 형태를 검사한다.
    """

    candidates = []

    # -----------------------------------------------------
    # JSON 안의 title / name 값
    # -----------------------------------------------------

    patterns = [
        r'"title"\s*:\s*"([^"]{2,150})"',
        r'"name"\s*:\s*"([^"]{2,150})"',
        r'"displayName"\s*:\s*"([^"]{2,150})"',
    ]

    for pattern in patterns:

        matches = re.findall(
            pattern,
            html,
            flags=re.IGNORECASE
        )

        for title in matches:
            title = clean_text(title)

            if not title:
                continue

            candidates.append(title)

    # -----------------------------------------------------
    # HTML title 속성
    # -----------------------------------------------------

    patterns = [
        r'<img[^>]+alt=["\']([^"\']{2,150})["\']',
        r'<img[^>]+title=["\']([^"\']{2,150})["\']',
    ]

    for pattern in patterns:

        matches = re.findall(
            pattern,
            html,
            flags=re.IGNORECASE
        )

        for title in matches:
            title = clean_text(title)

            if title:
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

    return unique


def collect_disney():

    url = "https://www.disneyplus.com/ko-kr"

    print("\n[Disney+] 한국 TOP 10")
    print(url)

    html = fetch_url(url)

    print(f"HTML length: {len(html):,}")

    titles = extract_possible_titles(html)

    # 페이지 구조 확인용
    items = []

    for index, title in enumerate(titles[:10], start=1):

        items.append({
            "rank": index,
            "title": title
        })

    print(f"Disney+: {len(items)}개")

    for item in items:
        print(f"  {item['rank']}. {item['title']}")

    return {
        "service": "Disney+",
        "category": "한국 TOP 10",
        "source": url,
        "items": items
    }


# =========================================================
# Coupang Play
# =========================================================

def collect_coupang():

    url = "https://www.coupangplay.com/catalog"

    print("\n[Coupang Play] 이번 주 TOP 20")
    print(url)

    html = fetch_url(url)

    print(f"HTML length: {len(html):,}")

    candidates = []

    # -----------------------------------------------------
    # JSON title/name 구조 탐색
    # -----------------------------------------------------

    patterns = [
        r'"title"\s*:\s*"([^"]{2,150})"',
        r'"name"\s*:\s*"([^"]{2,150})"',
        r'"displayName"\s*:\s*"([^"]{2,150})"',
        r'"programName"\s*:\s*"([^"]{2,150})"',
    ]

    for pattern in patterns:

        matches = re.findall(
            pattern,
            html,
            flags=re.IGNORECASE
        )

        for title in matches:

            title = clean_text(title)

            if title:
                candidates.append(title)

    # -----------------------------------------------------
    # alt/title 속성
    # -----------------------------------------------------

    patterns = [
        r'<img[^>]+alt=["\']([^"\']{2,150})["\']',
        r'<img[^>]+title=["\']([^"\']{2,150})["\']',
    ]

    for pattern in patterns:

        matches = re.findall(
            pattern,
            html,
            flags=re.IGNORECASE
        )

        for title in matches:

            title = clean_text(title)

            if title:
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

    items = []

    for index, title in enumerate(unique[:20], start=1):

        items.append({
            "rank": index,
            "title": title
        })

    print(f"Coupang Play: {len(items)}개")

    for item in items:
        print(f"  {item['rank']}. {item['title']}")

    return {
        "service": "Coupang Play",
        "category": "이번 주 TOP 20",
        "source": url,
        "items": items
    }


# =========================================================
# 실행
# =========================================================

def main():

    now = datetime.now(timezone.utc).isoformat()

    print("=" * 60)
    print("OTT Ranking Collector")
    print("=" * 60)
    print(f"Collected at: {now}")

    result = {
        "collectedAt": now,
        "country": "KR",
        "services": {}
    }

    # -----------------------------------------------------
    # Netflix
    # -----------------------------------------------------

    try:

        result["services"]["netflix"] = collect_netflix()

    except Exception as e:

        print("\nNetflix ERROR:")
        print(str(e))

        result["services"]["netflix"] = {
            "error": str(e)
        }

    # -----------------------------------------------------
    # Disney+
    # -----------------------------------------------------

    try:

        result["services"]["disneyplus"] = collect_disney()

    except Exception as e:

        print("\nDisney+ ERROR:")
        print(str(e))

        result["services"]["disneyplus"] = {
            "error": str(e)
        }

    # -----------------------------------------------------
    # Coupang Play
    # -----------------------------------------------------

    try:

        result["services"]["coupangplay"] = collect_coupang()

    except Exception as e:

        print("\nCoupang Play ERROR:")
        print(str(e))

        result["services"]["coupangplay"] = {
            "error": str(e)
        }

    # -----------------------------------------------------
    # 저장
    # -----------------------------------------------------

    save_json(result)

    print("\n" + "=" * 60)
    print(f"완료: {OUTPUT_FILE}")
    print("=" * 60)


if __name__ == "__main__":
    main()
