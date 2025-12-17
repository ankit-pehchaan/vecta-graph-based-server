"""AWS KMS Service for managing user encryption keys."""
import boto3
from botocore.exceptions import ClientError
from typing import Optional, Tuple, Union
from uuid import UUID
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.user_kms import UserKmsMapping, KmsTier
from app.core.config import settings

# Type alias for user ID (can be int or UUID depending on database schema)
UserIdType = Union[int, UUID]


class KmsService:
    """
    Service for creating and managing AWS KMS keys for users.

    Each user gets a dedicated KMS key for encrypting their sensitive documents.
    """

    def __init__(self, session: Optional[AsyncSession] = None):
        self.session = session
        self.kms_client = boto3.client(
            'kms',
            region_name=getattr(settings, 'AWS_REGION', 'ap-southeast-2')
        )
        self.key_policy_template = self._get_key_policy_template()

    def _get_key_policy_template(self) -> str:
        """Get the default key policy for user KMS keys."""
        # This policy allows the root account and the application to use the key
        account_id = self._get_account_id()
        return f'''{{
    "Version": "2012-10-17",
    "Id": "vecta-user-key-policy",
    "Statement": [
        {{
            "Sid": "Enable IAM User Permissions",
            "Effect": "Allow",
            "Principal": {{
                "AWS": "arn:aws:iam::{account_id}:root"
            }},
            "Action": "kms:*",
            "Resource": "*"
        }},
        {{
            "Sid": "Allow application to use the key",
            "Effect": "Allow",
            "Principal": {{
                "AWS": "*"
            }},
            "Action": [
                "kms:Encrypt",
                "kms:Decrypt",
                "kms:GenerateDataKey",
                "kms:GenerateDataKeyWithoutPlaintext",
                "kms:DescribeKey"
            ],
            "Resource": "*",
            "Condition": {{
                "StringEquals": {{
                    "kms:CallerAccount": "{account_id}"
                }}
            }}
        }}
    ]
}}'''

    def _get_account_id(self) -> str:
        """Get the AWS account ID."""
        try:
            sts_client = boto3.client('sts', region_name=getattr(settings, 'AWS_REGION', 'ap-southeast-2'))
            return sts_client.get_caller_identity()['Account']
        except Exception:
            # Fallback - will be replaced with actual account ID when key is created
            return "ACCOUNT_ID"

    async def create_user_key(
        self,
        user_id: UserIdType,
        user_email: str,
        tier: str = KmsTier.FREE.value
    ) -> Tuple[str, str, str]:
        """
        Create a new KMS key for a user.

        Args:
            user_id: The user's database ID
            user_email: The user's email (for tagging)
            tier: The user's tier level

        Returns:
            Tuple of (key_arn, key_id, alias)

        Raises:
            Exception: If key creation fails
        """
        # Create a unique alias for this user's key
        alias_name = f"alias/vecta-user-{user_id}"
        description = f"Vecta encryption key for user {user_id}"

        try:
            # Create the KMS key
            response = self.kms_client.create_key(
                Description=description,
                KeyUsage='ENCRYPT_DECRYPT',
                KeySpec='SYMMETRIC_DEFAULT',
                Origin='AWS_KMS',
                Tags=[
                    {'TagKey': 'Application', 'TagValue': 'Vecta'},
                    {'TagKey': 'UserId', 'TagValue': str(user_id)},
                    {'TagKey': 'UserEmail', 'TagValue': user_email},
                    {'TagKey': 'Tier', 'TagValue': tier},
                    {'TagKey': 'Environment', 'TagValue': getattr(settings, 'ENVIRONMENT', 'dev')}
                ]
            )

            key_arn = response['KeyMetadata']['Arn']
            key_id = response['KeyMetadata']['KeyId']

            # Create an alias for easier reference
            try:
                self.kms_client.create_alias(
                    AliasName=alias_name,
                    TargetKeyId=key_id
                )
            except ClientError as e:
                # Alias might already exist, try to update it
                if e.response['Error']['Code'] == 'AlreadyExistsException':
                    self.kms_client.update_alias(
                        AliasName=alias_name,
                        TargetKeyId=key_id
                    )
                else:
                    raise

            print(f"[KMS] Created key for user {user_id}: {key_id}")
            return key_arn, key_id, alias_name

        except ClientError as e:
            print(f"[KMS] Failed to create key for user {user_id}: {e}")
            raise Exception(f"Failed to create KMS key: {str(e)}")

    async def save_user_key_mapping(
        self,
        user_id: UserIdType,
        key_arn: str,
        key_id: str,
        alias: str,
        tier: str = KmsTier.FREE.value
    ) -> UserKmsMapping:
        """
        Save the user-to-KMS key mapping in the database.

        Args:
            user_id: The user's database ID
            key_arn: The KMS key ARN
            key_id: The KMS key ID
            alias: The key alias
            tier: The user's tier level

        Returns:
            The created UserKmsMapping record
        """
        if not self.session:
            raise ValueError("Database session not provided")

        mapping = UserKmsMapping(
            user_id=user_id,
            kms_key_arn=key_arn,
            kms_key_id=key_id,
            tier=tier,
            alias=alias
        )

        self.session.add(mapping)
        await self.session.commit()
        await self.session.refresh(mapping)

        print(f"[KMS] Saved key mapping for user {user_id}")
        return mapping

    async def create_and_save_user_key(
        self,
        user_id: UserIdType,
        user_email: str,
        tier: str = KmsTier.FREE.value
    ) -> UserKmsMapping:
        """
        Create a KMS key and save the mapping in one operation.

        This is the main method to call during user signup.

        Args:
            user_id: The user's database ID
            user_email: The user's email
            tier: The user's tier level

        Returns:
            The created UserKmsMapping record
        """
        # Create the key in AWS KMS
        key_arn, key_id, alias = await self.create_user_key(user_id, user_email, tier)

        # Save the mapping in the database
        mapping = await self.save_user_key_mapping(
            user_id=user_id,
            key_arn=key_arn,
            key_id=key_id,
            alias=alias,
            tier=tier
        )

        return mapping

    async def get_user_key(self, user_id: UserIdType) -> Optional[UserKmsMapping]:
        """
        Get the KMS key mapping for a user.

        Args:
            user_id: The user's database ID

        Returns:
            The UserKmsMapping record or None if not found
        """
        if not self.session:
            raise ValueError("Database session not provided")

        result = await self.session.execute(
            select(UserKmsMapping).where(UserKmsMapping.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def update_user_tier(self, user_id: UserIdType, new_tier: str) -> Optional[UserKmsMapping]:
        """
        Update a user's tier in the KMS mapping.

        Args:
            user_id: The user's database ID
            new_tier: The new tier level

        Returns:
            The updated UserKmsMapping record or None if not found
        """
        if not self.session:
            raise ValueError("Database session not provided")

        mapping = await self.get_user_key(user_id)
        if not mapping:
            return None

        mapping.tier = new_tier
        mapping.updated_at = datetime.now(timezone.utc)

        # Update the tag on the KMS key as well
        try:
            self.kms_client.tag_resource(
                KeyId=mapping.kms_key_id,
                Tags=[{'TagKey': 'Tier', 'TagValue': new_tier}]
            )
        except ClientError as e:
            print(f"[KMS] Warning: Failed to update KMS key tag: {e}")

        await self.session.commit()
        await self.session.refresh(mapping)

        return mapping

    def schedule_key_deletion(self, key_id: str, pending_window_days: int = 7) -> bool:
        """
        Schedule a KMS key for deletion.

        Args:
            key_id: The KMS key ID
            pending_window_days: Days to wait before deletion (7-30)

        Returns:
            True if scheduled successfully
        """
        try:
            self.kms_client.schedule_key_deletion(
                KeyId=key_id,
                PendingWindowInDays=pending_window_days
            )
            print(f"[KMS] Scheduled key {key_id} for deletion in {pending_window_days} days")
            return True
        except ClientError as e:
            print(f"[KMS] Failed to schedule key deletion: {e}")
            return False
