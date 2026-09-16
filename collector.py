# ============================================================
# TMDB 상세정보
# ============================================================

TMDB_DETAILS_FILE = "tmdb.json"
TMDB_DETAIL_CACHE_DAYS = 7


def load_tmdb_details():
    if not os.path.exists(TMDB_DETAILS_FILE):
        return {}

    try:
        with open(TMDB_DETAILS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict):
            return data

    except Exception as e:
        print(f"[TMDB CACHE] 불러오기 실패: {e}")

    return {}


def save_tmdb_details(data):
    try:
        with open(TMDB_DETAILS_FILE, "w", encoding="utf-8") as f:
            json.dump(
                data,
                f,
                ensure_ascii=False,
                indent=2
            )

        print(
            f"[TMDB CACHE] {TMDB_DETAILS_FILE} 저장 완료 "
            f"({len(data)}개)"
        )

    except Exception as e:
        print(f"[TMDB CACHE] 저장 실패: {e}")


def tmdb_get_detail(media_type, tmdb_id):
    """
    TMDB 상세정보를 가져온다.

    media_type:
        tv
        movie
    """

    if not TMDB_API_KEY:
        return None

    if not tmdb_id:
        return None

    if media_type not in ("tv", "movie"):
        return None

    try:
        data = tmdb_request(
            f"/{media_type}/{tmdb_id}",
            {
                "language": "ko-KR",
                "append_to_response": "credits,videos"
            }
        )

        if not data:
            return None

        credits = data.get("credits") or {}

        # ----------------------------------------------------
        # 감독
        # ----------------------------------------------------

        directors = []

        for person in credits.get("crew", []):
            if person.get("job") == "Director":
                name = person.get("name")

                if name and name not in directors:
                    directors.append(name)

        # TV는 감독 정보가 없는 경우가 많으므로 제작자 사용
        if not directors and media_type == "tv":
            for person in data.get("created_by", []):
                name = person.get("name")

                if name and name not in directors:
                    directors.append(name)

        # ----------------------------------------------------
        # 출연진
        # ----------------------------------------------------

        cast = []

        for person in credits.get("cast", [])[:10]:
            name = person.get("name")

            if name and name not in cast:
                cast.append(name)

        # ----------------------------------------------------
        # 장르
        # ----------------------------------------------------

        genres = []

        for genre in data.get("genres", []):
            name = genre.get("name")

            if name:
                genres.append(name)

        # ----------------------------------------------------
        # 개봉일 / 첫 방송일
        # ----------------------------------------------------

        if media_type == "tv":
            release_date = data.get("first_air_date", "")
        else:
            release_date = data.get("release_date", "")

        # ----------------------------------------------------
        # 러닝타임
        # ----------------------------------------------------

        runtime = data.get("runtime")

        if not runtime and media_type == "tv":
            runtimes = data.get("episode_run_time") or []

            if runtimes:
                runtime = runtimes[0]

        # ----------------------------------------------------
        # 예고편
        # ----------------------------------------------------

        trailer_key = None

        videos = data.get("videos") or {}
        video_results = videos.get("results") or []

        # 공식 YouTube Trailer 우선
        for video in video_results:

            if (
                video.get("site") == "YouTube"
                and video.get("type") == "Trailer"
                and video.get("official") is True
            ):
                trailer_key = video.get("key")
                break

        # 공식 Trailer가 없으면 일반 Trailer
        if not trailer_key:

            for video in video_results:

                if (
                    video.get("site") == "YouTube"
                    and video.get("type") == "Trailer"
                ):
                    trailer_key = video.get("key")
                    break

        # 그래도 없으면 YouTube 영상
        if not trailer_key:

            for video in video_results:

                if video.get("site") == "YouTube":
                    trailer_key = video.get("key")
                    break

        # ----------------------------------------------------
        # 제목
        # ----------------------------------------------------

        if media_type == "tv":

            korean_title = (
                data.get("name")
                or data.get("original_name")
                or ""
            )

            original_title = (
                data.get("original_name")
                or data.get("name")
                or ""
            )

        else:

            korean_title = (
                data.get("title")
                or data.get("original_title")
                or ""
            )

            original_title = (
                data.get("original_title")
                or data.get("title")
                or ""
            )

        # ----------------------------------------------------
        # Blogger에서 실제로 필요한 정보만 저장
        # ----------------------------------------------------

        result = {
            "id": data.get("id"),
            "media_type": media_type,

            "title": korean_title,
            "original_title": original_title,

            "poster_path": data.get("poster_path"),
            "backdrop_path": data.get("backdrop_path"),

            "vote_average": data.get("vote_average"),
            "vote_count": data.get("vote_count"),

            "release_date": release_date,

            "genres": genres,

            "runtime": runtime,

            "overview": data.get("overview") or "",

            "director": directors,
            "cast": cast,

            "trailer_key": trailer_key,

            "homepage": data.get("homepage") or ""
        }

        return result

    except Exception as e:

        print(
            f"[TMDB DETAIL ERROR] "
            f"{media_type}/{tmdb_id}: {e}"
        )

        return None


def build_tmdb_details(current_items):
    """
    현재 ranking.json에 들어가는 콘텐츠들의
    TMDB 상세정보를 tmdb.json으로 만든다.

    기존 tmdb.json이 있으면 7일 동안 재사용한다.
    """

    existing = load_tmdb_details()

    result = {}

    now = datetime.now(timezone.utc)

    for item in current_items:

        tmdb_id = item.get("tmdb_id")
        media_type = item.get("media_type")

        if not tmdb_id:
            continue

        if media_type not in ("tv", "movie"):
            continue

        key = f"{media_type}:{tmdb_id}"

        old = existing.get(key)

        # ----------------------------------------------------
        # 기존 캐시 확인
        # ----------------------------------------------------

        if old:

            cached_at = old.get("cached_at")

            if cached_at:

                try:

                    cached_time = datetime.fromisoformat(
                        cached_at.replace("Z", "+00:00")
                    )

                    age = now - cached_time

                    if age.days < TMDB_DETAIL_CACHE_DAYS:

                        result[key] = old

                        print(
                            f"[TMDB CACHE] 재사용 "
                            f"{key}"
                        )

                        continue

                except Exception:
                    pass

        # ----------------------------------------------------
        # 새 TMDB 상세정보 요청
        # ----------------------------------------------------

        print(
            f"[TMDB DETAIL] 요청 "
            f"{media_type}/{tmdb_id}"
        )

        detail = tmdb_get_detail(
            media_type,
            tmdb_id
        )

        if detail:

            detail["cached_at"] = (
                now.isoformat()
            )

            result[key] = detail

        elif old:

            # API 오류가 나더라도 기존 데이터 유지
            result[key] = old

    return result
