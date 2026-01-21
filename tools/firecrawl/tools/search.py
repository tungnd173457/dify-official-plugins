from typing import Any, Generator
from dify_plugin.entities.tool import ToolInvokeMessage
from dify_plugin import Tool

from .firecrawl_appx import FirecrawlApp, get_array_params


class SearchTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        """
        the api doc:
        https://api.firecrawl.dev/v2/search
        """
        app = FirecrawlApp(
            api_key=self.runtime.credentials["firecrawl_api_key"], base_url=self.runtime.credentials["base_url"]
        )
        
        query = tool_parameters["query"]
        limit = tool_parameters.get("limit", 5)
        sources = get_array_params(tool_parameters, "sources")
        
        result = app.search(query=query, limit=limit, sources=sources)
        yield self.create_json_message(result)
