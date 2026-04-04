"""Web 工具模块：提供 web_search（网页搜索）和 web_fetch（网页抓取）功能。"""

from __future__ import annotations

import asyncio
import html
import json
import os
import re
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import httpx
from loguru import logger

from nanobot.agent.tools.base import Tool

if TYPE_CHECKING:
    from nanobot.config.schema import WebSearchConfig

# ========================= 共享常量 =========================
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7_2) AppleWebKit/537.36"
MAX_REDIRECTS = 5  # 限制重定向次数，防止 DoS 攻击


# ========================= 辅助函数 =========================

def _strip_tags(text: str) -> str:
    """
    去除 HTML 标签并解码 HTML 实体。

    参数：
        text: 包含 HTML 的字符串

    返回：
        纯文本字符串，去除了 <script>、<style> 等标签，并将 &lt; 等实体解码为实际字符。
    """
    # 移除 <script> 标签及其内容
    text = re.sub(r'<script[\s\S]*?</script>', '', text, flags=re.I)
    # 移除 <style> 标签及其内容
    text = re.sub(r'<style[\s\S]*?</style>', '', text, flags=re.I)
    # 移除所有其他 HTML 标签
    text = re.sub(r'<[^>]+>', '', text)
    # 解码 HTML 实体（如 &amp; → &）
    return html.unescape(text).strip()


def _normalize(text: str) -> str:
    """
    规范化空白字符：将多个空格合并为一个，将三个以上连续换行合并为两个换行。

    参数：
        text: 输入字符串

    返回：
        规范化后的字符串。
    """
    # 将连续的空白字符（空格、制表符）替换为单个空格
    text = re.sub(r'[ \t]+', ' ', text)
    # 将三个以上连续换行替换为两个换行
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def _validate_url(url: str) -> tuple[bool, str]:
    """
    验证 URL 是否合法：必须是 http 或 https 协议，且包含域名。

    参数：
        url: 待验证的 URL

    返回：
        (是否合法, 错误信息) 元组。合法时错误信息为空字符串。
    """
    try:
        p = urlparse(url)
        if p.scheme not in ('http', 'https'):
            return False, f"仅允许 http/https 协议，当前是 '{p.scheme or '未提供'}'"
        if not p.netloc:
            return False, "缺少域名"
        return True, ""
    except Exception as e:
        return False, str(e)


def _format_results(query: str, items: list[dict[str, Any]], n: int) -> str:
    """
    将不同搜索提供商返回的结果格式化为统一的纯文本输出。

    参数：
        query: 搜索查询词
        items: 搜索结果列表，每个元素包含 title、url、content（摘要）
        n: 最多返回的结果数量

    返回：
        格式化后的字符串，包含查询词、编号、标题、URL 和摘要。
    """
    if not items:
        return f"没有找到与“{query}”相关的结果。"
    lines = [f"“{query}”的搜索结果：\n"]
    for i, item in enumerate(items[:n], 1):
        # 对标题和摘要进行标签去除和空白规范化
        title = _normalize(_strip_tags(item.get("title", "")))
        snippet = _normalize(_strip_tags(item.get("content", "")))
        lines.append(f"{i}. {title}\n   {item.get('url', '')}")
        if snippet:
            lines.append(f"   {snippet}")
    return "\n".join(lines)


# ========================= WebSearchTool 类 =========================

