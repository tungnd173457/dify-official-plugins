from collections.abc import Generator
from typing import Any
import json
import requests

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage
from dify_plugin.errors.tool import ToolProviderCredentialValidationError


class GetDocumentWithMetadataFilterTool(Tool):

    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage]:
        dataset_id = tool_parameters.get("dataset_id")
        filter_conditions = tool_parameters.get("filter_conditions")

        if not self.runtime or not self.runtime.credentials:
            raise ToolProviderCredentialValidationError("Tool runtime or credentials are missing")

        api_base_url = self.runtime.credentials.get("api_base_url")
        api_key = self.runtime.credentials.get("api_key")

        if not api_base_url:
            raise ToolProviderCredentialValidationError("Knowledge API base URL is required.")
        if not api_key:
            raise ToolProviderCredentialValidationError("Knowledge API key is required.")

        # get the download url for each document
        headers = {
            "authorization": f"bearer {api_key}",
            "content-type": "application/json",
        }
        url = f"{api_base_url.rstrip('/')}/datasets/{dataset_id}/documents"
        try:
            response = requests.get(url, headers=headers, timeout=60)
            response.raise_for_status()
            data = response.json()
            filtered = self.filter_documents(data, filters=filter_conditions)

            yield self.create_json_message({
                "result": filtered
            })
        except Exception as e:
            data = {}
            yield self.create_text_message(f"Error: {str(e)}")

    def filter_documents(self, data, filters):
        """
        Filters documents in 'data' based on metadata values.
        Supports both dict and JSON string for filters.
        """
        # Parse filters if it's a string
        if isinstance(filters, str):
            try:
                filters = json.loads(filters)
            except json.JSONDecodeError:
                raise ValueError("Invalid JSON string for filters")

        if not isinstance(filters, dict):
            raise TypeError("filters must be a dict or JSON string representing a dict")

        result = []

        for item in data.get("data", []):
            metadata = {m["name"]: m["value"] for m in item.get("doc_metadata", [])}

            # Keep document if all filter conditions match
            if all(metadata.get(k) == v for k, v in filters.items()):
                result.append(item)

        return result
