import os
import random
import threading
from pathlib import Path
from typing import Any, Callable, List
from urllib.parse import quote_plus, urlencode, urlsplit, urlunsplit

import requests
from loguru import logger
from moviepy.video.io.VideoFileClip import VideoFileClip

from app.config import config
from app.models.schema import MaterialInfo, VideoAspect, VideoConcatMode
from app.services import material_cache, task_artifacts
from app.utils import utils

# ---------------------------------------------------------------------------
# Per-video provider-variety tracking for the multi-source router.
# Reset at the start of every download_videos() call so variety is measured
# within a single video's worth of search terms, not across the process lifetime.
# ---------------------------------------------------------------------------
_provider_usage_this_video: dict[str, int] = {}
_provider_usage_lock = threading.Lock()

# Thread-safe counter for API key rotation
_api_key_counter = 0
_api_key_lock = threading.Lock()


def _safe_public_url(value: Any) -> str | None:
    """
    只保留可公开展示的 HTTP(S) 页面地址，并移除查询参数和凭据。

    素材下载地址可能携带 API Key、签名 JWT 或临时 token。任务清单只需要
    帮助用户回到供应商的公开素材页，不应保存鉴权参数；用户信息形式的 URL
    同样拒绝，避免 ``https://user:pass@example.com`` 一类内容落盘。
    """
    if not isinstance(value, str) or not value.strip():
        return None

    try:
        parsed = urlsplit(value.strip())
    except ValueError:
        return None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _creator_info(value: Any) -> dict[str, str] | None:
    """从不同供应商的作者结构中提取统一的公开字段。"""
    if isinstance(value, str) and value.strip():
        return {"name": value.strip()}
    if not isinstance(value, dict):
        return None

    creator: dict[str, str] = {}
    creator_id = value.get("id")
    creator_name = value.get("name") or value.get("username")
    creator_page = _safe_public_url(
        value.get("url") or value.get("profile_url") or value.get("profile_page")
    )
    if creator_id is not None:
        creator["id"] = str(creator_id)
    if creator_name:
        creator["name"] = str(creator_name)
    if creator_page:
        creator["profile_page"] = creator_page
    return creator or None


def _material_source_record(item: MaterialInfo, local_path: str) -> dict[str, Any]:
    """
    为成功下载的素材生成轻量来源记录。

    ``source_info`` 可能来自缓存，甚至来自外部构造的 ``MaterialInfo``，因此
    不能原样写入。这里按白名单重新构造，只保留公开页面、业务标识和尺寸，
    并只记录本地文件名，避免用户目录或 Docker 挂载路径进入任务文件。
    """
    source = item.source_info if isinstance(item.source_info, dict) else {}
    record: dict[str, Any] = {
        "provider": str(item.provider or source.get("provider") or ""),
        "local_file": Path(local_path).name,
        "duration": int(item.duration),
    }

    search_term = source.get("search_term")
    asset_id = source.get("asset_id")
    source_page = _safe_public_url(source.get("source_page"))
    if isinstance(search_term, str) and search_term.strip():
        record["search_term"] = search_term.strip()
    if asset_id not in (None, ""):
        record["asset_id"] = str(asset_id)
    if source_page:
        record["source_page"] = source_page

    creator = _creator_info(source.get("creator"))
    if creator:
        record["creator"] = creator

    raw_rendition = source.get("rendition")
    if isinstance(raw_rendition, dict):
        rendition = {}
        for field in ("id", "width", "height"):
            value = raw_rendition.get(field)
            if value not in (None, ""):
                rendition[field] = str(value) if field == "id" else value
        if rendition:
            record["rendition"] = rendition
    return record


def _persist_material_sources(
    task_id: str,
    material_sources: list[dict[str, Any]],
) -> None:
    """
    将当前实际下载成功的素材来源补充到任务清单。

    任务记录是辅助能力，不能改变视频下载函数的返回值，也不能因为写盘失败
    中断成片主流程。``patch_script_data`` 会负责原子替换和异常日志；这里仅在
    成功后记录数量，便于确认任务追溯信息是否已经落盘。
    """
    try:
        saved = task_artifacts.patch_script_data(
            task_id,
            material_sources=material_sources,
        )
        if saved:
            logger.info(
                f"saved material source records: "
                f"task_id={task_id}, count={len(material_sources)}"
            )
    except Exception as exc:
        # task_artifacts 自身已经按失败降级设计，这里仍保留最后一道隔离，
        # 防止未来实现调整或目录解析异常意外影响素材下载返回值。
        logger.warning(
            "failed to persist material source records: "
            f"task_id={task_id}, error={type(exc).__name__}, detail={exc}"
        )


def _get_tls_verify() -> bool:
    # 默认开启 TLS 证书校验，防止素材搜索和下载过程被中间人篡改。
    # 仅在企业代理、自签证书等明确需要的场景下，允许用户通过
    # `config.toml` 显式设置 `tls_verify = false` 临时关闭。
    tls_verify = config.app.get("tls_verify", True)
    if isinstance(tls_verify, str):
        tls_verify = tls_verify.strip().lower() not in ("0", "false", "no", "off")

    if not tls_verify:
        logger.warning(
            "TLS certificate verification is disabled by config.app.tls_verify=false. "
            "Only use this in trusted proxy environments."
        )

    return bool(tls_verify)


def get_api_key(cfg_key: str):
    api_keys = config.app.get(cfg_key)
    if not api_keys:
        raise ValueError(
            f"\n\n##### {cfg_key} is not set #####\n\n"
            f"Please set it in the config.toml file: {config.config_file}\n"
        )

    # if only one key is provided, return it
    if isinstance(api_keys, str):
        return api_keys

    global _api_key_counter
    with _api_key_lock:
        _api_key_counter += 1
        return api_keys[_api_key_counter % len(api_keys)]


def _redact_secret(message: str, secret: str) -> str:
    """
    对即将写入日志的异常文本做最小范围脱敏。

    requests 的连接异常可能包含完整请求 URL，而 Pixabay API Key 通过查询
    参数传递。这里同时替换原始值和 URL 编码值，既保留网络错误信息用于排查，
    又避免密钥进入日志文件。
    """
    safe_message = str(message)
    if not secret:
        return safe_message

    safe_message = safe_message.replace(secret, "***")
    encoded_secret = quote_plus(secret)
    if encoded_secret != secret:
        safe_message = safe_message.replace(encoded_secret, "***")
    return safe_message


def _redact_request_error(error: Exception, *secrets: str) -> str:
    """
    保留网络异常的可排查信息，同时移除 API Key 和代理凭据。

    直接只记录异常类型会丢失 DNS、证书、超时等关键上下文；直接记录原始异常
    又可能回显完整请求 URL。统一入口可以让三个素材供应商使用相同脱敏规则。
    """
    safe_message = str(error)
    for secret in secrets:
        safe_message = _redact_secret(safe_message, str(secret or ""))
    for proxy_url in config.proxy.values():
        safe_message = _redact_secret(safe_message, str(proxy_url))
    return safe_message


