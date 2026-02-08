from collections.abc import Generator
from typing import Any
import requests

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage
from dify_plugin.errors.tool import ToolProviderCredentialValidationError


class GetBrandProjectsTool(Tool):

    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage]:
        if not self.runtime or not self.runtime.credentials:
            raise ToolProviderCredentialValidationError("Tool runtime or credentials are missing")

        api_base_url = self.runtime.credentials.get("api_base_url")
        api_key = self.runtime.credentials.get("api_key")

        if not api_base_url:
            raise ToolProviderCredentialValidationError("Knowledge API base URL is required.")
        if not api_key:
            raise ToolProviderCredentialValidationError("Knowledge API key is required.")

        # Get parameters from tool_parameters
        dataset_id = tool_parameters.get("dataset_id")
        brand_name = tool_parameters.get("brand_name")

        if not brand_name:
            yield self.create_text_message("Error: brand_name parameter is required")
            return

        if not dataset_id:
            yield self.create_text_message("Error: dataset_id parameter is required")
            return

        # Get the brand documents
        headers = {
            "authorization": f"bearer {api_key}",
            "content-type": "application/json",
        }
        url = f"{api_base_url.rstrip('/')}/brand/document?brand_name={brand_name}&dataset_id={dataset_id}"
        try:
            response = requests.get(url, headers=headers, timeout=60)
            response.raise_for_status()
            documents = response.json()
            yield self.create_json_message(documents)
        except Exception as e:
            yield self.create_text_message(f"Error: {str(e)}")