class WebSearchTool(Tool):
    """网页搜索工具，通过配置的搜索提供商（Brave、Tavily、SearXNG、Jina、DuckDuckGo）执行搜索。"""

    # 类属性定义工具名称、描述和参数 JSON Schema
    name = "web_search"
    description = "搜索网页内容，返回标题、链接和摘要。"
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词。"},
            "count": {"type": "integer", "description": "返回结果数量（1 到 10）。", "minimum": 1, "maximum": 10},
        },
        "required": ["query"],
    }

    def __init__(self, config: WebSearchConfig | None = None, proxy: str | None = None):
        """
        初始化 WebSearchTool。

        参数：
            config: WebSearchConfig 配置对象，包含 provider、api_key、base_url 等。
            proxy: HTTP 代理地址，可选。
        """
        from nanobot.config.schema import WebSearchConfig

        self.config = config if config is not None else WebSearchConfig()
        self.proxy = proxy
        # proxy: 可选的 HTTP 代理地址，会传递给 httpx.AsyncClient
        # config 包含 provider/api_key/base_url 等运行时配置

    async def execute(self, query: str, count: int | None = None, **kwargs: Any) -> str:
        """
        执行搜索。

        参数：
            query: 搜索关键词
            count: 结果数量（1-10），若未提供则使用配置中的 max_results
            **kwargs: 额外参数（兼容性）

        返回：
            格式化后的搜索结果字符串。
        """
        # 确定使用的搜索提供商，默认 "brave"
        provider = self.config.provider.strip().lower() or "brave"
        # 限制结果数量在 1-10 之间
        n = min(max(count or self.config.max_results, 1), 10)

        # 根据提供商调用相应的方法
        if provider == "duckduckgo":
            return await self._search_duckduckgo(query, n)
        elif provider == "tavily":
            return await self._search_tavily(query, n)
        elif provider == "searxng":
            return await self._search_searxng(query, n)
        elif provider == "jina":
            return await self._search_jina(query, n)
        elif provider == "brave":
            return await self._search_brave(query, n)
        else:
            return f"错误：未知的搜索提供商“{provider}”。"

    # ---------- 各提供商的具体实现 ----------

    async def _search_brave(self, query: str, n: int) -> str:
        """
        使用 Brave Search API 进行搜索。
        需要设置环境变量 BRAVE_API_KEY 或在配置中提供 api_key。
        """
        api_key = self.config.api_key or os.environ.get("BRAVE_API_KEY", "")
        if not api_key:
            logger.warning("未设置 BRAVE_API_KEY，自动回退到 DuckDuckGo 搜索")
            return await self._search_duckduckgo(query, n)  # 降级到 DuckDuckGo

        try:
            async with httpx.AsyncClient(proxy=self.proxy) as client:
                r = await client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    params={"q": query, "count": n},
                    headers={"Accept": "application/json", "X-Subscription-Token": api_key},
                    timeout=10.0,
                )
                r.raise_for_status()
            # 提取搜索结果
            items = [
                {"title": x.get("title", ""), "url": x.get("url", ""), "content": x.get("description", "")}
                for x in r.json().get("web", {}).get("results", [])
            ]
            return _format_results(query, items, n)
        except Exception as e:
            return f"错误：Brave 搜索失败：{e}"

    async def _search_tavily(self, query: str, n: int) -> str:
        """
        使用 Tavily API 进行搜索。
        需要设置环境变量 TAVILY_API_KEY 或在配置中提供 api_key。
        """
        api_key = self.config.api_key or os.environ.get("TAVILY_API_KEY", "")
        if not api_key:
            logger.warning("未设置 TAVILY_API_KEY，自动回退到 DuckDuckGo 搜索")
            return await self._search_duckduckgo(query, n)

        try:
            async with httpx.AsyncClient(proxy=self.proxy) as client:
                r = await client.post(
                    "https://api.tavily.com/search",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={"query": query, "max_results": n},
                    timeout=15.0,
                )
                r.raise_for_status()
            return _format_results(query, r.json().get("results", []), n)
        except Exception as e:
            return f"错误：Tavily 搜索失败：{e}"

    async def _search_searxng(self, query: str, n: int) -> str:
        """
        使用自托管的 SearXNG 实例进行搜索。
        需要设置环境变量 SEARXNG_BASE_URL 或在配置中提供 base_url。
        """
        base_url = (self.config.base_url or os.environ.get("SEARXNG_BASE_URL", "")).strip()
        if not base_url:
            logger.warning("未设置 SEARXNG_BASE_URL，自动回退到 DuckDuckGo 搜索")
            return await self._search_duckduckgo(query, n)

        endpoint = f"{base_url.rstrip('/')}/search"
        is_valid, error_msg = _validate_url(endpoint)
        if not is_valid:
            return f"错误：SearXNG 地址不合法：{error_msg}"

        try:
            async with httpx.AsyncClient(proxy=self.proxy) as client:
                r = await client.get(
                    endpoint,
                    params={"q": query, "format": "json"},
                    headers={"User-Agent": USER_AGENT},
                    timeout=10.0,
                )
                r.raise_for_status()
            return _format_results(query, r.json().get("results", []), n)
        except Exception as e:
            return f"错误：SearXNG 搜索失败：{e}"

    async def _search_jina(self, query: str, n: int) -> str:
        """
        使用 Jina AI 的搜索 API（https://s.jina.ai/）。
        需要设置环境变量 JINA_API_KEY 或在配置中提供 api_key。
        """
        api_key = self.config.api_key or os.environ.get("JINA_API_KEY", "")
        if not api_key:
            logger.warning("未设置 JINA_API_KEY，自动回退到 DuckDuckGo 搜索")
            return await self._search_duckduckgo(query, n)

        try:
            headers = {"Accept": "application/json", "Authorization": f"Bearer {api_key}"}
            async with httpx.AsyncClient(proxy=self.proxy) as client:
                r = await client.get(
                    "https://s.jina.ai/",
                    params={"q": query},
                    headers=headers,
                    timeout=15.0,
                )
                r.raise_for_status()
            data = r.json().get("data", [])[:n]
            items = [
                {"title": d.get("title", ""), "url": d.get("url", ""), "content": d.get("content", "")[:500]}
                for d in data
            ]
            return _format_results(query, items, n)
        except Exception as e:
            return f"错误：Jina 搜索失败：{e}"

    async def _search_duckduckgo(self, query: str, n: int) -> str:
        """
        使用 DuckDuckGo 的非官方库 `ddgs` 进行搜索（本地抓取）。
        此方法作为其他提供商不可用时的降级方案。
        """
        try:
            from ddgs import DDGS

            ddgs = DDGS(timeout=10)
            # 由于 ddgs 是同步库，使用 asyncio.to_thread 在线程池中执行
            raw = await asyncio.to_thread(ddgs.text, query, max_results=n)
            if not raw:
                return f"没有找到与“{query}”相关的结果。"
            items = [
                {"title": r.get("title", ""), "url": r.get("href", ""), "content": r.get("body", "")}
                for r in raw
            ]
            return _format_results(query, items, n)
        except Exception as e:
            logger.warning("DuckDuckGo 搜索失败：{}", e)
            return f"错误：DuckDuckGo 搜索失败（{e}）"