def _is_cloudflare_challenge(response: requests.Response) -> bool:
    """
    识别 Cloudflare 返回的 HTML Challenge，而不是把它当成 Pixabay JSON。

    Cloudflare 通常会设置 `cf-mitigated: challenge`；部分部署只返回带有
    "Just a moment" 或 challenge-platform 的 HTML，因此保留内容特征兜底。
    响应正文仅在内存中判断，不写入日志，避免记录无价值的大段 HTML。
    """
    headers = getattr(response, "headers", {}) or {}
    if str(headers.get("cf-mitigated", "")).lower() == "challenge":
        return True

    content_type = str(headers.get("content-type", "")).lower()
    if "text/html" not in content_type:
        return False

    body = str(getattr(response, "text", "")).lower()
    return "just a moment" in body or "/cdn-cgi/challenge-platform/" in body


def _matches_video_aspect(
    width: Any,
    height: Any,
    video_aspect: VideoAspect,
    *,
    is_vertical: Any = None,
) -> bool:
    """
    判断远端素材是否与目标画面方向一致。

    Pexels、Pixabay 和 Coverr 的响应字段并不统一，因此先使用宽高做可靠判断；
    Coverr 部分历史响应缺少尺寸时，再使用明确的 ``is_vertical`` 布尔值兜底。
    无法确认方向的素材直接跳过，避免竖屏任务混入横屏素材并在成片中产生黑边。
    """
    aspect = VideoAspect(video_aspect)
    try:
        normalized_width = int(float(width))
        normalized_height = int(float(height))
    except (TypeError, ValueError):
        normalized_width = 0
        normalized_height = 0

    if normalized_width > 0 and normalized_height > 0:
        if aspect == VideoAspect.portrait:
            return normalized_height > normalized_width
        if aspect == VideoAspect.landscape:
            return normalized_width > normalized_height
        return normalized_width == normalized_height

    if isinstance(is_vertical, bool) and aspect != VideoAspect.square:
        return is_vertical == (aspect == VideoAspect.portrait)
    return False


def _filter_materials_by_aspect(
    items: List[MaterialInfo],
    video_aspect: VideoAspect,
) -> List[MaterialInfo]:
    """
    对缓存结果再次校验方向。

    素材搜索缓存最长保留 24 小时，升级前写入的缓存可能包含方向不匹配的素材。
    在统一缓存入口过滤可以让修复立即生效，也能防御第三方 Provider 或旧缓存
    遗漏远端筛选。无法读取 rendition 尺寸的旧条目按未验证处理并跳过。
    """
    aspect = VideoAspect(video_aspect)
    if aspect == VideoAspect.square:
        # Pixabay 和 Coverr 很少提供原生方形素材。方形输出沿用既有行为，
        # 接受可用候选并交给视频合成阶段裁剪，避免升级后 1:1 任务无素材。
        return list(items)

    filtered_items = []
    for item in items:
        source_info = item.source_info if isinstance(item.source_info, dict) else {}
        rendition = source_info.get("rendition")
        rendition = rendition if isinstance(rendition, dict) else {}
        if _matches_video_aspect(
            rendition.get("width"),
            rendition.get("height"),
            aspect,
        ):
            filtered_items.append(item)
    return filtered_items


