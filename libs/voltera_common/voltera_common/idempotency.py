"""Helpers de idempotencia (Powertools sobre DynamoDB). Las tablas usan PK `facturaId` y TTL `expiresAt`."""
from __future__ import annotations

import os
from typing import Any


def persistence_layer(table_name: str | None = None, key_attr: str = "facturaId", boto3_client: Any = None):
    from aws_lambda_powertools.utilities.idempotency import DynamoDBPersistenceLayer

    return DynamoDBPersistenceLayer(
        table_name=table_name or os.environ["TABLE_IDEMPOTENCIA"],
        key_attr=key_attr,
        expiry_attr=os.environ.get("IDEMPOTENCY_TTL_ATTR", "expiresAt"),
        boto3_client=boto3_client,
    )


def idempotency_config(event_key_jmespath: str, expires_after_seconds: int = 3600, **kwargs: Any):
    from aws_lambda_powertools.utilities.idempotency import IdempotencyConfig

    return IdempotencyConfig(event_key_jmespath=event_key_jmespath, expires_after_seconds=expires_after_seconds, **kwargs)
