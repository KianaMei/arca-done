#!/usr/bin/env python3
"""
Arca.live 表情包爬虫 (DrissionPage 版本)
使用 DrissionPage 绕过 Cloudflare 检测
"""

import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

# 修复Windows控制台编码
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import httpx
from DrissionPage import ChromiumPage, ChromiumOptions

ALLOWED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
ALLOWED_VIDEO_EXTS = {".mp4", ".webm"}
ALLOWED_EXTS = ALLOWED_IMAGE_EXTS | ALLOWED_VIDEO_EXTS


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    raw = raw.strip().lower()
    if raw in {"1", "true", "yes", "y", "on"}:
        return True
    if raw in {"0", "false", "no", "n", "off"}:
        return False
    return default


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


def _classify_urls(urls: list[str]) -> tuple[list[str], list[str]]:
    images: list[str] = []
    videos: list[str] = []
    for u in urls:
        path = urlparse(u).path.lower()
        ext = Path(path).suffix
        if ext in ALLOWED_VIDEO_EXTS:
            videos.append(u)
        elif ext in ALLOWED_IMAGE_EXTS:
            images.append(u)
        else:
            images.append(u)
    return images, videos


def sanitize_filename(name: str) -> str:
    """清理文件名"""
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    name = re.sub(r"\s+", "_", name)
    return name[:50] if len(name) > 50 else name


def _choose_ext_from_url(media_url: str) -> str:
    parsed = urlparse(media_url)
    ext = Path(parsed.path).suffix
    return ext if ext else ".bin"


def _wait_for_cf(page, timeout_s: int = 120) -> bool:
    """等待 Cloudflare 验证完成"""
    start = time.time()
    while time.time() - start < timeout_s:
        try:
            title = page.title or ""
            t = title.lower()
            # 检查是否还在验证页面
            if "just a moment" in t or "cloudflare" in t:
                time.sleep(1)
                continue
            
            # 检查页面内容
            try:
                text = page.html.lower() if page.html else ""
                if "checking your browser" in text or "cf-ray" in text[:1000]:
                    time.sleep(1)
                    continue
            except:
                pass
            
            # 验证通过
            return True
        except Exception:
            time.sleep(1)
    return False


def _wait_for_login(page, timeout_s: int = 300) -> bool:
    """等待用户完成登录"""
    start = time.time()
    while time.time() - start < timeout_s:
        try:
            url = page.url or ""
            title = page.title or ""
            
            # 如果在登录页面或标题包含登录，继续等待
            if "/u/login" in url or "로그인" in title or "login" in title.lower():
                remaining = int(timeout_s - (time.time() - start))
                print(f"\r请在浏览器中登录... (剩余 {remaining} 秒)", end="", flush=True)
                time.sleep(2)
                continue
            
            print()  # 换行
            return True
        except Exception:
            time.sleep(1)
    print()
    return False


def _auto_login(page, username: str, password: str) -> bool:
    """自动登录 arca.live (多阶段登录流程)"""
    try:
        url = page.url or ""
        title = page.title or ""

        if "/u/login" not in url and "로그인" not in title:
            return True

        print("正在自动登录...")
        time.sleep(3)

        # Stage 1: 填写用户名
        username_input = page.ele('#idInput', timeout=15)
        if not username_input:
            print("  找不到用户名输入框")
            return False

        username_input.clear()
        username_input.input(username)
        print(f"  已填写用户名: {username}")
        time.sleep(0.5)

        # 点击 Stage 1 的"下一步"按钮
        next_btn = page.ele('#stage-1 button[data-submitstage]', timeout=5)
        if next_btn:
            next_btn.click()
            print("  已点击下一步")
        else:
            username_input.input('\n')
            print("  以回车提交用户名")

        # 等待 Stage 2 激活
        time.sleep(2)

        # Stage 2: 填写密码
        password_input = page.ele('#idPassword', timeout=10)
        if not password_input:
            print("  找不到密码输入框")
            return False

        password_input.clear()
        password_input.input(password)
        print("  已填写密码")
        time.sleep(0.5)

        # 点击 Stage 2 的"登录"按钮
        login_btn = page.ele('#stage-2 button[data-submitstage]', timeout=5)
        if login_btn:
            login_btn.click()
            print("  已点击登录按钮")
        else:
            password_input.input('\n')
            print("  以回车提交密码")

        # 等待登录完成
        time.sleep(3)
        for _ in range(30):
            url = page.url or ""
            title = page.title or ""
            if "/u/login" not in url and "로그인" not in title:
                print("  登录成功！")
                return True
            time.sleep(1)

        print("  登录失败或超时（可能需要二次验证）")
        return False

    except Exception as e:
        print(f"  登录出错: {e}")
        return False


