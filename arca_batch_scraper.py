#!/usr/bin/env python3
"""
Arca.live 批量爬虫 - 支持标签/频道列表页，抓取所有帖子的媒体
用法: python arca_batch_scraper.py <listing_url> <output_folder_name>
"""

import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, urlencode, parse_qs, urlunparse, urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import httpx
from DrissionPage import ChromiumPage, ChromiumOptions

ALLOWED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
ALLOWED_VIDEO_EXTS = {".mp4", ".webm"}
ALLOWED_EXTS = ALLOWED_IMAGE_EXTS | ALLOWED_VIDEO_EXTS


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw.strip())
    except Exception:
        return default


def _looks_like_media_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return False
        path = parsed.path.lower()
        return any(path.endswith(ext) for ext in ALLOWED_EXTS)
    except Exception:
        return False


def _choose_ext_from_url(media_url: str) -> str:
    parsed = urlparse(media_url)
    ext = Path(parsed.path).suffix
    return ext if ext else ".bin"


def _wait_for_cf(page, timeout_s: int = 120) -> bool:
    start = time.time()
    while time.time() - start < timeout_s:
        try:
            title = page.title or ""
            t = title.lower()
            if "just a moment" in t or "cloudflare" in t:
                time.sleep(1)
                continue
            try:
                text = page.html.lower() if page.html else ""
                if "checking your browser" in text or "cf-ray" in text[:1000]:
                    time.sleep(1)
                    continue
            except:
                pass
            return True
        except Exception:
            time.sleep(1)
    return False


def _wait_for_login(page, timeout_s: int = 300) -> bool:
    """等待用户完成手动登录"""
    start = time.time()
    while time.time() - start < timeout_s:
        try:
            url = page.url or ""
            title = page.title or ""
            if "/u/login" in url or "로그인" in title:
                remaining = int(timeout_s - (time.time() - start))
                print(f"\r请在浏览器中登录... (剩余 {remaining} 秒)", end="", flush=True)
                time.sleep(2)
                continue
            print()
            return True
        except Exception:
            time.sleep(1)
    print()
    return False


def _auto_login(page, username: str, password: str) -> bool:
    try:
        url = page.url or ""
        title = page.title or ""
        if "/u/login" not in url and "로그인" not in title:
            return True
        print("正在自动登录...")
        time.sleep(3)
        username_input = page.ele('#idInput', timeout=15)
        if not username_input:
            return False
        username_input.clear()
        username_input.input(username)
        time.sleep(0.5)
        next_btn = page.ele('#stage-1 button[data-submitstage]', timeout=5)
        if next_btn:
            next_btn.click()
        else:
            username_input.input('\n')
        time.sleep(2)
        password_input = page.ele('#idPassword', timeout=10)
        if not password_input:
            return False
        password_input.clear()
        password_input.input(password)
        time.sleep(0.5)
        login_btn = page.ele('#stage-2 button[data-submitstage]', timeout=5)
        if login_btn:
            login_btn.click()
        else:
            password_input.input('\n')
        time.sleep(3)
        for _ in range(30):
            url = page.url or ""
            title = page.title or ""
            if "/u/login" not in url and "로그인" not in title:
                print("  登录成功！")
                return True
            time.sleep(1)
        return False
    except Exception as e:
        print(f"  登录出错: {e}")
        return False


def _extract_emote_channel_links(page, base_url: str) -> list[str]:
    """从表情包标签搜索页提取所有 /e/XXXXX 表情频道链接"""
    links = []
    seen = set()
    parsed_base = urlparse(base_url)
    netloc = f"{parsed_base.scheme}://{parsed_base.netloc}"
    try:
        raw_links = page.run_js(
            "return Array.from(document.querySelectorAll('a[href]')).map(a => a.getAttribute('href'))"
        )
        if raw_links:
            for href in raw_links:
                if not href:
                    continue
                if href.startswith("/"):
                    full = netloc + href
                elif href.startswith("http"):
                    full = href
                else:
                    continue
                # 只要 /e/纯数字ID (不带路径) 的表情频道链接
                path = urlparse(full).path.rstrip("/")
                m = re.match(r'^/e/(\d+)$', path)
                if m:
                    clean = netloc + path
                    if clean not in seen:
                        seen.add(clean)
                        links.append(clean)
    except Exception as e:
        print(f"  提取频道链接出错: {e}")
    print(f"  找到 {len(links)} 个表情频道: {[l.split('/')[-1] for l in links]}")
    return links


