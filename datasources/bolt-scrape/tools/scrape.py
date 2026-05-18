import json
import time
import requests
from bs4 import BeautifulSoup
from typing import Any, Generator, List, Optional
from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage


# Full, realistic browser headers. The previous "Mozilla/5.0" stub looked like a
# bot and caused the site to intermittently return a degraded/skeleton page,
# which was the root cause of the "same URL -> 2 different results" bug.
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
}


class ScrapeTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        url = tool_parameters.get('url')
        exclude_tags_input = tool_parameters.get('exclude_tags', [])

        exclude_tags = self._parse_exclude_tags(exclude_tags_input)

        if not url:
            yield self.create_text_message("URL is required.")
            return

        try:
            html = self._fetch(url)
            soup = BeautifulSoup(html, "html.parser")

            # Strategy 3: prefer the page's embedded structured data
            # (schema.org JSON-LD). It is present in the raw HTML regardless of
            # SSR cache state / JS rendering, so it is stable across requests.
            structured_text = self._extract_from_json_ld(soup)
            if structured_text:
                yield self.create_text_message(structured_text)
                return

            # Fallback: generic visible-text extraction (original behaviour),
            # so the tool still works for arbitrary non-structured pages.
            content = self._extract_clean_text(soup, exclude_tags)
            yield self.create_text_message(content)
        except Exception as e:
            yield self.create_text_message(f"Error scraping URL: {str(e)}")

    @staticmethod
    def _parse_exclude_tags(exclude_tags_input: Any) -> List[str]:
        if isinstance(exclude_tags_input, list):
            return exclude_tags_input
        if isinstance(exclude_tags_input, str):
            try:
                parsed = json.loads(exclude_tags_input)
                if isinstance(parsed, list):
                    return parsed
            except json.JSONDecodeError:
                pass
            return [t.strip() for t in exclude_tags_input.split(',') if t.strip()]
        return []

    @staticmethod
    def _fetch(url: str, timeout: int = 15, retries: int = 2) -> str:
        last_exc: Optional[Exception] = None
        for attempt in range(retries + 1):
            try:
                resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
                resp.raise_for_status()
                # Let requests/​charset detection decide encoding correctly so
                # CJK content is not mojibake.
                if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
                    resp.encoding = resp.apparent_encoding
                return resp.text
            except requests.RequestException as e:
                last_exc = e
                if attempt < retries:
                    time.sleep(1 + attempt)
        raise last_exc  # type: ignore[misc]

    # schema.org types that carry the page's primary content, ranked by how
    # specific/useful they are. Anything not listed is still usable as a
    # fallback as long as it has a title-ish field.
    CONTENT_TYPE_PRIORITY = [
        "product",
        "recipe",
        "newsarticle",
        "blogposting",
        "article",
        "techarticle",
        "report",
        "question",
        "qapage",
        "howto",
        "event",
        "course",
        "jobposting",
        "creativework",
        "webpage",
    ]

    # schema.org types that are site chrome / metadata, never the page's
    # primary content. Nodes whose every @type is in this set are ignored so
    # we don't return e.g. the publisher Organization instead of the article.
    NON_CONTENT_TYPES = {
        "organization",
        "website",
        "breadcrumblist",
        "listitem",
        "itemlist",
        "searchaction",
        "imageobject",
        "sitenavigationelement",
        "wpheader",
        "wpfooter",
    }

    # Common "title" and "body" keys across schema.org types, tried in order.
    TITLE_KEYS = ["name", "headline", "title"]
    BODY_KEYS = ["description", "articleBody", "text", "reviewBody", "abstract"]

    def _extract_from_json_ld(self, soup: BeautifulSoup) -> Optional[str]:
        """Collect every typed JSON-LD node on the page, pick the most relevant
        one, and render it generically. Works for any schema.org type, not just
        Product."""
        candidates: List[dict] = []
        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            raw = script.string or script.get_text()
            if not raw or not raw.strip():
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            self._collect_nodes(data, candidates)

        best = self._pick_best_node(candidates)
        if best:
            rendered = self._render_node(best)
            if rendered:
                return rendered
        return None

    def _collect_nodes(self, node: Any, out: List[dict]) -> None:
        """Recursively gather all dict nodes that declare an @type."""
        if isinstance(node, list):
            for item in node:
                self._collect_nodes(item, out)
            return
        if isinstance(node, dict):
            if "@graph" in node:
                self._collect_nodes(node["@graph"], out)
            if node.get("@type"):
                out.append(node)
            for value in node.values():
                if isinstance(value, (dict, list)):
                    self._collect_nodes(value, out)

    @classmethod
    def _node_types(cls, node: dict) -> List[str]:
        t = node.get("@type")
        types = t if isinstance(t, list) else [t]
        return [str(x).lower() for x in types if x]

    @classmethod
    def _pick_best_node(cls, candidates: List[dict]) -> Optional[dict]:
        """Prefer the most specific known content type; otherwise fall back to
        any node that at least has a title-like field."""
        def score(node: dict) -> tuple:
            types = cls._node_types(node)
            rank = len(cls.CONTENT_TYPE_PRIORITY)
            for t in types:
                if t in cls.CONTENT_TYPE_PRIORITY:
                    rank = min(rank, cls.CONTENT_TYPE_PRIORITY.index(t))
            has_title = any(node.get(k) for k in cls.TITLE_KEYS)
            has_body = any(node.get(k) for k in cls.BODY_KEYS)
            # lower rank = better; richer node breaks ties
            return (rank, -(has_title + has_body), -len(node))

        def is_content(node: dict) -> bool:
            if not any(node.get(k) for k in cls.TITLE_KEYS + cls.BODY_KEYS):
                return False
            types = cls._node_types(node)
            # drop only if it has types and ALL of them are site chrome
            return not (types and all(t in cls.NON_CONTENT_TYPES for t in types))

        usable = [n for n in candidates if is_content(n)]
        if not usable:
            return None
        return min(usable, key=score)

    @classmethod
    def _render_node(cls, node: dict) -> str:
        """Generic renderer: pull common title/body plus a handful of widely
        used schema.org fields, regardless of the node's @type."""
        lines: List[str] = []

        for k in cls.TITLE_KEYS:
            if node.get(k):
                lines.append(str(node[k]).strip())
                break

        types = [t for t in cls._node_types(node) if t]
        if types:
            lines.append(f"Type: {', '.join(types)}")

        author = cls._name_of(node.get("author"))
        if author:
            lines.append(f"Author: {author}")

        for k in ("datePublished", "dateModified", "uploadDate"):
            if node.get(k):
                lines.append(f"Date: {node[k]}")
                break

        brand = cls._name_of(node.get("brand"))
        if brand:
            lines.append(f"Brand: {brand}")

        for k in ("sku", "mpn", "isbn", "identifier"):
            if node.get(k):
                lines.append(f"{k.upper()}: {node[k]}")
                break

        offers = node.get("offers")
        if isinstance(offers, list):
            offers = offers[0] if offers else None
        if isinstance(offers, dict):
            price = offers.get("price") or offers.get("lowPrice")
            currency = offers.get("priceCurrency", "")
            if price is not None:
                lines.append(f"Price: {price} {currency}".strip())
            if offers.get("availability"):
                lines.append(
                    f"Availability: {str(offers['availability']).split('/')[-1]}")

        for k in cls.BODY_KEYS:
            if node.get(k):
                lines.append("")
                lines.append(str(node[k]).strip())
                break

        # Recipe / HowTo style structured content
        cls._append_list(lines, node.get("recipeIngredient"), "Ingredients")
        cls._append_steps(lines, node.get("recipeInstructions") or node.get("step"))

        return "\n".join(lines).strip()

    @staticmethod
    def _name_of(value: Any) -> Optional[str]:
        if isinstance(value, dict):
            return value.get("name")
        if isinstance(value, list):
            names = [ScrapeTool._name_of(v) for v in value]
            names = [n for n in names if n]
            return ", ".join(names) if names else None
        if isinstance(value, str):
            return value
        return None

    @staticmethod
    def _append_list(lines: List[str], items: Any, header: str) -> None:
        if isinstance(items, list) and items:
            lines.append("")
            lines.append(f"{header}:")
            for it in items:
                lines.append(f"- {it}")

    @staticmethod
    def _append_steps(lines: List[str], steps: Any) -> None:
        if not isinstance(steps, list) or not steps:
            return
        lines.append("")
        lines.append("Steps:")
        for i, st in enumerate(steps, 1):
            if isinstance(st, dict):
                st = st.get("text") or st.get("name") or ""
            if st:
                lines.append(f"{i}. {st}")

    @staticmethod
    def _extract_clean_text(soup: BeautifulSoup, exclude_tags: List[str]) -> str:
        body = soup.body
        if body:
            if exclude_tags:
                for tag in body(exclude_tags):
                    tag.decompose()
            return body.get_text(separator="\n", strip=True)
        if exclude_tags:
            for tag in soup(exclude_tags):
                tag.decompose()
        return soup.get_text(separator="\n", strip=True)
