import csv
import io
from typing import Tuple, Optional
from urllib.parse import urlparse
import boto3
from botocore.exceptions import ClientError
import pdfplumber
import aws_encryption_sdk
from aws_encryption_sdk import CommitmentPolicy


class DocumentParser:
    """Download, decrypt, and parse documents from S3 URLs."""

    def __init__(self):
        self.s3_client = boto3.client('s3')
        # Initialize AWS Encryption SDK client
        self.encryption_client = aws_encryption_sdk.EncryptionSDKClient(
            commitment_policy=CommitmentPolicy.REQUIRE_ENCRYPT_REQUIRE_DECRYPT
        )

    def _decrypt_content(self, ciphertext: bytes, kms_key_arn: str) -> bytes:
        """
        Decrypt content that was encrypted by Vecta Lambda using AWS Encryption SDK.

        Args:
            ciphertext: Encrypted file bytes
            kms_key_arn: User's KMS key ARN for decryption

        Returns:
            Decrypted plaintext bytes
        """
        # Strict Master Key Provider: Ensure we only decrypt using the expected key
        master_key_provider = aws_encryption_sdk.StrictAwsKmsMasterKeyProvider(
            key_ids=[kms_key_arn]
        )

        # Decrypt
        plaintext, header = self.encryption_client.decrypt(
            source=ciphertext,
            key_provider=master_key_provider
        )

        print(f"[DocumentParser] Decrypted file using KMS key: {kms_key_arn[:50]}...")
        return plaintext

    async def download_and_parse(
        self,
        s3_url: str,
        kms_key_arn: Optional[str] = None
    ) -> Tuple[str, str]:
        """
        Download file from S3, decrypt if needed, and extract text content.

        Args:
            s3_url: S3 URL in format s3://bucket/key or https://bucket.s3.region.amazonaws.com/key
            kms_key_arn: User's KMS key ARN for decryption (required for encrypted files)

        Returns:
            Tuple of (extracted_text, file_type)

        Raises:
            ValueError: If URL format is invalid or file type is unsupported
            ClientError: If S3 download fails
        """
        bucket, key = self._parse_s3_url(s3_url)

        try:
            response = self.s3_client.get_object(Bucket=bucket, Key=key)
            content = response['Body'].read()
            content_type = response.get('ContentType', '')
            print(f"[DocumentParser] Downloaded {len(content)} bytes from S3")
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            raise ValueError(f"Failed to download from S3: {error_code}") from e

        # Decrypt content if KMS key is provided
        if kms_key_arn:
            try:
                content = self._decrypt_content(content, kms_key_arn)
                print(f"[DocumentParser] Decrypted to {len(content)} bytes")
            except Exception as e:
                print(f"[DocumentParser] Decryption failed: {e}")
                raise ValueError(f"Failed to decrypt file: {str(e)}") from e

        file_type = self._get_file_type(key, content_type)

        if file_type == 'pdf':
            text = self._parse_pdf(content)
        elif file_type == 'csv':
            text = self._parse_csv(content)
        elif file_type == 'txt':
            text = content.decode('utf-8', errors='ignore')
        else:
            raise ValueError(f"Unsupported file type: {file_type}")

        return text, file_type

    def _parse_s3_url(self, s3_url: str) -> Tuple[str, str]:
        """
        Parse S3 URL to extract bucket and key.

        Supports:
        - s3://bucket-name/path/to/file.pdf
        - https://bucket-name.s3.region.amazonaws.com/path/to/file.pdf
        - https://s3.region.amazonaws.com/bucket-name/path/to/file.pdf
        """
        parsed = urlparse(s3_url)

        if parsed.scheme == 's3':
            bucket = parsed.netloc
            key = parsed.path.lstrip('/')
        elif parsed.scheme in ('http', 'https'):
            host = parsed.netloc
            path = parsed.path.lstrip('/')

            if '.s3.' in host or host.startswith('s3.'):
                # Virtual-hosted style: bucket.s3.region.amazonaws.com
                if '.s3.' in host:
                    bucket = host.split('.s3.')[0]
                    key = path
                # Path style: s3.region.amazonaws.com/bucket/key
                else:
                    parts = path.split('/', 1)
                    bucket = parts[0]
                    key = parts[1] if len(parts) > 1 else ''
            else:
                raise ValueError(f"Invalid S3 URL format: {s3_url}")
        else:
            raise ValueError(f"Invalid S3 URL scheme: {parsed.scheme}")

        if not bucket or not key:
            raise ValueError(f"Could not parse bucket/key from URL: {s3_url}")

        return bucket, key

    def _parse_pdf(self, content: bytes) -> str:
        """
        Extract text from PDF using pdfplumber (better for tables).

        Args:
            content: PDF file bytes

        Returns:
            Extracted text content
        """
        text_parts = []

        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                # Extract regular text
                page_text = page.extract_text() or ""

                # Extract tables and format them
                tables = page.extract_tables()
                table_text = ""
                for table in tables:
                    if table:
                        table_text += self._format_table(table) + "\n"

                if page_text or table_text:
                    text_parts.append(f"--- Page {page_num} ---\n{page_text}\n{table_text}")

        return "\n".join(text_parts)

    def _format_table(self, table: list) -> str:
        """Format a table as readable text."""
        if not table:
            return ""

        lines = []
        for row in table:
            if row:
                # Filter out None values and join with | separator
                cells = [str(cell) if cell is not None else "" for cell in row]
                lines.append(" | ".join(cells))

        return "\n".join(lines)

    def _parse_csv(self, content: bytes) -> str:
        """
        Parse CSV and format as readable text.

        Args:
            content: CSV file bytes

        Returns:
            Formatted CSV content as text
        """
        text_content = content.decode('utf-8', errors='ignore')
        reader = csv.reader(io.StringIO(text_content))

        lines = []
        headers = None

        for i, row in enumerate(reader):
            if i == 0:
                headers = row
                lines.append("Headers: " + " | ".join(row))
                lines.append("-" * 50)
            else:
                if headers:
                    # Format as key: value pairs
                    pairs = [f"{headers[j]}: {row[j]}" for j in range(min(len(headers), len(row)))]
                    lines.append("\n".join(pairs))
                    lines.append("-" * 30)
                else:
                    lines.append(" | ".join(row))

        return "\n".join(lines)

    def _get_file_type(self, s3_key: str, content_type: str) -> str:
        """
        Determine file type from extension or content-type.

        Args:
            s3_key: S3 object key (path)
            content_type: Content-Type header from S3

        Returns:
            File type string: 'pdf', 'csv', 'txt', or 'unknown'
        """
        # First try extension
        key_lower = s3_key.lower()
        if key_lower.endswith('.pdf'):
            return 'pdf'
        elif key_lower.endswith('.csv'):
            return 'csv'
        elif key_lower.endswith('.txt'):
            return 'txt'

        # Fall back to content type
        content_type_lower = content_type.lower()
        if 'pdf' in content_type_lower:
            return 'pdf'
        elif 'csv' in content_type_lower or 'comma-separated' in content_type_lower:
            return 'csv'
        elif 'text/plain' in content_type_lower:
            return 'txt'

        return 'unknown'