def search_videos_pexels(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> List[MaterialInfo]:
    aspect = VideoAspect(video_aspect)
    video_orientation = aspect.name
    video_width, video_height = aspect.to_resolution()
    api_key = get_api_key("pexels_api_keys")
    headers = {
        "Authorization": api_key,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    }
    # Build URL
    params = {"query": search_term, "per_page": 20, "orientation": video_orientation}
    query_url = f"https://api.pexels.com/v1/videos/search?{urlencode(params)}"
    logger.info(f"searching videos on pexels: term={search_term!r}")

    try:
        r = requests.get(
            query_url,
            headers=headers,
            proxies=config.proxy,
            verify=_get_tls_verify(),
            timeout=(30, 60),
        )
        response = r.json()
        video_items = []
        if "videos" not in response:
            logger.error("pexels video search returned an unsupported response")
            return video_items
        videos = response["videos"]
        # loop through each video in the result
        for v in videos:
            duration = v["duration"]
            # check if video has desired minimum duration
            if duration < minimum_duration:
                continue
            video_files = v["video_files"]
            # loop through each url to determine the best quality
            for video in video_files:
                w = int(video["width"])
                h = int(video["height"])
                if (
                    _matches_video_aspect(w, h, aspect)
                    and w == video_width
                    and h == video_height
                ):
                    item = MaterialInfo()
                    item.provider = "pexels"
                    item.url = video["link"]
                    item.duration = duration
                    item.source_info = {
                        "provider": "pexels",
                        "search_term": search_term,
                        "asset_id": (
                            str(v.get("id")) if v.get("id") is not None else None
                        ),
                        "source_page": _safe_public_url(v.get("url")),
                        "creator": _creator_info(v.get("user")),
                        "rendition": {
                            "id": (
                                str(video.get("id"))
                                if video.get("id") is not None
                                else None
                            ),
                            "width": w,
                            "height": h,
                        },
                    }
                    video_items.append(item)
                    break
        return video_items
    except Exception as e:
        logger.error(
            "pexels video search failed: "
            f"error={type(e).__name__}, detail={_redact_request_error(e, api_key)}"
        )

    return []


def search_videos_pixabay(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> List[MaterialInfo]:
    aspect = VideoAspect(video_aspect)

    video_width, video_height = aspect.to_resolution()

    api_key = get_api_key("pixabay_api_keys")
    # Build URL
    params = {
        "q": search_term,
        "video_type": "all",  # Accepted values: "all", "film", "animation"
        "per_page": 50,
        "key": api_key,
    }
    query_url = f"https://pixabay.com/api/videos/?{urlencode(params)}"
    logger.info(
        f"searching videos on pixabay: term={search_term!r}, "
        f"proxy_enabled={bool(config.proxy)}"
    )

    try:
        r = requests.get(
            query_url, proxies=config.proxy, verify=_get_tls_verify(), timeout=(30, 60)
        )
        status_code = int(getattr(r, "status_code", 200))
        headers = getattr(r, "headers", {}) or {}
        content_type = str(headers.get("content-type", ""))
        retry_after = headers.get("retry-after")
        cf_ray = headers.get("cf-ray")

        if _is_cloudflare_challenge(r):
            logger.error(
                "pixabay search was blocked by a Cloudflare challenge: "
                f"status={status_code}, cf_ray={cf_ray or 'unknown'}. "
                "Check the server network or proxy, or use Pexels/Coverr instead."
            )
            return []

        if status_code == 429:
            logger.error(
                "pixabay API rate limit exceeded: "
                f"status=429, retry_after={retry_after or 'unknown'}"
            )
            return []

        if status_code >= 400:
            logger.error(
                "pixabay search request failed: "
                f"status={status_code}, content_type={content_type or 'unknown'}"
            )
            return []

        try:
            response = r.json()
        except ValueError:
            logger.error(
                "pixabay returned an unexpected non-JSON response: "
                f"status={status_code}, content_type={content_type or 'unknown'}"
            )
            return []

        video_items = []
        if "hits" not in response:
            logger.error("pixabay video search returned an unsupported response")
            return video_items
        videos = response["hits"]
        # loop through each video in the result
        for v in videos:
            duration = v["duration"]
            # check if video has desired minimum duration
            if duration < minimum_duration:
                continue
            video_files = v["videos"]
            # loop through each url to determine the best quality
            for video_type in video_files:
                video = video_files[video_type]
                try:
                    w = int(video["width"])
                    h = int(video["height"])
                except (KeyError, TypeError, ValueError):
                    continue
                # Pixabay 很少返回原生方形视频；1:1 输出继续接受满足分辨率的
                # 候选并由合成阶段裁剪。横竖屏则必须严格匹配目标方向。
                orientation_matches = aspect == VideoAspect.square or (
                    _matches_video_aspect(w, h, aspect)
                )
                if orientation_matches and w >= video_width:
                    item = MaterialInfo()
                    item.provider = "pixabay"
                    item.url = video["url"]
                    item.duration = duration
                    item.source_info = {
                        "provider": "pixabay",
                        "search_term": search_term,
                        "asset_id": (
                            str(v.get("id")) if v.get("id") is not None else None
                        ),
                        "source_page": _safe_public_url(v.get("pageURL")),
                        "creator": _creator_info(
                            {
                                "id": v.get("user_id"),
                                "name": v.get("user"),
                            }
                        ),
                        "rendition": {
                            "id": video_type,
                            "width": w,
                            "height": video.get("height"),
                        },
                    }
                    video_items.append(item)
                    break
        return video_items
    except Exception as e:
        error_message = _redact_request_error(e, api_key)
        logger.error(
            "pixabay search request failed: "
            f"error={type(e).__name__}, detail={error_message}"
        )

    return []


def search_videos_coverr(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> List[MaterialInfo]:
    """
    Coverr (https://coverr.co) - free HD/4K stock videos,
    subject to Coverr license terms (https://coverr.co/license).

    Coverr API notes (based on official docs at api.coverr.co/docs/):
      - 鉴权: Authorization: Bearer <api_key>
      - 搜索端点: GET /videos?query=...,响应结构 {"hits": [...], ...}
      - 加 ?urls=true 在搜索响应里直接返回 mp4 直链
      - URL 是 signed JWT(绑定 API key,无过期时间)
      - Coverr 支持通过 filter=is_vertical:true/false 筛选横竖屏素材；
        响应返回后仍根据 max_width/max_height 或 is_vertical 做本地校验
      - duration 字段同时存在 number 和 string 两种形态,本函数都接受

    本函数使用 urls.mp4_download 字段作为下载地址 —— 按 Coverr 官方文档
    (https://api.coverr.co/docs/videos/#download-a-video) 的说法,
    GET 这个 URL 本身就被 Coverr 当作一次合法的 download 事件计入统计,
    无需再调用 PATCH /videos/:id/stats/downloads。
    """
    aspect = VideoAspect(video_aspect)
    api_key = get_api_key("coverr_api_keys")
    headers = {"Authorization": f"Bearer {api_key}"}
    params = {
        "query": search_term,
        "page_size": 20,
        "urls": "true",
        "sort": "popular",
    }
    # 服务端方向筛选可以直接从完整搜索结果中返回目标素材，避免先取热门结果再
    # 本地过滤导致竖屏候选为空。方形素材没有对应布尔条件，继续依赖本地宽高校验。
    if aspect == VideoAspect.portrait:
        params["filter"] = "is_vertical:true"
    elif aspect == VideoAspect.landscape:
        params["filter"] = "is_vertical:false"
    query_url = f"https://api.coverr.co/videos?{urlencode(params)}"
    logger.info(f"searching videos on coverr: term={search_term!r}")

    try:
        r = requests.get(
            query_url,
            headers=headers,
            proxies=config.proxy,
            verify=_get_tls_verify(),
            timeout=(30, 60),
        )
        response = r.json()
        video_items: List[MaterialInfo] = []

        if not isinstance(response, dict) or "hits" not in response:
            logger.error("coverr video search returned an unsupported response")
            return video_items

        for v in response["hits"]:
            # duration 在不同响应里可能是 number(11.625) 或 string("10.500000")
            try:
                duration = int(float(v.get("duration") or 0))
            except (TypeError, ValueError):
                continue
            if duration < minimum_duration:
                continue

            video_id = v.get("id")
            mp4_download_url = (v.get("urls") or {}).get("mp4_download")
            if not video_id or not mp4_download_url:
                continue
            if aspect != VideoAspect.square and not _matches_video_aspect(
                v.get("max_width"),
                v.get("max_height"),
                aspect,
                is_vertical=v.get("is_vertical"),
            ):
                continue

            item = MaterialInfo()
            item.provider = "coverr"
            item.url = mp4_download_url
            item.duration = duration
            item.source_info = {
                "provider": "coverr",
                "search_term": search_term,
                "asset_id": str(video_id),
                "source_page": _safe_public_url(v.get("canonical_url") or v.get("url")),
                "creator": _creator_info(v.get("creator") or v.get("author")),
                "rendition": {
                    "id": "mp4_download",
                    "width": v.get("max_width"),
                    "height": v.get("max_height"),
                },
            }
            video_items.append(item)
        return video_items
    except Exception as e:
        logger.error(
            "coverr video search failed: "
            f"error={type(e).__name__}, detail={_redact_request_error(e, api_key)}"
        )

    return []


# =============================================================================
# Step 4 — Image-to-portrait-video converter (cover-crop, no black bars)
# =============================================================================

def _convert_image_to_portrait_video(
    image_url: str,
    target_width: int,
    target_height: int,
    clip_duration: int,
    save_dir: str = "",
) -> str:
    """
    Download an image, apply cover-crop with Ken-Burns margin, add a slow
    zoom-in (Ken-Burns effect), and write a silent MP4.

    Steps:
    1. Download the image.
    2. Cover-scale + center-crop to a canvas slightly larger than the target
       (``_KB_END_SCALE`` margin) so the zoom never reveals canvas edges.
    3. Apply a slow continuous zoom from 1.0 to ``_KB_END_SCALE`` using
       MoviePy's time-varying resize, then crop the centre of every frame
       back to the exact target resolution -- zero black pixels at any frame.
    4. Write a 30-fps silent libx264 MP4.

    Returns the local .mp4 path on success, or "" on any failure.
    """
    # Ken-Burns parameters.  End scale 1.05 = 5% zoom-in over the full clip
    # duration -- slow enough to feel cinematic, not disorienting.
    _KB_END_SCALE = 1.05

    # Import lazily to avoid heavy deps at module load time.
    try:
        from PIL import Image as _PILImage
        from moviepy.video.VideoClip import ImageClip as _ImageClip
        from moviepy.video.compositing.CompositeVideoClip import (
            CompositeVideoClip as _CompositeVideoClip,
        )
    except ImportError as exc:
        logger.error(f"image-to-video conversion unavailable: {exc}")
        return ""

    if not save_dir:
        save_dir = utils.storage_dir("cache_videos")
    os.makedirs(save_dir, exist_ok=True)

    url_hash = utils.md5(image_url.split("?")[0])
    video_path = os.path.join(save_dir, f"img-{url_hash}.mp4")
    if os.path.exists(video_path) and os.path.getsize(video_path) > 0:
        logger.info(f"image video already exists: {video_path}")
        return video_path

    # ── 1. Download ──────────────────────────────────────────────────────────
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/115.0.0.0 Safari/537.36"
            )
        }
        resp = requests.get(
            image_url,
            headers=headers,
            proxies=config.proxy,
            verify=_get_tls_verify(),
            timeout=(30, 60),
        )
        resp.raise_for_status()
    except Exception as exc:
        logger.error(
            f"failed to download image for conversion: "
            f"error={type(exc).__name__}, detail={_redact_request_error(exc)}"
        )
        return ""

    # ── 2. Decode + cover-crop with Ken-Burns margin ─────────────────────────
    # We crop to a canvas that is _KB_END_SCALE times the target so that when
    # the zoom reaches its maximum the edges are exactly at the target boundary.
    try:
        import io
        img = _PILImage.open(io.BytesIO(resp.content)).convert("RGB")
        src_w, src_h = img.size

        # Canvas = target * end_scale (must be >= target in both axes).
        canvas_w = max(target_width, int(target_width * _KB_END_SCALE) + 1)
        canvas_h = max(target_height, int(target_height * _KB_END_SCALE) + 1)

        # Cover-scale so both axes fill the larger canvas.
        scale = max(canvas_w / src_w, canvas_h / src_h)
        new_w = int(src_w * scale)
        new_h = int(src_h * scale)
        img = img.resize((new_w, new_h), _PILImage.LANCZOS)

        # Center-crop to the canvas size.
        left = (new_w - canvas_w) // 2
        top = (new_h - canvas_h) // 2
        img = img.crop((left, top, left + canvas_w, top + canvas_h))

        # Save a clean PNG as intermediate (strips EXIF / bad metadata).
        png_path = os.path.join(save_dir, f"img-{url_hash}.png")
        img.save(png_path, format="PNG")
    except Exception as exc:
        logger.error(
            f"failed to process image for video conversion: "
            f"error={type(exc).__name__}, detail={exc}"
        )
        return ""

    # ── 3. Ken-Burns zoom + write MP4 ────────────────────────────────────────
    # The ImageClip starts at canvas_w x canvas_h.  The lambda scales it from
    # 1.0 to _KB_END_SCALE over the clip duration, then cropped() trims the
    # centre back to the exact target resolution -- no frame ever shows a
    # black edge because the canvas already has the required margin.
    try:
        clip = _ImageClip(png_path).with_duration(clip_duration)

        # Time-varying resize: 1.0 at t=0, _KB_END_SCALE at t=clip_duration.
        zoomed = clip.resized(
            lambda t: 1.0 + (_KB_END_SCALE - 1.0) * (t / clip_duration)
        )

        # Crop the centre of every zoomed frame to the exact target resolution.
        cropped = zoomed.cropped(
            x_center=zoomed.w / 2,
            y_center=zoomed.h / 2,
            width=target_width,
            height=target_height,
        )

        final = _CompositeVideoClip([cropped], size=(target_width, target_height))
        final.write_videofile(
            video_path,
            fps=30,
            logger=None,
            codec="libx264",
            audio=False,
        )
        clip.close()
        final.close()
        # Clean up intermediate PNG.
        try:
            os.remove(png_path)
        except OSError:
            pass
        logger.success(
            f"image converted to portrait video with Ken-Burns zoom: {video_path} "
            f"({target_width}x{target_height}, {clip_duration}s, "
            f"zoom 1.0\u2192{_KB_END_SCALE})"
        )
        return video_path
    except Exception as exc:
        logger.error(
            f"failed to write image video: "
            f"error={type(exc).__name__}, detail={exc}"
        )
        # Remove partial file so a future retry starts fresh.
        try:
            if os.path.exists(video_path):
                os.remove(video_path)
        except OSError:
            pass
        return ""


# =============================================================================
# Step 2 — New provider search functions
# =============================================================================

def search_images_unsplash(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> List[MaterialInfo]:
    """
    Unsplash Search Photos API (https://unsplash.com/developers).

    Images have no natural duration; ``duration`` is set to ``minimum_duration``
    so downstream duration filtering passes.  The URL points to the raw image;
    the multi-source download path converts it to a portrait MP4 via
    _convert_image_to_portrait_video() before saving.
    """
    aspect = VideoAspect(video_aspect)
    access_key = config.app.get("unsplash_access_key", "").strip()
    if not access_key:
        return []

    orientation_map = {
        VideoAspect.portrait: "portrait",
        VideoAspect.landscape: "landscape",
        VideoAspect.square: "squarish",
    }
    params = {
        "query": search_term,
        "per_page": 20,
        "orientation": orientation_map.get(aspect, "portrait"),
    }
    query_url = f"https://api.unsplash.com/search/photos?{urlencode(params)}"
    headers = {
        "Authorization": f"Client-ID {access_key}",
        "Accept-Version": "v1",
    }
    logger.info(f"searching images on unsplash: term={search_term!r}")

    try:
        r = requests.get(
            query_url,
            headers=headers,
            proxies=config.proxy,
            verify=_get_tls_verify(),
            timeout=(30, 60),
        )
        r.raise_for_status()
        response = r.json()
        results = response.get("results", [])
        items: List[MaterialInfo] = []
        for photo in results:
            # Use the "raw" URL with a size hint for consistent dimensions.
            urls = photo.get("urls") or {}
            # full is typically 2000+px wide; raw is the original unmodified file.
            # We prefer "full" for reasonable download size.
            image_url = urls.get("full") or urls.get("raw") or ""
            if not image_url:
                continue
            photo_id = photo.get("id") or ""
            source_page = _safe_public_url(photo.get("links", {}).get("html"))
            user = photo.get("user") or {}
            width = photo.get("width") or 0
            height = photo.get("height") or 0
            item = MaterialInfo()
            item.provider = "unsplash"
            item.url = image_url
            item.duration = minimum_duration
            item.source_info = {
                "provider": "unsplash",
                "search_term": search_term,
                "asset_id": photo_id,
                "source_page": source_page,
                "creator": _creator_info(
                    {
                        "id": user.get("id"),
                        "name": user.get("name"),
                        "url": (user.get("links") or {}).get("html"),
                    }
                ),
                "rendition": {"width": width, "height": height},
            }
            items.append(item)
        logger.info(
            f"unsplash returned {len(items)} images for {search_term!r}"
        )
        return items
    except Exception as exc:
        logger.error(
            "unsplash image search failed: "
            f"error={type(exc).__name__}, "
            f"detail={_redact_request_error(exc, access_key)}"
        )
    return []


def search_videos_giphy(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> List[MaterialInfo]:
    """
    Giphy Search API (https://developers.giphy.com/).

    Uses each result's MP4 rendition so downstream treats it as an ordinary
    video file — no image conversion needed.  ``rating=g`` keeps content safe.
    Only clips whose MP4 rendition has height > width are kept for portrait output.
    """
    aspect = VideoAspect(video_aspect)
    api_key = config.app.get("giphy_api_key", "").strip()
    if not api_key:
        return []

    params = {
        "api_key": api_key,
        "q": search_term,
        "limit": 20,
        "rating": "g",
        "lang": "en",
    }
    query_url = f"https://api.giphy.com/v1/gifs/search?{urlencode(params)}"
    logger.info(f"searching videos on giphy: term={search_term!r}")

    try:
        r = requests.get(
            query_url,
            proxies=config.proxy,
            verify=_get_tls_verify(),
            timeout=(30, 60),
        )
        r.raise_for_status()
        response = r.json()
        data = response.get("data", [])
        items: List[MaterialInfo] = []
        for gif in data:
            images = gif.get("images") or {}
            # Prefer original mp4 for best quality.
            rendition = images.get("original") or images.get("downsized_medium") or {}
            mp4_url = rendition.get("mp4") or ""
            if not mp4_url:
                continue
            try:
                width = int(rendition.get("width") or 0)
                height = int(rendition.get("height") or 0)
            except (TypeError, ValueError):
                width, height = 0, 0

            # For portrait output, only keep portrait-oriented clips.
            if aspect == VideoAspect.portrait and not (height > width > 0):
                continue
            if aspect == VideoAspect.landscape and not (width > height > 0):
                continue

            gif_id = gif.get("id") or ""
            # Giphy GIFs have no meaningful duration in the search response;
            # use minimum_duration as placeholder (same as Unsplash images).
            try:
                duration_secs = int(float(rendition.get("duration") or minimum_duration))
            except (TypeError, ValueError):
                duration_secs = minimum_duration
            if duration_secs < 1:
                duration_secs = minimum_duration

            item = MaterialInfo()
            item.provider = "giphy"
            item.url = mp4_url
            item.duration = max(duration_secs, minimum_duration)
            item.source_info = {
                "provider": "giphy",
                "search_term": search_term,
                "asset_id": gif_id,
                "source_page": _safe_public_url(
                    f"https://giphy.com/gifs/{gif_id}"
                ),
                "creator": _creator_info(
                    {
                        "name": (gif.get("user") or {}).get("display_name"),
                        "url": (gif.get("user") or {}).get("profile_url"),
                    }
                ),
                "rendition": {"width": width, "height": height},
            }
            items.append(item)
        logger.info(
            f"giphy returned {len(items)} usable clips for {search_term!r}"
        )
        return items
    except Exception as exc:
        logger.error(
            "giphy video search failed: "
            f"error={type(exc).__name__}, "
            f"detail={_redact_request_error(exc, api_key)}"
        )
    return []


def search_images_openverse(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> List[MaterialInfo]:
    """
    Openverse Images API (https://api.openverse.org/v1/images/).

    No API key required for anonymous use.  Rate limits are low for anonymous
    callers, so per_page is capped at 10 and the timeout is short.
    Only CC images with commercial-use licenses are included.
    """
    params = {
        "q": search_term,
        "per_page": 10,
        "license_type": "commercial",
        "format": "jpg",  # prefer JPEG for smaller download size
    }
    query_url = f"https://api.openverse.org/v1/images/?{urlencode(params)}"
    headers = {
        "User-Agent": "MoneyMaker-Automation/1.0 (open-source, non-commercial)"
    }
    logger.info(f"searching images on openverse: term={search_term!r}")

    try:
        r = requests.get(
            query_url,
            headers=headers,
            proxies=config.proxy,
            verify=_get_tls_verify(),
            timeout=(10, 30),
        )
        if r.status_code == 429:
            logger.warning(
                "openverse rate limit hit (anonymous quota); skipping this source"
            )
            return []
        r.raise_for_status()
        response = r.json()
        results = response.get("results", [])
        items: List[MaterialInfo] = []
        for photo in results:
            image_url = photo.get("url") or ""
            if not image_url:
                continue
            photo_id = photo.get("id") or ""
            source_page = _safe_public_url(photo.get("foreign_landing_url"))
            width = photo.get("width") or 0
            height = photo.get("height") or 0
            creator = photo.get("creator") or ""
            creator_url = photo.get("creator_url") or ""
            item = MaterialInfo()
            item.provider = "openverse"
            item.url = image_url
            item.duration = minimum_duration
            item.source_info = {
                "provider": "openverse",
                "search_term": search_term,
                "asset_id": photo_id,
                "source_page": source_page,
                "creator": _creator_info(
                    {"name": creator, "url": creator_url}
                ) if creator else None,
                "rendition": {"width": width, "height": height},
                "license": photo.get("license"),
            }
            items.append(item)
        logger.info(
            f"openverse returned {len(items)} images for {search_term!r}"
        )
        return items
    except Exception as exc:
        logger.error(
            "openverse image search failed: "
            f"error={type(exc).__name__}, detail={_redact_request_error(exc)}"
        )
    return []


# =============================================================================
# Step 3 — Content-safety blocklist and multi-source router
# =============================================================================

# Blocked terms: real people, brand names, fictional characters, franchise titles.
# Keys are lowercased substrings to detect; values are safe generic replacements.
_CONTENT_SAFETY_BLOCKLIST: dict[str, str] = {
    # Real people — common names that often appear in animal-fact scripts
    "attenborough": "wildlife documentary narrator",
    "steve irwin": "wildlife expert",
    "crocodile hunter": "wildlife expert",
    "jane goodall": "primatologist",
    # Franchise / brand / character names
    "spider-man": "superhero figure",
    "spiderman": "superhero figure",
    "batman": "superhero figure",
    "superman": "superhero figure",
    "iron man": "superhero figure",
    "ironman": "superhero figure",
    "black panther": "wild panther",
    "marvel": "superhero action",
    "disney": "animated character",
    "pixar": "animated character",
    "nemo": "clownfish",
    "simba": "lion cub",
    "dumbo": "young elephant",
    "bambi": "young deer",
    "national geographic": "wildlife documentary",
    "nat geo": "wildlife documentary",
    "bbc": "nature documentary",
    "discovery channel": "nature documentary",
    "netflix": "streaming nature documentary",
    "amazon": "amazon rainforest",
    "google": "technology concept",
    "apple": "apple fruit",
    "microsoft": "technology concept",
    "coca-cola": "beverage",
    "pepsi": "beverage",
    "nike": "athletic gear",
}


def _sanitize_search_term(term: str) -> str:
    """
    Content-safety blocklist gate.

    Runs ONCE at the top of the multi-source router before any source is queried.
    Checks the search term against known real-people names, brand names, and
    fictional character names that could cause copyright or content-policy issues.

    Blocked sub-terms are replaced with a safe generic equivalent.  The term is
    rephrased, not dropped — a dropped term would cause the scene to have no
    material at all.
    """
    lower = term.lower()
    sanitized = term
    for blocked, replacement in _CONTENT_SAFETY_BLOCKLIST.items():
        if blocked in lower:
            old = sanitized
            # Case-insensitive replacement preserving surrounding text.
            import re as _re
            sanitized = _re.sub(
                _re.escape(blocked), replacement, sanitized, flags=_re.IGNORECASE
            )
            if sanitized != old:
                logger.info(
                    f"search term sanitized: {old!r} -> {sanitized!r} "
                    f"(blocked pattern: {blocked!r})"
                )
    return sanitized


def _score_candidate(
    item: MaterialInfo,
    target_width: int,
    target_height: int,
    video_aspect: VideoAspect,
) -> float:
    """
    Score a material candidate for best-match selection.

    Higher is better.  Scoring factors:
    - Aspect ratio match:     +10 exact match, +3 close match (within 15%)
    - Resolution adequacy:    +5 if width >= target, +2 if >= 50% of target
    - Video-type bonus:       +3 for real video providers (Pexels, Pixabay,
                              Giphy MP4s, Coverr) vs image providers (Unsplash,
                              Openverse). Prevents the 2:1 image-pool imbalance
                              from systematically beating video in tiebreaks.
    - Openverse penalty:      -1 (anonymous, rate-limited, lower resolution than
                              Unsplash; should only win when better sources fail)
    - Provider variety bonus: +0..+4 based on how rarely this provider has
                              been used for the current video's other terms
                              (tracked in _provider_usage_this_video).  Prevents
                              one provider from dominating all search terms.
    """
    score = 0.0
    source = item.source_info or {}
    rendition = source.get("rendition") or {}

    try:
        w = int(rendition.get("width") or 0)
        h = int(rendition.get("height") or 0)
    except (TypeError, ValueError):
        w, h = 0, 0

    # ── Aspect-ratio scoring ─────────────────────────────────────────────────
    if w > 0 and h > 0:
        if _matches_video_aspect(w, h, video_aspect):
            score += 10.0
        else:
            # Partial credit for near-miss (e.g. square images usable for portrait).
            aspect_ratio = w / h
            target_ratio = target_width / target_height
            if abs(aspect_ratio - target_ratio) / target_ratio < 0.15:
                score += 3.0
    else:
        # No dimension info — small neutral score, don't drop it entirely.
        score += 1.0

    # ── Resolution scoring ───────────────────────────────────────────────────
    if w >= target_width:
        score += 5.0
    elif w >= target_width * 0.5:
        score += 2.0

    # ── Video-type bonus ─────────────────────────────────────────────────────
    # Real video footage (Pexels, Pixabay, Giphy MP4s, Coverr) has more visual
    # interest than an animated still. When base scores are otherwise equal,
    # prefer video over image sources. This breaks the 2:1 image-to-video pool
    # imbalance that arises because Unsplash + Openverse together contribute
    # 25-30 candidates per term while Pexels contributes only 10-15.
    provider = item.provider or "unknown"
    _image_providers_local = {"unsplash", "openverse"}
    if provider not in _image_providers_local:
        score += 3.0

    # ── Openverse de-priority ────────────────────────────────────────────────
    # Openverse is anonymous, rate-limited, and typically lower-resolution than
    # Unsplash. Use it only when other sources come up short.
    if provider == "openverse":
        score -= 1.0

    # ── Provider variety bonus ───────────────────────────────────────────────
    with _provider_usage_lock:
        usage_count = _provider_usage_this_video.get(provider, 0)
    # Bonus decays as a provider is used more: 4, 3, 2, 1, 0 (floored at 0)
    variety_bonus = max(0, 4 - usage_count)
    score += variety_bonus

    return score


def search_materials_multi_source(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> List[MaterialInfo]:
    """
    Query ALL configured sources and return the best-scored combined candidate list.

    Compared to the legacy approach (query sources in order, stop at first
    non-empty result), this always collects from every source that has API
    credentials configured, then ranks by concrete heuristics.  Pexels almost
    always returns *something*, so a first-match-wins approach would use Pexels
    ~100% of the time — this router avoids that.

    Search term is sanitized through the content-safety blocklist exactly once
    before any source is queried.
    """
    aspect = VideoAspect(video_aspect)
    target_width, target_height = aspect.to_resolution()

    # ── Content-safety gate (runs once, before any source query) ────────────
    safe_term = _sanitize_search_term(search_term)

    # ── Collect from all sources concurrently ────────────────────────────────
    all_candidates: List[MaterialInfo] = []
    lock = threading.Lock()

    def _collect(fn, *args):
        try:
            results = fn(*args)
            with lock:
                all_candidates.extend(results)
        except Exception as exc:
            logger.warning(
                f"source {fn.__name__} raised unexpectedly: "
                f"error={type(exc).__name__}, detail={exc}"
            )

    # Always include Pexels.
    sources = [
        (search_videos_pexels, safe_term, minimum_duration, aspect),
    ]
    # Unsplash: only if key is configured.
    if config.app.get("unsplash_access_key", "").strip():
        sources.append((search_images_unsplash, safe_term, minimum_duration, aspect))
    # Giphy: only if key is configured.
    if config.app.get("giphy_api_key", "").strip():
        sources.append((search_videos_giphy, safe_term, minimum_duration, aspect))
    # Openverse: always available (no key needed).
    sources.append((search_images_openverse, safe_term, minimum_duration, aspect))

    threads = [
        threading.Thread(
            target=_collect,
            args=(fn, *fn_args),
            daemon=True,
        )
        for fn, *fn_args in sources
    ]
    for t in threads:
        t.start()
    for t in threads:
        # 75-second wall-clock cap: any single slow source won't stall the whole
        # pipeline.  The _collect wrapper already returns [] on exceptions.
        t.join(timeout=75)

    if not all_candidates:
        logger.warning(
            f"all sources returned no candidates for {search_term!r}"
        )
        return []

    # ── Rank by score, best first ────────────────────────────────────────────
    scored = [
        (
            _score_candidate(item, target_width, target_height, aspect),
            idx,
            item,
        )
        for idx, item in enumerate(all_candidates)
    ]
    scored.sort(key=lambda x: (-x[0], x[1]))  # descending score, stable index tiebreak
    ranked = [item for _, _, item in scored]

    top_providers = [item.provider for item in ranked[:5]]
    logger.info(
        f"multi-source found {len(ranked)} candidates for {search_term!r}; "
        f"top-5 providers: {top_providers}"
    )
    return ranked


def save_video(video_url: str, save_dir: str = "") -> str:
    if not save_dir:
        save_dir = utils.storage_dir("cache_videos")

    if not os.path.exists(save_dir):
        os.makedirs(save_dir)

    url_without_query = video_url.split("?")[0]
    url_hash = utils.md5(url_without_query)
    video_id = f"vid-{url_hash}"
    video_path = f"{save_dir}/{video_id}.mp4"

    # if video already exists, return the path
    if os.path.exists(video_path) and os.path.getsize(video_path) > 0:
        logger.info(f"video already exists: {video_path}")
        return video_path

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    }

    # if video does not exist, download it
    with open(video_path, "wb") as f:
        f.write(
            requests.get(
                video_url,
                headers=headers,
                proxies=config.proxy,
                verify=_get_tls_verify(),
                timeout=(60, 240),
            ).content
        )

    if os.path.exists(video_path) and os.path.getsize(video_path) > 0:
        clip = None
        try:
            clip = VideoFileClip(video_path)
            duration = clip.duration
            fps = clip.fps
            if duration > 0 and fps > 0:
                return video_path
        except Exception as e:
            logger.warning(f"invalid video file: {video_path} => {str(e)}")
            try:
                os.remove(video_path)
            except Exception as remove_error:
                logger.warning(
                    f"failed to remove invalid video file: {video_path}, error: {str(remove_error)}"
                )
        finally:
            if clip is not None:
                try:
                    clip.close()
                except Exception as close_error:
                    logger.warning(
                        f"failed to close video clip: {video_path}, error: {str(close_error)}"
                    )
    return ""


def _search_videos_with_cache(
    provider: str,
    search_videos: Callable[..., List[MaterialInfo]],
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect,
) -> List[MaterialInfo]:
    """
    统一处理三个在线素材源的 24 小时搜索缓存。

    缓存只包裹搜索 API，不改变后续视频下载与去重逻辑。远端返回空列表时不写
    缓存，因为现有 provider 接口使用空列表同时表示“没有结果”和“请求失败”；
    在两者尚未拆分为明确结果类型前，宁可下次重试，也不能把临时故障缓存一天。
    """
    cache_args = {
        "provider": provider,
        "search_term": search_term,
        "minimum_duration": minimum_duration,
        "video_aspect": video_aspect,
    }

    def load_cache_safely() -> List[MaterialInfo] | None:
        try:
            return material_cache.load_material_search_cache(**cache_args)
        except Exception as exc:
            # 缓存是可选优化，任何缓存实现异常都必须按未命中处理，不能阻断
            # Pexels、Pixabay 或 Coverr 的正常远端搜索。
            logger.warning(
                "material search cache read failed, continue with remote search: "
                f"provider={provider}, error={type(exc).__name__}, detail={exc}"
            )
            return None

    def load_matching_cache() -> tuple[List[MaterialInfo] | None, int]:
        cached_items = load_cache_safely()
        if cached_items is None:
            return None, 0

        filtered_cached_items = _filter_materials_by_aspect(
            cached_items,
            video_aspect,
        )
        ignored_count = len(cached_items) - len(filtered_cached_items)
        if ignored_count:
            # 旧版本缓存可能混入其它方向的素材。即使仍有少量可用条目，也要刷新
            # 完整候选集，否则在缓存有效期内会反复使用同一批少量视频。
            return None, ignored_count
        return filtered_cached_items, 0

    cached_items, ignored_count = load_matching_cache()
    if cached_items is not None:
        return cached_items
    if ignored_count:
        logger.info(
            "material search cache contains mismatched orientations, "
            f"refresh from provider: provider={provider}, term={search_term!r}, "
            f"ignored={ignored_count}"
        )

    cache_lock = material_cache.get_material_search_cache_lock(**cache_args)
    with cache_lock:
        # 等待相同搜索条件的线程完成后再次读取，避免多个 API 任务在首次缓存
        # 未命中时同时请求远端，降低第三方接口限流和风控触发概率。
        cached_items, _ = load_matching_cache()
        if cached_items is not None:
            return cached_items

        items = search_videos(
            search_term=search_term,
            minimum_duration=minimum_duration,
            video_aspect=video_aspect,
        )
        # Provider 正常会写入当前关键词，但测试替身、第三方扩展或旧实现可能
        # 遗漏或携带错误值。缓存读取会根据缓存键恢复该字段，因此远端结果也在
        # 同一入口校正，保证首次搜索与缓存命中的任务来源记录保持一致。
        for item in items:
            if isinstance(item.source_info, dict):
                item.source_info = dict(item.source_info)
                item.source_info["search_term"] = search_term
        if items:
            try:
                material_cache.save_material_search_cache(
                    **cache_args,
                    items=items,
                )
            except Exception as exc:
                logger.warning(
                    "material search cache write failed, use remote results: "
                    f"provider={provider}, error={type(exc).__name__}, detail={exc}"
                )
        return items


def download_videos(
    task_id: str,
    search_terms: List[str],
    source: str = "pexels",
    video_aspect: VideoAspect = VideoAspect.portrait,
    video_concat_mode: VideoConcatMode = VideoConcatMode.random,
    audio_duration: float = 0.0,
    max_clip_duration: int = 5,
    match_script_order: bool = False,
) -> List[str]:
    # Reset per-video provider-variety counter so variety scoring is
    # measured within this video's material set only.
    with _provider_usage_lock:
        _provider_usage_this_video.clear()

    # Determine which search backend to use.
    is_multi = source == "multi"
    provider = "pexels"
    remote_search_videos = search_videos_pexels
    if source == "pixabay":
        provider = "pixabay"
        remote_search_videos = search_videos_pixabay
    elif source == "coverr":
        provider = "coverr"
        remote_search_videos = search_videos_coverr
    elif is_multi:
        provider = "multi"
        remote_search_videos = search_materials_multi_source

    def search_videos(
        search_term: str,
        minimum_duration: int,
        video_aspect: VideoAspect,
    ) -> List[MaterialInfo]:
        return _search_videos_with_cache(
            provider=provider,
            search_videos=remote_search_videos,
            search_term=search_term,
            minimum_duration=minimum_duration,
            video_aspect=video_aspect,
        )

    material_directory = config.app.get("material_directory", "").strip()
    if material_directory == "task":
        material_directory = utils.task_dir(task_id)
    elif material_directory and not os.path.isdir(material_directory):
        material_directory = ""

    if match_script_order:
        return _download_videos_by_script_order(
            task_id=task_id,
            search_terms=search_terms,
            search_videos=search_videos,
            video_aspect=video_aspect,
            audio_duration=audio_duration,
            max_clip_duration=max_clip_duration,
            material_directory=material_directory,
        )

    valid_video_items = []
    valid_video_urls = []
    found_duration = 0.0
    _image_providers = {"unsplash", "openverse"}
    aspect = VideoAspect(video_aspect)
    target_width, target_height = aspect.to_resolution()

    for search_term in search_terms:
        video_items = search_videos(
            search_term=search_term,
            minimum_duration=max_clip_duration,
            video_aspect=video_aspect,
        )
        logger.info(f"found {len(video_items)} videos for '{search_term}'")

        for item in video_items:
            if item.url not in valid_video_urls:
                valid_video_items.append(item)
                valid_video_urls.append(item.url)
                found_duration += item.duration

    logger.info(
        f"found total videos: {len(valid_video_items)}, required duration: {audio_duration} seconds, found duration: {found_duration} seconds"
    )
    video_paths = []
    material_sources: list[dict[str, Any]] = []

    concat_mode_value = getattr(video_concat_mode, "value", video_concat_mode)
    if concat_mode_value == VideoConcatMode.random.value:
        random.shuffle(valid_video_items)

    # ── First-clip video preference (multi-source only) ───────────────────────
    # Images from Unsplash/Openverse — even with Ken-Burns motion — don't grab
    # attention as well as real video footage in the opening second of a Short.
    # If the list starts with an image candidate but contains at least one true
    # video candidate, swap the first video to position 0.  All other positions
    # keep their shuffled/scored order unchanged.
    if is_multi and valid_video_items:
        first_is_image = valid_video_items[0].provider in _image_providers
        if first_is_image:
            video_idx = next(
                (
                    i
                    for i, it in enumerate(valid_video_items)
                    if it.provider not in _image_providers
                ),
                None,
            )
            if video_idx is not None:
                logger.info(
                    f"first-clip preference: swapping position 0 (image: "
                    f"{valid_video_items[0].provider}) with position {video_idx} "
                    f"(video: {valid_video_items[video_idx].provider})"
                )
                valid_video_items[0], valid_video_items[video_idx] = (
                    valid_video_items[video_idx],
                    valid_video_items[0],
                )

    total_duration = 0.0

    for item in valid_video_items:
        try:
            source_info = item.source_info if isinstance(item.source_info, dict) else {}
            logger.info(
                f"downloading {item.provider} video: "
                f"asset_id={source_info.get('asset_id') or 'unknown'}"
            )

            # ── Image providers: convert to portrait MP4 before saving ────────
            # Unsplash and Openverse return raw image URLs.  We must convert
            # them to portrait MP4s (cover-crop, no black bars) before the
            # normal save_video() path, which expects a video URL.
            if is_multi and item.provider in _image_providers:
                saved_video_path = _convert_image_to_portrait_video(
                    image_url=item.url,
                    target_width=target_width,
                    target_height=target_height,
                    clip_duration=max_clip_duration,
                    save_dir=material_directory or "",
                )
            else:
                saved_video_path = save_video(
                    video_url=item.url, save_dir=material_directory
                )

            if saved_video_path:
                logger.info(f"video saved: {saved_video_path}")
                video_paths.append(saved_video_path)
                # Update variety counter for the provider that was successfully used.
                if is_multi:
                    with _provider_usage_lock:
                        _provider_usage_this_video[item.provider] = (
                            _provider_usage_this_video.get(item.provider, 0) + 1
                        )
                try:
                    material_sources.append(
                        _material_source_record(item, saved_video_path)
                    )
                except Exception as source_error:
                    # 来源记录异常不能把已经成功下载的素材视为下载失败，更不能
                    # 阻断视频生成；保留供应商和异常类型用于后续定位。
                    logger.warning(
                        "failed to prepare material source record: "
                        f"provider={item.provider}, "
                        f"error={type(source_error).__name__}, detail={source_error}"
                    )
                seconds = min(max_clip_duration, item.duration)
                total_duration += seconds
                if total_duration > audio_duration:
                    logger.info(
                        f"total duration of downloaded videos: {total_duration} seconds, skip downloading more"
                    )
                    break
        except Exception as e:
            logger.error(
                "failed to download material video: "
                f"provider={item.provider}, error={type(e).__name__}, "
                f"detail={_redact_request_error(e, item.url)}"
            )
    logger.success(f"downloaded {len(video_paths)} videos")
    _persist_material_sources(task_id, material_sources)
    return video_paths


def _download_videos_by_script_order(
    task_id: str,
    search_terms: List[str],
    search_videos,
    video_aspect: VideoAspect,
    audio_duration: float,
    max_clip_duration: int,
    material_directory: str,
) -> List[str]:
    """
    按脚本文案顺序下载素材。

    默认下载逻辑会把所有关键词的候选素材合并成一个大列表；如果第一个
    关键词返回很多结果，最终下载时可能一直消耗这个关键词的素材，后续
    脚本主题就排不上时间线。这里按关键词分组后轮询下载：
    第 1 轮取每个关键词的第 1 个候选，第 2 轮取每个关键词的第 2 个候选。
    这样在不重写视频合成引擎的前提下，尽量保证素材顺序贴近文案顺序。
    """
    logger.info("downloading videos with script-order material matching")
    candidate_groups = []
    valid_video_urls = set()
    found_duration = 0.0

    for search_term in search_terms:
        video_items = search_videos(
            search_term=search_term,
            minimum_duration=max_clip_duration,
            video_aspect=video_aspect,
        )
        logger.info(f"found {len(video_items)} videos for '{search_term}'")

        term_items = []
        for item in video_items:
            if item.url in valid_video_urls:
                continue
            term_items.append(item)
            valid_video_urls.add(item.url)
            found_duration += item.duration

        if term_items:
            candidate_groups.append((search_term, term_items))

    logger.info(
        f"found total ordered video candidates: {sum(len(items) for _, items in candidate_groups)}, "
        f"required duration: {audio_duration} seconds, found duration: {found_duration} seconds"
    )

    video_paths = []
    material_sources: list[dict[str, Any]] = []
    total_duration = 0.0
    candidate_index = 0
    while candidate_groups and total_duration <= audio_duration:
        has_candidate = False
        for search_term, term_items in candidate_groups:
            if candidate_index >= len(term_items):
                continue

            has_candidate = True
            item = term_items[candidate_index]
            try:
                source_info = (
                    item.source_info if isinstance(item.source_info, dict) else {}
                )
                logger.info(
                    f"downloading ordered {item.provider} video for {search_term!r}: "
                    f"asset_id={source_info.get('asset_id') or 'unknown'}"
                )
                saved_video_path = save_video(
                    video_url=item.url, save_dir=material_directory
                )
                if saved_video_path:
                    logger.info(f"video saved: {saved_video_path}")
                    video_paths.append(saved_video_path)
                    try:
                        material_sources.append(
                            _material_source_record(item, saved_video_path)
                        )
                    except Exception as source_error:
                        logger.warning(
                            "failed to prepare ordered material source record: "
                            f"provider={item.provider}, "
                            f"error={type(source_error).__name__}, "
                            f"detail={source_error}"
                        )
                    total_duration += min(max_clip_duration, item.duration)
                    if total_duration > audio_duration:
                        logger.info(
                            f"total duration of downloaded videos: {total_duration} seconds, skip downloading more"
                        )
                        break
            except Exception as e:
                logger.error(
                    "failed to download ordered material video: "
                    f"provider={item.provider}, error={type(e).__name__}, "
                    f"detail={_redact_request_error(e, item.url)}"
                )

        if not has_candidate:
            break
        candidate_index += 1

    logger.success(f"downloaded {len(video_paths)} ordered videos")
    _persist_material_sources(task_id, material_sources)
    return video_paths


if __name__ == "__main__":
    download_videos(
        "test123", ["Money Exchange Medium"], audio_duration=100, source="pixabay"
    )
