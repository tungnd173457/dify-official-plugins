from collections.abc import Generator
from typing import Any
import requests

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage
from dify_plugin.errors.tool import ToolProviderCredentialValidationError


class GetDocumentContentTool(Tool):

    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage]:
        dataset_id = tool_parameters.get("dataset_id")
        document_name = tool_parameters.get("document_name")
        segment_index = tool_parameters.get("segment_index")

        if not self.runtime or not self.runtime.credentials:
            raise ToolProviderCredentialValidationError("Tool runtime or credentials are missing")

        api_base_url = self.runtime.credentials.get("api_base_url")
        api_key = self.runtime.credentials.get("api_key")

        if not api_base_url:
            raise ToolProviderCredentialValidationError("Knowledge API base URL is required.")
        if not api_key:
            raise ToolProviderCredentialValidationError("Knowledge API key is required.")

        if not dataset_id:
            yield self.create_text_message("Error: dataset_id parameter is required")
            return
            
        if not document_name:
            yield self.create_text_message("Error: document_name parameter is required")
            return

        url = f"{api_base_url.rstrip('/')}/dataset/documents/content"
        params = {
            "document_name": document_name,
            "dataset_id": dataset_id,
            "segment_index": int(segment_index)
        }
        headers = {
            "authorization": f"bearer {api_key}",
            "content-type": "application/json",
        }

        try:
            response = requests.get(url, headers=headers, params=params, timeout=60)
            response.raise_for_status()
            result = response.json()
            yield self.create_json_message(result)
        except Exception as e:
            yield self.create_text_message(f"Error fetching document content: {str(e)}")