def _extract_media_urls(page) -> list[str]:
    """从帖子页提取所有媒体 URL"""
    ordered_urls = []
    seen = set()

    def add_url(u):
        if not u:
            return
        u = u.replace("\\u002F", "/").replace("\\/", "/").replace("\\", "")
        u = u.replace("&amp;", "&").strip()
        if u.startswith("//"):
            u = "https:" + u
        if not (u.startswith("http://") or u.startswith("https://")):
            return
        if "ac.namu.la" not in u and not _looks_like_media_url(u):
            return
        if u not in seen:
            seen.add(u)
            ordered_urls.append(u)

    try:
        js_code = """
            let root = document.querySelector('.article-content');
            if (!root) root = document.body;
            const res = [];
            root.querySelectorAll('video, img').forEach(el => {
                let src = el.getAttribute('data-url') || el.getAttribute('data-src') || el.getAttribute('src');
                if (src) res.push(src);
                if (el.tagName === 'VIDEO') {
                    el.querySelectorAll('source').forEach(s => {
                        let ssrc = s.getAttribute('src');
                        if (ssrc) res.push(ssrc);
                    });
                }
            });
            return res;
        """
        dom_urls = page.run_js(js_code)
        if dom_urls:
            for u in dom_urls:
                add_url(u)
    except Exception as e:
        print(f"  DOM 提取出错: {e}")

    if not ordered_urls:
        try:
            html = page.html or ""
            cdn_pattern = r'(?:https?:)?//ac\.namu\.la/[^"\'>\\s]+'
            for match in re.finditer(cdn_pattern, html, re.IGNORECASE):
                add_url(match.group(0))
        except Exception:
            pass

    return ordered_urls


def download_file(url: str, output_path: Path, referer: str, user_agent: str, max_retries: int = 3) -> bool:
    tmp_path = output_path.with_suffix(output_path.suffix + ".part")
    for attempt in range(1, max_retries + 1):
        try:
            with httpx.Client(timeout=60, follow_redirects=True) as client:
                headers = {"Referer": referer, "User-Agent": user_agent}
                with client.stream("GET", url, headers=headers) as resp:
                    if resp.status_code >= 400:
                        raise Exception(f"HTTP {resp.status_code}")
                    content_type = (resp.headers.get("content-type") or "").lower()
                    if content_type.startswith("text/html"):
                        raise Exception(f"unexpected content-type {content_type}")
                    tmp_path.parent.mkdir(parents=True, exist_ok=True)
                    with tmp_path.open("wb") as f:
                        for chunk in resp.iter_bytes():
                            if chunk:
                                f.write(chunk)
            size = tmp_path.stat().st_size
            if size < 200:
                raise Exception(f"file too small ({size} bytes)")
            if output_path.exists():
                output_path.unlink()
            tmp_path.replace(output_path)
            return True
        except Exception as e:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except:
                    pass
            if attempt >= max_retries:
                return False
            time.sleep(min(4.0, 0.6 * (2 ** (attempt - 1))))
    return False


def _build_page_url(base_listing_url: str, page_num: int) -> str:
    """构建分页 URL"""
    parsed = urlparse(base_listing_url)
    qs = parse_qs(parsed.query, keep_blank_values=True)
    qs["p"] = [str(page_num)]
    new_query = urlencode({k: v[0] for k, v in qs.items()})
    return urlunparse(parsed._replace(query=new_query))


def _convert_mp4_to_gif(mp4_path: Path) -> bool:
    import subprocess as sp
    gif_path = mp4_path.with_suffix(".gif")
    try:
        import imageio_ffmpeg
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        ffmpeg = "ffmpeg"
    try:
        sp.run(
            [ffmpeg, "-y", "-i", str(mp4_path),
             "-vf", "split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse",
             "-loop", "0", str(gif_path)],
            capture_output=True, check=True, timeout=60,
        )
        mp4_path.unlink()
        return True
    except Exception as e:
        print(f"    GIF转换失败: {e}")
        return False


