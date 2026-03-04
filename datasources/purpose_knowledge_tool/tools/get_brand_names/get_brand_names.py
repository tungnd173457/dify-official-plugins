from collections.abc import Generator
from typing import Any
import requests
import ast
import json

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage
from dify_plugin.errors.tool import ToolProviderCredentialValidationError


class GetBrandNamesTool(Tool):

    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage]:
        dataset_id = tool_parameters.get("dataset_id")
        if not self.runtime or not self.runtime.credentials:
            raise ToolProviderCredentialValidationError("Tool runtime or credentials are missing")

        api_base_url = self.runtime.credentials.get("api_base_url")
        api_key = self.runtime.credentials.get("api_key")

        if not api_base_url:
            raise ToolProviderCredentialValidationError("Knowledge API base URL is required.")
        if not api_key:
            raise ToolProviderCredentialValidationError("Knowledge API key is required.")

        # Get the brand names
        headers = {
            "authorization": f"bearer {api_key}",
            "content-type": "application/json",
        }
        params = {
            "dataset_id": dataset_id,
        }
        url = f"{api_base_url.rstrip('/')}/brand/list"
        try:
            response = requests.get(url, headers=headers, params=params, timeout=60)
            response.raise_for_status()
            brands = response.json()
            yield self.create_json_message(brands)
        except Exception as e:
            yield self.create_text_message(f"Error: {str(e)}")
