"""
Step 4: 并发 URL 缩短

完全不涉及 LLM，使用 asyncio + httpx.AsyncClient 并发请求 TinyURL。
"""

import asyncio
import os
from pathlib import Path

import httpx

from pipeline import load_json, save_json, Color

URL_MAP_FILE = Path(os.getenv("OUTPUT_DIR", "./output")) / "short_links_map.json"


async def _shorten_one(
    long_url: str,
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    url_map: dict,
) -> str:
    """缩短单个 URL，命中缓存直接返回"""
    if not long_url or long_url == "#":
        return long_url
    if long_url in url_map:
        return url_map[long_url]

    async with semaphore:
        for attempt in range(2):  # 最多 2 次尝试
            try:
                resp = await client.get(
                    f"http://tinyurl.com/api-create.php?url={long_url}",
                    timeout=10,
                )
                if resp.status_code == 200:
                    short = resp.text.strip()
                    url_map[long_url] = short
                    return short
            except Exception:
                if attempt == 0:
                    await asyncio.sleep(1)
    return long_url


async def run_shortlinks(
    tweets: list[dict],
    intermediate_dir: Path,
    force_rerun: bool = False,
) -> dict:
    """
    并发缩短推文链接。

    返回 {tweet_id: short_url}
    """
    cache_file = intermediate_dir / "shortlinks.json"
    shortlinks: dict = {} if force_rerun else load_json(cache_file)
    url_map: dict = load_json(URL_MAP_FILE)

    to_process = [t for t in tweets if str(t["tweet_id"]) not in shortlinks]

    if not to_process:
        print(f"  {Color.GREEN}✓ 短链接缓存命中，跳过缩链步骤{Color.RESET}")
        return shortlinks

    print(f"  {Color.CYAN}🔗 开始并发缩短 {len(to_process)} 条链接...{Color.RESET}")

    semaphore = asyncio.Semaphore(10)

    async with httpx.AsyncClient() as client:
        tasks = []
        tweet_ids = []
        for t in to_process:
            tid = str(t["tweet_id"])
            long_url = f"https://x.com/{t['username']}/status/{tid}"
            tasks.append(_shorten_one(long_url, client, semaphore, url_map))
            tweet_ids.append(tid)

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for tid, result in zip(tweet_ids, results):
            if isinstance(result, Exception):
                shortlinks[tid] = f"https://x.com/i/status/{tid}"
            else:
                shortlinks[tid] = result

    save_json(cache_file, shortlinks)
    save_json(URL_MAP_FILE, url_map)

    print(f"  {Color.GREEN}✓ 缩链完成：{len(shortlinks)} 条{Color.RESET}")
    return shortlinks
