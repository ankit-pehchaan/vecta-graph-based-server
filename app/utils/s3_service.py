import base64
import httpx
from typing import Tuple
from app.core.config import settings


class DocumentUploadService:
    """
    Service for uploading documents to the Vecta Redaction Lambda.

    The Lambda handles:
    1. PII redaction (names, addresses, account numbers, etc.)
    2. Uploading redacted file to S3
    3. Returning the S3 URL of the redacted document
    """

    def __init__(self):
        self.lambda_url = getattr(
            settings,
            'DOC_UPLOAD_LAMBDA_URL',
            'https://your-api-id.execute-api.ap-southeast-2.amazonaws.com/Prod/upload/'
        )
        self.timeout = 60.0  # Lambda might take time for large documents

    async def upload_and_redact(
        self,
        file_content: bytes,
        filename: str,
        mime_type: str,
        auth_token: str,
        pii_strategy: str = "HYBRID"
    ) -> Tuple[str, dict]:
        """
        Upload document to Redaction Lambda via API Gateway.

        The Lambda will:
        1. Redact PII from the document
        2. Upload redacted version to S3
        3. Return the S3 URL

        Args:
            file_content: File bytes
            filename: Original filename
            mime_type: MIME type of the file (application/pdf, text/csv, etc.)
            auth_token: JWT token to forward to Lambda (includes user identity)
            pii_strategy: Redaction strategy - "HYBRID", "AWS_ONLY", or "LOCAL_ONLY"

        Returns:
            Tuple of (s3_url, full_response_data)

        Raises:
            ValueError: If Lambda call fails
        """
        # Encode file to base64
        file_b64 = base64.b64encode(file_content).decode('utf-8')

        # Prepare payload for Lambda
        payload = {
            "file": file_b64,
            "fileName": filename,
            "mimeType": mime_type,
            "metadata": {
                "pii_strategy": pii_strategy
            }
        }

        # Prepare headers - forward the auth token
        headers = {
            "Authorization": auth_token,
            "Content-Type": "application/json"
        }

        try:
            print(f"[DocumentUpload] Calling Lambda at: {self.lambda_url}")
            print(f"[DocumentUpload] File: {filename}, MIME: {mime_type}, Size: {len(file_content)} bytes")

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.lambda_url,
                    json=payload,
                    headers=headers,
                    timeout=self.timeout
                )

            print(f"[DocumentUpload] Lambda response status: {response.status_code}")

            # Handle non-200 responses
            if response.status_code != 200:
                try:
                    error_detail = response.json()
                    error_msg = error_detail.get('message', response.text)
                    print(f"[DocumentUpload] Lambda error: {error_detail}")
                except Exception:
                    error_msg = response.text
                    print(f"[DocumentUpload] Lambda error (raw): {error_msg}")
                raise ValueError(f"Lambda redaction failed ({response.status_code}): {error_msg}")

            # Parse successful response
            result = response.json()
            print(f"[DocumentUpload] Lambda response: {result}")

            # Extract S3 URL from response
            data = result.get('data', {})
            s3_url = data.get('s3Url')

            if not s3_url:
                raise ValueError(f"Lambda did not return S3 URL. Response: {result}")

            print(f"[DocumentUpload] Success! S3 URL: {s3_url}")
            return s3_url, data

        except httpx.TimeoutException:
            print(f"[DocumentUpload] Timeout after {self.timeout}s")
            raise ValueError("Document processing timed out. Please try with a smaller file.")
        except httpx.RequestError as e:
            print(f"[DocumentUpload] Request error: {e}")
            raise ValueError(f"Failed to connect to document processing service: {str(e)}")
        except Exception as e:
            print(f"[DocumentUpload] Unexpected error: {type(e).__name__}: {e}")
            raise

    def get_mime_type(self, filename: str) -> str:
        """Get MIME type from filename extension."""
        ext = filename.split('.')[-1].lower() if '.' in filename else ''
        mime_types = {
            'pdf': 'application/pdf',
            'csv': 'text/csv',
            'txt': 'text/plain',
            'png': 'image/png',
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg'
        }
        return mime_types.get(ext, 'application/octet-stream')


# Backwards compatibility alias
S3Service = DocumentUploadService
