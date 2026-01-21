from collections import defaultdict
from collections.abc import Generator
from typing import Any
import json
import requests

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage
from dify_plugin.errors.tool import ToolProviderCredentialValidationError


class GroupBrandWithProjectTool(Tool):

    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage]:
        dataset_id = tool_parameters.get("dataset_id")
        group_field = tool_parameters.get("group_field")
        value_field = tool_parameters.get("value_field")
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
            field_values = self.group_brand_to_document_types(data, group_field, value_field, filter_conditions)

            yield self.create_json_message({
                "result": field_values
            })
        except Exception as e:
            data = {}
            yield self.create_text_message(f"Error: {str(e)}")

    def group_brand_to_document_types(self, data, group_field, value_field, filters=None):
        """
        Group metadata values by another metadata field, with optional filtering.

        Args:
            data (dict): The JSON object containing a "data" list.
            group_field (str): The metadata field to group by (e.g. "brand_name").
            value_field (str): The metadata field whose values will be collected (e.g. "document_type").
            filters (dict|str|None): Optional metadata filters (dict or JSON string).

        Returns:
            dict: { group_field_value: [value_field_value1, value_field_value2, ...] }
        """
        # Parse filters if it's a JSON string
        if isinstance(filters, str) and filters.strip():
            try:
                filters = json.loads(filters)
            except json.JSONDecodeError:
                raise ValueError("Invalid JSON string for filters")

        if filters is not None and not isinstance(filters, dict):
            raise TypeError("filters must be a dict, JSON string, or None")

        grouped = defaultdict(set)

        for item in data.get("data", []):
            doc_metadata = item.get("doc_metadata") or []
            metadata = {m.get("name"): m.get("value") for m in doc_metadata if isinstance(m, dict)}

            # Apply filters if provided
            if filters and not all(metadata.get(k) == v for k, v in filters.items()):
                continue

            group_key = metadata.get(group_field)
            value = metadata.get(value_field)

            if group_key and value:
                grouped[group_key].add(value)

        # Convert sets to sorted lists for clean output
        return {k: sorted(list(v)) for k, v in grouped.items()}