def main():
    if len(sys.argv) < 3:
        print("用法: python arca_batch_scraper.py <listing_url> <output_folder_name>")
        print("例:   python arca_batch_scraper.py \"https://arca.live/e/43153?target=tag&keyword=xxx&p=1\" \"我的收藏\"")
        sys.exit(1)

    listing_url = sys.argv[1]
    folder_name = sys.argv[2]

    print(f"列表页: {listing_url}")
    print(f"输出目录: downloads/{folder_name}")

    co = ChromiumOptions()
    if _env_int("ARCA_HEADLESS", 0):
        co.headless()
    co.set_argument("--disable-blink-features=AutomationControlled")
    co.set_argument("--no-first-run")
    try:
        profile_dir = Path(__file__).resolve().parent / ".arca_profile_dp"
        co.set_user_data_path(str(profile_dir))
    except Exception:
        pass

    print("启动浏览器...")
    try:
        page = ChromiumPage(co)
    except Exception as e:
        print(f"浏览器启动失败: {e}")
        return

    output_dir = Path("downloads") / folder_name
    output_dir.mkdir(parents=True, exist_ok=True)

    username = os.environ.get("ARCA_USERNAME", "")
    password = os.environ.get("ARCA_PASSWORD", "")

    # 从原始 URL 中提取 keyword 和起始页
    parsed_start = urlparse(listing_url)
    qs_start = parse_qs(parsed_start.query, keep_blank_values=True)
    start_page = int(qs_start.get("p", ["1"])[0])
    keyword_raw = qs_start.get("keyword", [""])[0]
    # 全局翻页基础 URL: https://arca.live/e/?target=tag&keyword=KEYWORD&p=N
    base_netloc = f"{parsed_start.scheme}://{parsed_start.netloc}"
    global_search_base = f"{base_netloc}/e/?target=tag&keyword={keyword_raw}"

    all_channel_links: list[str] = []
    global_media_counter = 0
    success_count = 0
    mp4_files: list[Path] = []

    def _goto_with_login(target_url):
        page.get(target_url)
        _wait_for_cf(page, _env_int("ARCA_CF_WAIT_SECS", 120))
        url_now = page.url or ""
        title_now = page.title or ""
        if "/u/login" in url_now or "로그인" in title_now:
            print("需要登录...")
            if username and password:
                if not _auto_login(page, username, password):
                    print("自动登录失败，等待手动登录 (最多5分钟)...")
                    _wait_for_login(page, 300)
            else:
                print("请在浏览器中手动登录 (最多5分钟)...")
                _wait_for_login(page, 300)
            page.get(target_url)
            time.sleep(2)
            _wait_for_cf(page, 60)
        time.sleep(2)

    try:
        # ─── 阶段1: 收集所有表情频道链接 ──────────────────────
        print("\n===== 阶段1: 收集表情频道链接 =====")
        current_page = start_page

        while True:
            page_url = f"{global_search_base}&p={current_page}"
            print(f"\n访问第 {current_page} 页: {page_url}")
            _goto_with_login(page_url)

            links = _extract_emote_channel_links(page, page_url)

            new_links = [l for l in links if l not in all_channel_links]
            if not new_links:
                print("  本页无新频道，停止翻页")
                break

            all_channel_links.extend(new_links)
            print(f"  累计频道数: {len(all_channel_links)}")
            current_page += 1
            time.sleep(1)

        print(f"\n共找到 {len(all_channel_links)} 个表情频道")

        if not all_channel_links:
            print("没有找到任何表情频道，退出")
            return

        # ─── 阶段2: 逐频道下载媒体 ────────────────────────────
        print("\n===== 阶段2: 下载媒体 =====")
        user_agent = page.run_js("return navigator.userAgent") or "Mozilla/5.0"
        max_retries = _env_int("ARCA_MAX_RETRIES", 4)
        concurrency = _env_int("ARCA_CONCURRENCY", 6)

        for post_idx, post_url in enumerate(all_channel_links, 1):
            print(f"\n[{post_idx}/{len(all_channel_links)}] 访问频道: {post_url}")
            page.get(post_url)
            _wait_for_cf(page, 30)
            time.sleep(2)

            # 滚动加载懒加载内容
            last_height = 0
            for _ in range(10):
                try:
                    h = page.run_js("return document.body.scrollHeight")
                    if h == last_height:
                        break
                    last_height = h
                    page.run_js("window.scrollTo(0, document.body.scrollHeight)")
                    time.sleep(0.8)
                except:
                    break
            time.sleep(0.5)

            media_urls = _extract_media_urls(page)
            print(f"  找到 {len(media_urls)} 个媒体文件")

            if not media_urls:
                continue

            # 过滤视频封面 webp
            video_stems = {Path(urlparse(v).path).stem for v in media_urls
                           if Path(urlparse(v).path).suffix.lower() in ALLOWED_VIDEO_EXTS}
            filtered = []
            for mu in media_urls:
                stem = Path(urlparse(mu).path).stem
                ext = Path(urlparse(mu).path).suffix.lower()
                if ext == ".webp" and stem in video_stems:
                    continue
                filtered.append(mu)

            def download_one(args):
                idx, mu = args
                ext = _choose_ext_from_url(mu)
                filename = f"{idx:04d}{ext}"
                filepath = output_dir / filename
                print(f"  下载: {filename}...", end=" ", flush=True)
                ok = download_file(mu, filepath, post_url, user_agent, max_retries)
                if ok:
                    size_kb = filepath.stat().st_size / 1024
                    print(f"OK ({size_kb:.1f} KB)")
                else:
                    print("失败")
                return (ok, filepath, ext)

            indices = range(global_media_counter + 1, global_media_counter + len(filtered) + 1)
            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                futures = [executor.submit(download_one, (i, u))
                           for i, u in zip(indices, filtered)]
                for future in as_completed(futures):
                    ok, filepath, ext = future.result()
                    if ok:
                        success_count += 1
                        if ext in ALLOWED_VIDEO_EXTS:
                            mp4_files.append(filepath)

            global_media_counter += len(filtered)

        # ─── MP4 → GIF ──────────────────────────────────────────
        if mp4_files:
            print(f"\n正在将 {len(mp4_files)} 个视频转换为 GIF...")
            for p in sorted(mp4_files):
                print(f"  转换: {p.name}...", end=" ", flush=True)
                if _convert_mp4_to_gif(p):
                    print("OK")
                else:
                    print("失败")

        print(f"\n\n===== 完成 =====")
        print(f"处理频道: {len(all_channel_links)} 个")
        print(f"下载媒体: {success_count}/{global_media_counter} 个")
        print(f"输出目录: {output_dir.resolve()}")

    finally:
        page.quit()


if __name__ == "__main__":
    main()