def _extract_media_urls(page) -> list[str]:
    """从页面按顺序提取所有媒体 URL"""
    ordered_urls = []
    seen = set()

    def add_url(u):
        if not u: return
        # 清理
        u = u.replace("\\u002F", "/").replace("\\/", "/").replace("\\", "")
        u = u.replace("&amp;", "&")
        u = u.strip()
        
        if u.startswith("//"):
            u = "https:" + u
            
        if not (u.startswith("http://") or u.startswith("https://")):
            return
            
        # 过滤: 只要 ac.namu.la 或 媒体后缀
        if "ac.namu.la" not in u and not _looks_like_media_url(u):
            return
            
        if u not in seen:
            seen.add(u)
            ordered_urls.append(u)

    print("  正在提取 URL...")
    
    # 1. DOM 顺序提取 (最准确)
    try:
        # 重点提取 .article-content 下的媒体，以防提取到侧边栏的干扰项
        # 如果找不到 .article-content，就提取全局
        js_code = """
            let root = document.querySelector('.article-content');
            if (!root) root = document.body;
            
            const res = [];
            // 查找所有视频和图片，按顺序
            root.querySelectorAll('video, img').forEach(el => {
                // 优先取 data-url (原始大图/视频), 然后 src
                let src = el.getAttribute('data-url') || el.getAttribute('data-src') || el.getAttribute('src');
                if (src) res.push(src);
                
                // 处理 source 标签
                if (el.tagName === 'VIDEO') {
                    el.querySelectorAll('source').forEach(s => {
                         let ssrc = s.getAttribute('src');
                         if(ssrc) res.push(ssrc);
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

    # 2. 如果 DOM 没提取到什么东西，再尝试全文正则作为保底 (可能会乱序，但总比没有好)
    if not ordered_urls:
        print("  DOM 提取为空，尝试正则提取...")
        try:
            html = page.html or ""
            cdn_pattern = r'(?:https?:)?//ac\.namu\.la/[^"\'>\\s]+'
            for match in re.finditer(cdn_pattern, html, re.IGNORECASE):
                add_url(match.group(0))
        except Exception:
            pass
            
    print(f"  提取到 {len(ordered_urls)} 个有序 URL")
    return ordered_urls


def download_file(url: str, output_path: Path, referer: str, user_agent: str, max_retries: int = 3) -> bool:
    """下载单个文件"""
    tmp_path = output_path.with_suffix(output_path.suffix + ".part")
    
    for attempt in range(1, max_retries + 1):
        try:
            with httpx.Client(timeout=60, follow_redirects=True) as client:
                headers = {
                    "Referer": referer,
                    "User-Agent": user_agent,
                }
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


def _clean_page_title(raw: str) -> str:
    """去掉页面标题中的网站后缀"""
    for suffix in (" - 아카라이브", " - arca.live", " - Arca.live"):
        if raw.endswith(suffix):
            raw = raw[:-len(suffix)]
    return raw.strip()



def _convert_mp4_to_gif(mp4_path: Path) -> bool:
    """MP4 → GIF (palette 优化)"""
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
        print(f"    转换失败: {e}")
        return False


def main():
    if len(sys.argv) < 2:
        print("Arca.live 表情包爬虫 (DrissionPage 版)")
        print("=" * 40)
        print("用法: python arca_scraper_dp.py <url> [output_dir]")
        sys.exit(1)
    
    url = sys.argv[1]
    print(f"正在访问: {url}")
    
    # 配置浏览器选项
    co = ChromiumOptions()
    # 尝试从环境变量读取 HEADLESS 设置，默认关闭（以便通过 CF）
    if _env_int("ARCA_HEADLESS", 0):
        co.headless()

    co.set_argument("--disable-blink-features=AutomationControlled")
    co.set_argument("--no-first-run")
    
    # 恢复用户数据目录以保持登录状态
    try:
        profile_dir = Path(__file__).resolve().parent / ".arca_profile_dp"
        co.set_user_data_path(str(profile_dir))
    except Exception as e:
        print(f"设置用户数据目录失败: {e}")
        # 如果设置失败，继续运行（不带 profile）

    print("启动浏览器...")
    # 尝试连接，如果不成功则报错退出
    try:
        page = ChromiumPage(co)
    except Exception as e:
        print(f"浏览器启动失败: {e}")
        return
    
    try:
        # 访问页面
        page.get(url)
        
        # 等待 Cloudflare 验证
        print("等待 Cloudflare 验证...")
        cf_timeout = _env_int("ARCA_CF_WAIT_SECS", 120)
        if not _wait_for_cf(page, cf_timeout):
            print("警告: Cloudflare 验证可能未完成")
        
        # 检测是否需要登录
        url_now = page.url or ""
        title_now = page.title or ""
        if "/u/login" in url_now or "로그인" in title_now:
            print("\n⚠️  需要登录才能查看此内容！")
            # 从环境变量或默认值获取账号密码
            username = os.environ.get("ARCA_USERNAME", "")
            password = os.environ.get("ARCA_PASSWORD", "")
            # 自动登录
            if not _auto_login(page, username, password):
                print("自动登录失败，退出")
                return
            # 登录成功后重新访问目标页面
            page.get(url)
            time.sleep(2)
        
        # 等待页面加载
        print("等待页面加载...")
        time.sleep(2)
        
        # 滚动页面加载懒加载内容
        max_scrolls = _env_int("ARCA_MAX_SCROLLS", 20)
        last_height = 0
        for i in range(max_scrolls):
            try:
                height = page.run_js("return document.body.scrollHeight")
                if height == last_height:
                    break
                last_height = height
                page.run_js("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(1.2)
            except:
                break
        time.sleep(1)
        
        raw_title = page.title or "arca_download"
        title = _clean_page_title(raw_title)
        print(f"页面标题: {title}")
        dir_name = sanitize_filename(title)
        
        # 提取媒体 URL
        all_urls = _extract_media_urls(page)
        images, videos = _classify_urls(all_urls)
        
        # 智能过滤 webp 封面：
        # 在 arca.live 上，视频文件通常有一个同名的 webp 封面图
        # 例如：abc123.mp4 + abc123.webp（封面）
        # 我们只需要下载视频，封面图可以跳过（重复内容）
        # 但如果 webp 与视频不同名，说明是独立图片，需要保留

        # 1. 提取所有视频的文件名（不含扩展名）
        video_stems = {Path(urlparse(v).path).stem for v in videos}

        # 2. 分离 webp：检查是否为视频封面
        webp_covers = []  # 视频封面（跳过）
        webp_images = []  # 独立的 webp 图片（保留）
        other_images = []  # 其他格式图片（保留）

        for img_url in images:
            parsed_path = urlparse(img_url).path
            img_stem = Path(parsed_path).stem
            img_ext = Path(parsed_path).suffix.lower()

            if img_ext == '.webp':
                # 如果 webp 的文件名与某个视频相同，判定为封面
                if img_stem in video_stems:
                    webp_covers.append(img_url)
                else:
                    webp_images.append(img_url)
            else:
                other_images.append(img_url)

        # 过滤掉视频封面 webp，保留其余所有媒体
        cover_set = set(webp_covers)
        all_media = [u for u in all_urls if u not in cover_set]

        print(f"\n找到 {len(other_images) + len(webp_images)} 张图片, {len(videos)} 个视频"
              f" (跳过 {len(webp_covers)} 个封面)")

        if not all_media:
            print("没有找到媒体文件")
            return

        # 确定输出目录：base_dir / 标题_中文翻译
        base_dir = Path(sys.argv[2]) if len(sys.argv) >= 3 else Path("downloads")
        output_dir = base_dir / dir_name

        output_dir.mkdir(parents=True, exist_ok=True)
        print(f"输出目录: {output_dir}\n")

        # 获取 User-Agent
        user_agent = page.run_js("return navigator.userAgent") or "Mozilla/5.0"

        max_retries = _env_int("ARCA_MAX_RETRIES", 4)
        concurrency = _env_int("ARCA_CONCURRENCY", 6)
        success_count = 0
        mp4_files: list[Path] = []

        def download_one(args):
            i, media_url = args
            ext = _choose_ext_from_url(media_url)
            filename = f"{i:03d}{ext}"
            filepath = output_dir / filename

            print(f"  下载: {filename}...", end=" ", flush=True)
            ok = download_file(media_url, filepath, url, user_agent, max_retries)

            if ok:
                size_kb = filepath.stat().st_size / 1024
                print(f"OK ({size_kb:.1f} KB)")
            else:
                print("失败")
            return (ok, filepath, ext)

        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [executor.submit(download_one, (i, u))
                       for i, u in enumerate(all_media, 1)]
            for future in as_completed(futures):
                ok, filepath, ext = future.result()
                if ok:
                    success_count += 1
                    if ext in ALLOWED_VIDEO_EXTS:
                        mp4_files.append(filepath)

        print(f"\n下载完成: {success_count}/{len(all_media)}")

        # MP4 → GIF 转换
        if mp4_files:
            print(f"\n正在将 {len(mp4_files)} 个视频转换为 GIF...")
            gif_ok = 0
            for p in sorted(mp4_files):
                print(f"  转换: {p.name}...", end=" ", flush=True)
                if _convert_mp4_to_gif(p):
                    gif_ok += 1
                    print("OK")
                else:
                    print("失败")
            print(f"GIF 转换完成: {gif_ok}/{len(mp4_files)}")
        
    finally:
        page.quit()


if __name__ == "__main__":
    main()
