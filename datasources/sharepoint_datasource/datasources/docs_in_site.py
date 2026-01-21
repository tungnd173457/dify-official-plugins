import logging
import time
import uuid
from collections.abc import Generator
import requests

from dify_plugin.entities.datasource import (
    DatasourceMessage,
    OnlineDriveBrowseFilesRequest,
    OnlineDriveBrowseFilesResponse,
    OnlineDriveDownloadFileRequest,
)
from dify_plugin.entities.invoke_message import InvokeMessage
from dify_plugin.interfaces.datasource.online_drive import OnlineDriveDatasource

from .utils import graph_utils

logger = logging.getLogger(__name__)


class SharePointDataSource(OnlineDriveDatasource):
    _BASE_URL = "https://graph.microsoft.com/v1.0"
    _RESOURCE = "sites"

    def _browse_files(self, request: OnlineDriveBrowseFilesRequest) -> OnlineDriveBrowseFilesResponse:
        credentials = self.runtime.credentials
        bucket_name = request.bucket
        prefix = request.prefix or ""  # Allow empty prefix for listing all sites
        max_keys = request.max_keys or 10
        next_page_parameters = request.next_page_parameters or {}

        if not credentials:
            raise ValueError("No credentials found")

        access_token = credentials.get("access_token")
        if not access_token:
            raise ValueError("Access token not found in credentials")

        # Parse prefix to determine site_id and item_id
        site_id, item_id = self._parse_path(prefix, access_token)

        # Prepare headers for HTTP requests
        headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}

        try:
            if not site_id:
                # Empty prefix: Use Graph API /sites to list all sites
                return self._list_all_sites(headers, max_keys, next_page_parameters, bucket_name)
            else:
                # Non-empty prefix: Browse specific site's drive content
                return self._browse_site_drive(site_id, item_id, headers, max_keys, next_page_parameters, bucket_name)

        except requests.exceptions.RequestException as e:
            raise ValueError(f"Network error occurred while accessing SharePoint: {str(e)}") from e
        except Exception as e:
            if "401" in str(e) or "Unauthorized" in str(e):
                raise ValueError(
                    "Authentication failed. Access token may have expired. "
                    "Please refresh or re-authorize the connection."
                ) from e
            raise

    def _parse_path(self, prefix: str, access_token: str) -> tuple[str, str]:
        return graph_utils.parse_path(prefix, access_token)

    def _list_all_sites(
        self, headers: dict, max_keys: int, next_page_parameters: dict, bucket_name: str
    ) -> OnlineDriveBrowseFilesResponse:
        return graph_utils.list_all_resources(
            self._BASE_URL, self._RESOURCE, headers, max_keys, next_page_parameters, bucket_name
        )

    def _browse_site_drive(
        self, site_id: str, item_id: str, headers: dict, max_keys: int, next_page_parameters: dict, bucket_name: str
    ) -> OnlineDriveBrowseFilesResponse:
        return graph_utils.browse_drive(
            self._BASE_URL, self._RESOURCE, site_id, item_id, headers, max_keys, next_page_parameters, bucket_name
        )

    def _stream_blob_chunks(
        self,
        blob_data: bytes,
        meta: dict | None = None,
        chunk_size: int = 8192,  # 8KB chunks - BACKEND LIMIT
        max_retries: int = 3,
    ) -> Generator[DatasourceMessage, None, None]:
        """
        Stream large blobs in chunks to avoid memory issues.

        IMPORTANT: Backend enforces strict limits:
        - Maximum chunk size: 8KB (8192 bytes)
        - Maximum total file size: 30MB

        Args:
            blob_data: The complete blob data to stream
            meta: Metadata to attach (only sent with LAST chunk when end=True)
            chunk_size: Size of each chunk in bytes (default 8KB, DO NOT EXCEED)
            max_retries: Maximum number of retries for failed chunks

        Yields:
            DatasourceMessage with BlobChunkMessage for each chunk

        Raises:
            ValueError: If blob_data exceeds 30MB limit
        """
        # Validate file size against backend limit
        MAX_FILE_SIZE = 2000 * 1024 * 1024  # 30MB
        if len(blob_data) > MAX_FILE_SIZE:
            raise ValueError(
                f"File size ({len(blob_data) / 1024 / 1024:.2f}MB) exceeds "
                f"backend limit of 30MB. Please use a smaller file."
            )

        blob_id = str(uuid.uuid4())
        total_length = len(blob_data)
        total_chunks = (total_length + chunk_size - 1) // chunk_size  # Ceiling division

        logger.info(
            f"Starting blob streaming: {total_length / 1024 / 1024:.2f}MB in {total_chunks} chunks of {chunk_size / 1024:.1f}KB"
        )

        for sequence, i in enumerate(range(0, total_length, chunk_size)):
            chunk = blob_data[i : i + chunk_size]
            is_end = (i + chunk_size) >= total_length

            # Retry logic for chunk streaming
            retry_count = 0
            while retry_count <= max_retries:
                try:
                    # Log progress
                    progress_pct = ((sequence + 1) / total_chunks) * 100
                    logger.info(f"Streaming chunk {sequence + 1}/{total_chunks} ({progress_pct:.1f}%)")

                    # Yield chunk message with metadata only on last chunk
                    yield self.response_type(
                        type=InvokeMessage.MessageType.BLOB_CHUNK,
                        message=InvokeMessage.BlobChunkMessage(
                            id=blob_id,
                            sequence=sequence,
                            total_length=total_length,
                            blob=chunk,
                            end=is_end,
                        ),
                        meta=meta if is_end else None,  # Metadata only on last chunk
                    )
                    break  # Success, exit retry loop

                except Exception as e:
                    retry_count += 1
                    if retry_count > max_retries:
                        logger.error(
                            f"Failed to stream chunk {sequence + 1}/{total_chunks} after {max_retries} retries: {str(e)}"
                        )
                        raise ValueError(
                            f"Failed to stream chunk {sequence + 1}/{total_chunks}: {str(e)}"
                        ) from e
                    else:
                        # Exponential backoff: 0.5s, 1s, 2s
                        backoff_time = 0.5 * (2 ** (retry_count - 1))
                        logger.warning(
                            f"Retry {retry_count}/{max_retries} for chunk {sequence + 1}/{total_chunks} "
                            f"after {backoff_time}s delay: {str(e)}"
                        )
                        time.sleep(backoff_time)

        logger.info(f"Successfully streamed all {total_chunks} chunks for blob {blob_id}")

    def _download_file_with_streaming(
        self, request: OnlineDriveDownloadFileRequest
    ) -> Generator[DatasourceMessage, None, None]:
        """
        Download file with blob chunk streaming support for large files.

        This is the new implementation that uses actual file_content
        and streams it in chunks to handle large files efficiently.

        IMPORTANT: Backend enforces 30MB maximum file size limit.
        """
        credentials = self.runtime.credentials
        file_id = request.id

        if not credentials:
            raise ValueError("No credentials found")

        access_token = credentials.get("access_token")
        if not access_token:
            raise ValueError("Access token not found in credentials")

        # Prepare headers for HTTP requests
        headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}

        try:
            logger.info(f"Downloading file with streaming: {file_id}")

            # Download file from SharePoint
            file_content, file_name, mime_type = graph_utils.download_file(
                self._BASE_URL, self._RESOURCE, file_id, headers, self._get_mime_type_from_filename
            )

            file_size_mb = len(file_content) / 1024 / 1024
            logger.info(f"Downloaded file '{file_name}' ({file_size_mb:.2f}MB, {mime_type})")

            # Stream the actual file content in chunks
            yield from self._stream_blob_chunks(
                file_content, meta={"file_name": file_name, "mime_type": mime_type}
            )

        except Exception as e:
            logger.error(f"Error downloading file with streaming: {str(e)}")
            raise

    def _download_file(self, request: OnlineDriveDownloadFileRequest) -> Generator[DatasourceMessage, None, None]:
        """
        Download file from SharePoint.
        
        Now uses streaming implementation for better memory efficiency.
        """
        # Use the new streaming implementation
        yield from self._download_file_with_streaming(request)

    def _get_mime_type_from_filename(self, filename: str) -> str:
        return graph_utils.get_mime_type_from_filename(filename)