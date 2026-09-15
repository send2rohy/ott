import json
import re
import subprocess
from datetime import datetime, timezone

OUTPUT_FILE = "test_result.json"

HEADERS = [
    "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36",
    "Accept-Language: ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
]

NETFLIX_MOVIES_URL = "https://www.netflix.com/tudum/top10/south-korea"
NETFLIX_TV_URL = "https://www.netflix.com/tudum/top10/south-korea/tv"

DISNEY_URL = "https://www.disneyplus.com/ko-kr"
COUPANG_URL = "https://www.coupangplay.com/catalog"


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
    ]

    for header in HEADERS:
        cmd += ["-H", header]

    cmd.append(url)

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore"
    )

    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "curl failed")

    return result.stdout


def clean_title(title):
    title = re.sub(r"\s+", " ", title)
    title = title.strip()

    # HTML/JSON 잔여 문자 제거
    title = title.replace("\\u0026", "&")
    title = title.replace("\\/", "/")
    title = title.replace("&amp;", "&")

    return title


def extract_netflix_titles(html):
    """
    Netflix Tudum 페이지에서 다음과 같은 구조를 찾는다.

    Image#1 in Movies
    ...
    Image#2 in Movies

    또는

    Image#1 in TV
    ...

    제목은 해당 이미지 앞뒤의 JSON/HTML 구조에서
    최대한 안전하게 찾는다.
    """

    results = []

    # ---------------------------------------------------------
    # 방법 1
    # alt/title 속성에 제목이 들어있는 경우
    # ---------------------------------------------------------
    patterns = [
        r'<img[^>]+alt=["\']([^"\']+)["\'][^>]*>',
        r'<img[^>]+title=["\']([^"\']+)["\'][^>]*>',
    ]

    candidates = []

    for pattern in patterns:
        for m in re.finditer(pattern, html, re.I):
            title = clean_title(m.group(1))

            if not title:
                continue

            if title.lower() in {
                "image",
                "logo",
                "netflix",
                "my list",
                "watch",
                "explore"
            }:
                continue

            candidates.append(title)

    # ---------------------------------------------------------
    # 방법 2
    # JSON 내부 title 필드
    # ---------------------------------------------------------
    json_patterns = [
        r'"title"\s*:\s*"([^"]+)"',
        r'"name"\s*:\s*"([^"]+)"',
        r'"displayName"\s*:\s*"([^"]+)"',
    ]

    for pattern in json_patterns:
        for m in re.finditer(pattern, html, re.I):
            title = clean_title(m.group(1))

            if not title:
                continue

            candidates.append(title)

    # ---------------------------------------------------------
    # Netflix가 실제 순위 데이터에 사용하는 제목 후보 제거
    # ---------------------------------------------------------
    bad_words = {
        "movies",
        "shows",
        "movie",
        "tv",
        "south korea",
        "my list",
        "watch",
        "explore",
        "netflix",
        "image",
        "top 10",
        "overview",
        "ranking",
    }

    seen = set()

    for title in candidates:
        key = title.lower().strip()

        if key in bad_words:
            continue

        if len(title) < 2:
            continue

        if len(title) > 200:
            continue

        if key in seen:
            continue

        seen.add(key)

        results.append(title)

    return results


def extract_netflix_ranked_titles(html):
    """
    페이지에서 'Image#N in Movies' 주변을 기준으로
    제목 후보를 찾는다.

    제목 순서가 공식 페이지의 순위 순서와 같다는 점을 이용한다.
    """

    # 페이지 텍스트화
    text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.I | re.S)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)

    # HTML 엔티티
    text = (
        text.replace("&amp;", "&")
            .replace("&quot;", '"')
            .replace("&#39;", "'")
            .replace("&apos;", "'")
    )

    ranked = []

    # 실제 페이지에서 확인되는 형식
    # Image#1 in Movies ... 제목 ... Image#2 in Movies
    pattern = re.compile(
        r"Image#\s*(\d{1,2})\s+in\s+(?:Movies|TV)"
        r"(.*?)(?=Image#\s*\d{1,2}\s+in\s+(?:Movies|TV)|Top 10 Movies overview|Top 10 Shows overview|$)",
        re.I
    )

    for match in pattern.finditer(text):
        rank = int(match.group(1))
        section = match.group(2)

        # 앞부분에서 제목 후보 추출
        section = section.strip()

        # 너무 긴 경우 앞부분만 사용
        section = section[:500]

        # 흔한 UI 텍스트 제거
        section = re.sub(
            r"\b(My List|Watch|Explore|in Movies|in TV)\b",
            " ",
            section,
            flags=re.I
        )

        section = re.sub(r"\s+", " ", section).strip()

        if not section:
            continue

        # 제목 앞에 붙는 잡다한 문구 제거
        section = re.sub(
            r"^(?:Image\s*)+",
            "",
            section,
            flags=re.I
        ).strip()

        # 너무 명백한 UI 문구 제외
        if section.lower() in {
            "movies",
            "tv",
            "watch",
            "explore",
            "my list",
        }:
            continue

        ranked.append({
            "rank": rank,
            "title": section
        })

    # 순위 정렬
    ranked.sort(key=lambda x: x["rank"])

    # 중복 순위 제거
    final = []
    seen_rank = set()

    for item in ranked:
        if item["rank"] in seen_rank:
            continue

        seen_rank.add(item["rank"])
        final.append(item)

    return final[:10]


