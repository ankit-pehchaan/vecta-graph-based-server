"""AWS Secrets Manager integration utility."""
import json
import logging
from typing import Optional, Dict, Any
import boto3
from botocore.exceptions import ClientError, NoCredentialsError, PartialCredentialsError

logger = logging.getLogger(__name__)


class AWSSecretsManager:
    """AWS Secrets Manager client wrapper with error handling."""

    def __init__(self, region_name: str = "us-east-1"):
        """
        Initialize AWS Secrets Manager client.

        Args:
            region_name: AWS region where secrets are stored
        """
        self.region_name = region_name
        self._client: Optional[Any] = None
        self._available = False
        self._initialize_client()

    def _initialize_client(self) -> None:
        """Initialize boto3 client with error handling."""
        try:
            self._client = boto3.client(
                service_name='secretsmanager',
                region_name=self.region_name
            )
            # Test credentials by making a simple call
            self._client.list_secrets(MaxResults=1)
            self._available = True
            logger.info(f"AWS Secrets Manager initialized successfully in region {self.region_name}")
        except (NoCredentialsError, PartialCredentialsError) as e:
            logger.warning(f"AWS credentials not found or incomplete: {e}")
            self._available = False
        except ClientError as e:
            logger.warning(f"AWS Secrets Manager client error: {e}")
            self._available = False
        except Exception as e:
            logger.warning(f"Unexpected error initializing AWS Secrets Manager: {e}")
            self._available = False

    @property
    def is_available(self) -> bool:
        """Check if AWS Secrets Manager is available and configured."""
        return self._available

    def get_secret(self, secret_name: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve secret from AWS Secrets Manager.

        Args:
            secret_name: Name or ARN of the secret

        Returns:
            Dictionary containing secret key-value pairs, or None if unavailable
        """
        if not self.is_available or not self._client:
            logger.debug(f"AWS Secrets Manager not available, skipping secret retrieval: {secret_name}")
            return None

        try:
            response = self._client.get_secret_value(SecretId=secret_name)

            # Secrets can be stored as SecretString (JSON) or SecretBinary
            if 'SecretString' in response:
                secret_string = response['SecretString']
                try:
                    # Try to parse as JSON
                    secret_dict = json.loads(secret_string)
                    logger.info(f"Successfully retrieved secret: {secret_name}")
                    return secret_dict
                except json.JSONDecodeError:
                    # If not JSON, return as single-value dict
                    logger.info(f"Successfully retrieved non-JSON secret: {secret_name}")
                    return {"value": secret_string}
            else:
                # Binary secrets not commonly used for app config
                logger.warning(f"Secret {secret_name} is binary, not supported")
                return None

        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'ResourceNotFoundException':
                logger.info(f"Secret not found in AWS Secrets Manager: {secret_name}")
            elif error_code == 'InvalidRequestException':
                logger.error(f"Invalid request for secret {secret_name}: {e}")
            elif error_code == 'InvalidParameterException':
                logger.error(f"Invalid parameter for secret {secret_name}: {e}")
            elif error_code == 'DecryptionFailure':
                logger.error(f"Decryption failed for secret {secret_name}: {e}")
            elif error_code == 'InternalServiceError':
                logger.error(f"AWS internal service error for secret {secret_name}: {e}")
            else:
                logger.error(f"ClientError retrieving secret {secret_name}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error retrieving secret {secret_name}: {e}")
            return None

    def get_secret_value(self, secret_name: str, key: str, default: Any = None) -> Any:
        """
        Get a specific value from a secret.

        Args:
            secret_name: Name or ARN of the secret
            key: Key within the secret JSON
            default: Default value if key not found

        Returns:
            Secret value or default
        """
        secret_dict = self.get_secret(secret_name)
        if secret_dict is None:
            return default
        return secret_dict.get(key, default)


def load_secrets_from_aws(
    secret_name: str,
    region_name: str = "us-east-1",
    required_keys: Optional[list[str]] = None
) -> Dict[str, Any]:
    """
    Load secrets from AWS Secrets Manager with fallback handling.

    Args:
        secret_name: Name of the secret in AWS Secrets Manager
        region_name: AWS region (default: us-east-1)
        required_keys: Optional list of required keys to validate

    Returns:
        Dictionary of secret values (empty if AWS unavailable)
    """
    if not secret_name:
        logger.info("No AWS secret name provided, skipping AWS Secrets Manager")
        return {}

    manager = AWSSecretsManager(region_name=region_name)

    if not manager.is_available:
        logger.info("AWS Secrets Manager unavailable, will use local environment variables")
        return {}

    secrets = manager.get_secret(secret_name)

    if secrets is None:
        logger.info(f"Could not retrieve secret '{secret_name}', will use local environment variables")
        return {}

    # Validate required keys if specified
    if required_keys:
        missing_keys = [key for key in required_keys if key not in secrets]
        if missing_keys:
            logger.warning(f"Missing required keys in AWS secret: {missing_keys}")

    return secrets