# ========================= WebFetchTool 类 =========================

class WebFetchTool(Tool):
    """网页抓取工具：从 URL 获取内容并提取可读文本（HTML → Markdown/纯文本）。"""

    name = "web_fetch"
    description = "抓取网页链接并提取适合阅读的正文内容（HTML 转 Markdown 或纯文本）。"
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "要抓取的网页链接。"},
            "extractMode": {"type": "string", "enum": ["markdown", "text"], "default": "markdown"},
            "maxChars": {"type": "integer", "minimum": 100, "description": "返回内容的最大字符数。"},
        },
        "required": ["url"],
    }

    def __init__(self, max_chars: int = 50000, proxy: str | None = None):
        """
        初始化 WebFetchTool。

        参数：
            max_chars: 提取内容的最大字符数，超过则截断。
            proxy: HTTP 代理地址，可选。
        """
        self.max_chars = max_chars
        self.proxy = proxy
        # max_chars: 最大提取字符数，超过则截断。proxy 同样透传给 httpx 客户端。

    async def execute(self, url: str, extractMode: str = "markdown", maxChars: int | None = None, **kwargs: Any) -> str:
        """
        执行网页抓取。

        参数：
            url: 目标 URL
            extractMode: 提取模式，"markdown"（转换为 Markdown）或 "text"（纯文本）
            maxChars: 最大字符数，覆盖实例的 max_chars
            **kwargs: 额外参数（兼容性）

        返回：
            JSON 字符串，包含提取结果及元数据（状态、提取器、是否截断等）。
        """
        max_chars = maxChars or self.max_chars
        is_valid, error_msg = _validate_url(url)
        if not is_valid:
            return json.dumps({"error": f"URL 校验失败：{error_msg}", "url": url}, ensure_ascii=False)

        # 优先尝试外部的 Jina Reader 接口（可靠且能做较好结构化抽取）。
        # 若 Jina 不可用或被限流，则降级到本地的 readability 提取实现。
        result = await self._fetch_jina(url, max_chars)
        if result is None:
            result = await self._fetch_readability(url, extractMode, max_chars)
        return result

    async def _fetch_jina(self, url: str, max_chars: int) -> str | None:
        """
        通过 Jina Reader API（https://r.jina.ai/）获取网页内容。

        返回：
            如果成功，返回包含提取结果的 JSON 字符串；失败则返回 None。
        """
        try:
            headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
            jina_key = os.environ.get("JINA_API_KEY", "")
            if jina_key:
                headers["Authorization"] = f"Bearer {jina_key}"
            async with httpx.AsyncClient(proxy=self.proxy, timeout=20.0) as client:
                r = await client.get(f"https://r.jina.ai/{url}", headers=headers)
                if r.status_code == 429:
                    logger.debug("Jina Reader 被限流，自动回退到 readability 提取")
                    return None  # 限流时降级
                r.raise_for_status()

            data = r.json().get("data", {})
            title = data.get("title", "")
            text = data.get("content", "")
            if not text:
                return None

            if title:
                text = f"# {title}\n\n{text}"
            truncated = len(text) > max_chars
            if truncated:
                text = text[:max_chars]

            return json.dumps({
                "url": url, "finalUrl": data.get("url", url), "status": r.status_code,
                "extractor": "jina", "truncated": truncated, "length": len(text), "text": text,
            }, ensure_ascii=False)
        except Exception as e:
            logger.debug("Jina Reader 处理 {} 失败，自动回退到 readability：{}", url, e)
            return None

    def _extract_title_from_html(self, html_text: str) -> str:
        """在不依赖第三方库的情况下，从原始 HTML 中提取标题。"""
        match = re.search(r"<title[^>]*>([\s\S]*?)</title>", html_text, flags=re.I)
        if not match:
            return ""
        return _normalize(_strip_tags(match.group(1)))

    def _extract_html_content(self, html_text: str, extract_mode: str) -> tuple[str, str]:
        """从 HTML 中提取正文；若缺少 readability，则自动降级。"""
        title = ""
        extractor = "html"

        try:
            from readability import Document

            doc = Document(html_text)
            title = _normalize(_strip_tags(doc.title() or ""))
            body_html = doc.summary()
            extractor = "readability"
        except Exception as exc:
            logger.debug("readability 不可用或提取失败，改用基础 HTML 提取：{}", exc)
            title = self._extract_title_from_html(html_text)
            body_match = re.search(r"<body[^>]*>([\s\S]*?)</body>", html_text, flags=re.I)
            body_html = body_match.group(1) if body_match else html_text

        if extract_mode == "markdown":
            content = self._to_markdown(body_html)
        else:
            content = _normalize(_strip_tags(body_html))

        if title and content:
            return f"# {title}\n\n{content}", extractor
        if title:
            return title, extractor
        return content, extractor

    async def _fetch_readability(self, url: str, extract_mode: str, max_chars: int) -> str:
        """
        本地抓取方法，使用 httpx 和 readability-lxml 提取内容。

        参数：
            url: 目标 URL
            extract_mode: "markdown" 或 "text"
            max_chars: 最大字符数

        返回：
            JSON 字符串，包含提取结果。
        """
        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                max_redirects=MAX_REDIRECTS,
                timeout=30.0,
                proxy=self.proxy,
            ) as client:
                r = await client.get(url, headers={"User-Agent": USER_AGENT})
                r.raise_for_status()

            ctype = r.headers.get("content-type", "")

            # 根据 Content-Type 决定处理方式
            if "application/json" in ctype:
                # JSON 响应：直接格式化输出
                text, extractor = json.dumps(r.json(), indent=2, ensure_ascii=False), "json"
            elif "text/html" in ctype or r.text[:256].lower().startswith(("<!doctype", "<html")):
                # HTML 响应：优先用 readability，缺失依赖时回退到基础 HTML 提取
                text, extractor = self._extract_html_content(r.text, extract_mode)
            else:
                # 其他类型（如纯文本）直接返回原始文本
                text, extractor = r.text, "raw"

            truncated = len(text) > max_chars
            if truncated:
                text = text[:max_chars]

            return json.dumps({
                "url": url, "finalUrl": str(r.url), "status": r.status_code,
                "extractor": extractor, "truncated": truncated, "length": len(text), "text": text,
            }, ensure_ascii=False)
        except httpx.ProxyError as e:
            logger.error("网页抓取代理错误，链接 {}：{}", url, e)
            return json.dumps({"error": f"代理错误：{e}", "url": url}, ensure_ascii=False)
        except Exception as e:
            logger.error("网页抓取失败，链接 {}：{}", url, e)
            return json.dumps({"error": f"网页抓取失败：{e}", "url": url}, ensure_ascii=False)

    def _to_markdown(self, html_content: str) -> str:
        """
        将 HTML 片段转换为 Markdown 格式（简单实现，仅处理链接、标题、列表和段落）。

        参数：
            html_content: 包含 HTML 的字符串

        返回：
            Markdown 格式文本。
        """
        # 处理 <a> 标签：转换为 [文本](url)
        text = re.sub(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>([\s\S]*?)</a>',
                      lambda m: f'[{_strip_tags(m[2])}]({m[1]})', html_content, flags=re.I)
        # 处理 <h1>...<h6>：转换为 # 标题
        text = re.sub(r'<h([1-6])[^>]*>([\s\S]*?)</h\1>',
                      lambda m: f'\n{"#" * int(m[1])} {_strip_tags(m[2])}\n', text, flags=re.I)
        # 处理 <li>：转换为 - 列表项
        text = re.sub(r'<li[^>]*>([\s\S]*?)</li>', lambda m: f'\n- {_strip_tags(m[1])}', text, flags=re.I)
        # 处理块级元素：</p>, </div>, </section>, </article> 后添加两个换行
        text = re.sub(r'</(p|div|section|article)>', '\n\n', text, flags=re.I)
        # 处理 <br> 和 <hr>：转换为一个换行
        text = re.sub(r'<(br|hr)\s*/?>', '\n', text, flags=re.I)
        # 最后去除剩余 HTML 标签并规范化空白
        return _normalize(_strip_tags(text))