def collect_netflix():
    result = {
        "movies": [],
        "tv": [],
        "error": None
    }

    errors = []

    # ---------------------------------------------------------
    # Movies
    # ---------------------------------------------------------
    try:
        html = curl_page(NETFLIX_MOVIES_URL)

        movies = extract_netflix_ranked_titles(html)

        result["movies"] = movies

        if not movies:
            # 보조 방식
            candidates = extract_netflix_titles(html)

            result["movies"] = [
                {
                    "rank": i + 1,
                    "title": title
                }
                for i, title in enumerate(candidates[:10])
            ]

    except Exception as e:
        errors.append("movies: " + str(e))

    # ---------------------------------------------------------
    # TV
    # ---------------------------------------------------------
    try:
        html = curl_page(NETFLIX_TV_URL)

        tv = extract_netflix_ranked_titles(html)

        result["tv"] = tv

        if not tv:
            candidates = extract_netflix_titles(html)

            result["tv"] = [
                {
                    "rank": i + 1,
                    "title": title
                }
                for i, title in enumerate(candidates[:10])
            ]

    except Exception as e:
        errors.append("tv: " + str(e))

    if errors:
        result["error"] = " | ".join(errors)

    return result


def extract_disney_titles(html):
    """
    Disney+ 페이지에서 실제 콘텐츠 제목 후보를 추출한다.
    """

    candidates = []

    patterns = [
        r'"title"\s*:\s*"([^"]+)"',
        r'"name"\s*:\s*"([^"]+)"',
        r'"contentTitle"\s*:\s*"([^"]+)"',
    ]

    for pattern in patterns:
        for m in re.finditer(pattern, html, re.I):
            title = clean_title(m.group(1))

            if title:
                candidates.append(title)

    bad = {
        "disney+",
        "disney plus",
        "home",
        "search",
        "login",
        "sign up",
        "watch now",
        "top 10",
    }

    result = []
    seen = set()

    for title in candidates:
        key = title.lower()

        if key in bad:
            continue

        if len(title) < 2 or len(title) > 150:
            continue

        if key in seen:
            continue

        seen.add(key)
        result.append(title)

    return result[:10]


def collect_disney():
    try:
        html = curl_page(DISNEY_URL)

        titles = extract_disney_titles(html)

        return {
            "items": [
                {
                    "rank": i + 1,
                    "title": title
                }
                for i, title in enumerate(titles)
            ],
            "error": None
        }

    except Exception as e:
        return {
            "items": [],
            "error": str(e)
        }


def extract_coupang_titles(html):
    """
    Coupang Play 페이지의 제목 후보를 추출한다.
    """

    candidates = []

    patterns = [
        r'"title"\s*:\s*"([^"]+)"',
        r'"name"\s*:\s*"([^"]+)"',
        r'"programTitle"\s*:\s*"([^"]+)"',
    ]

    for pattern in patterns:
        for m in re.finditer(pattern, html, re.I):
            title = clean_title(m.group(1))

            if title:
                candidates.append(title)

    bad_words = {
        "coupang play",
        "home",
        "search",
        "login",
        "sign up",
        "top 20",
        "trending now",
    }

    result = []
    seen = set()

    for title in candidates:
        key = title.lower()

        if key in bad_words:
            continue

        if len(title) < 2 or len(title) > 150:
            continue

        # 모바일 히어로 / 오토플레이 같은 부가 문구 제거
        if "모바일히어로" in title:
            continue

        if "오토플레이" in title:
            continue

        if key in seen:
            continue

        seen.add(key)
        result.append(title)

    return result[:20]


def collect_coupang():
    try:
        html = curl_page(COUPANG_URL)

        titles = extract_coupang_titles(html)

        return {
            "items": [
                {
                    "rank": i + 1,
                    "title": title
                }
                for i, title in enumerate(titles)
            ],
            "error": None
        }

    except Exception as e:
        return {
            "items": [],
            "error": str(e)
        }


def main():

    print("======================================")
    print("OTT COLLECTOR TEST")
    print("======================================")

    print()
    print("[1] Netflix 수집")
    netflix = collect_netflix()

    print("Netflix Movies:", len(netflix["movies"]))
    print("Netflix TV:", len(netflix["tv"]))

    if netflix["error"]:
        print("Netflix ERROR:", netflix["error"])

    print()
    print("[2] Disney+ 수집")
    disney = collect_disney()

    print("Disney+:", len(disney["items"]))

    if disney["error"]:
        print("Disney+ ERROR:", disney["error"])

    print()
    print("[3] Coupang Play 수집")
    coupang = collect_coupang()

    print("Coupang Play:", len(coupang["items"]))

    if coupang["error"]:
        print("Coupang Play ERROR:", coupang["error"])

    data = {
        "collected_at": datetime.now(timezone.utc).isoformat(),

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
    print("======================================")
    print("RESULT SAVED")
    print("======================================")
    print(OUTPUT_FILE)


if __name__ == "__main__":
    main()
