from collections.abc import Generator
from typing import Any
import json
import requests

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage
from dify_plugin.errors.tool import ToolProviderCredentialValidationError


class GetFieldValuesWithMetadataFilterTool(Tool):

    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage]:
        dataset_id = tool_parameters.get("dataset_id")
        field_name = tool_parameters.get("field_name")
        limit = tool_parameters.get("limit")
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
        params = {
            "page": 1,
            "limit": int(limit),
        }
        url = f"{api_base_url.rstrip('/')}/datasets/{dataset_id}/documents"
        try:
            response = requests.get(url, headers=headers, params=params, timeout=60)
            response.raise_for_status()
            data = response.json()
            field_values = self.get_metadata_field_values(data, filter_conditions, field_name)

            yield self.create_json_message({
                "result": field_values
            })
        except Exception as e:
            data = {}
            yield self.create_text_message(f"Error: {str(e)}")

    def filter_documents(self, data, filters):
        """Filter documents by metadata fields."""
        if isinstance(filters, str):
            try:
                filters = json.loads(filters)
            except json.JSONDecodeError:
                raise ValueError("Invalid JSON string for filters")

        if not isinstance(filters, dict):
            raise TypeError("filters must be a dict or JSON string representing a dict")

        result = []
        for item in data.get("data", []):
            doc_metadata = item.get("doc_metadata") or []
            metadata = {m["name"]: m["value"] for m in doc_metadata if isinstance(m, dict)}

            if all(metadata.get(k) == v for k, v in filters.items()):
                result.append(item)

        return result


    def get_metadata_field_values(self, data, filters, field_name):
        """
        Get unique metadata values for a given field from filtered documents.

        Args:
            data (dict): JSON object with "data" key.
            filters (dict|str): Filter conditions (dict or JSON string).
            field_name (str): Metadata field name to extract (e.g. "brand_name").

        Returns:
            list: Unique list of metadata values.
        """
        filtered_docs = self.filter_documents(data, filters)
        values = set()  # use set for uniqueness

        for doc in filtered_docs:
            doc_metadata = doc.get("doc_metadata") or []
            for meta in doc_metadata:
                if isinstance(meta, dict) and meta.get("name") == field_name:
                    values.add(meta.get("value"))
                    break  # assume one per doc

        return list(values)
