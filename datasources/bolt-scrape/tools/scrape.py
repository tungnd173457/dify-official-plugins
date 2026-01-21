import json
import requests
from bs4 import BeautifulSoup
from typing import Any, Generator, List, Union
from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

class ScrapeTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        url = tool_parameters.get('url')
        exclude_tags_input = tool_parameters.get('exclude_tags', [])
        
        # Parse exclude_tags if strictly required to be a list
        exclude_tags = []
        if isinstance(exclude_tags_input, list):
            exclude_tags = exclude_tags_input
        elif isinstance(exclude_tags_input, str):
            try:
                # Try parsing as JSON
                parsed = json.loads(exclude_tags_input)
                if isinstance(parsed, list):
                    exclude_tags = parsed
                else:
                    # Treat as comma-separated
                    exclude_tags = [tag.strip() for tag in exclude_tags_input.split(',') if tag.strip()]
            except json.JSONDecodeError:
                # Treat as comma-separated
                exclude_tags = [tag.strip() for tag in exclude_tags_input.split(',') if tag.strip()]
        
        # If no tags provided, maybe default to the ones in the snippet?
        # User said: "Receive input... array containing tags to remove... remove content of tags in the array".
        # If the array is empty, maybe remove nothing?
        # But the snippet had a robust default. 
        # I'll stick to using the input. If input is empty, no exclusion (or maybe the user wants the defaults effectively).
        # Let's assume if input is provided, use it. If completely missing (None), use defaults? 
        # The user's prompt says "input is ... array". So I'll assume they provide it. 
        
        if not url:
            yield self.create_text_message("URL is required.")
            return

        try:
            content = self.extract_clean_text(url, exclude_tags)
            yield self.create_text_message(content)
        except Exception as e:
            yield self.create_text_message(f"Error scraping URL: {str(e)}")

    def extract_clean_text(self, url: str, exclude_tags: List[str] = [], timeout=10) -> str:
        headers = {
            "User-Agent": "Mozilla/5.0"
        }

        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        # remove unwanted tags
        body = soup.body
        if body:
            for tag in body(exclude_tags):
                tag.decompose()
            text = body.get_text(separator="\n", strip=True)
        else:
            for tag in soup(exclude_tags):
                tag.decompose()
            text = soup.get_text(separator="\n", strip=True)

        return text
