"""
Bootstrap module for Talos Gateway.
Sets up Dependency Injection container with SDK adapters.
"""

from dotenv import load_dotenv
from talos_sdk.container import Container, get_container

# Ensure env is loaded early
load_dotenv()
from talos_sdk.ports.audit_store import IAuditStorePort
from talos_sdk.ports.crypto import ICryptoPort
from talos_sdk.ports.hash import IHashPort
from talos_sdk.adapters.memory_store import InMemoryAuditStore
from talos_sdk.adapters.crypto import Ed25519CryptoAdapter
from talos_sdk.adapters.hash import NativeHashAdapter


def bootstrap() -> Container:
    """Initialize the DI container with default adapters."""
    container = get_container()

    # Register adapters
    import os
    storage_type = os.getenv("TALOS_STORAGE_TYPE", "memory")
    
    if storage_type == "postgres":
        from src.adapters.postgres_store import PostgresAuditStore
        container.register(IAuditStorePort, PostgresAuditStore())
    else:
        container.register(IAuditStorePort, InMemoryAuditStore())

    container.register(ICryptoPort, Ed25519CryptoAdapter())
    container.register(IHashPort, NativeHashAdapter())

    return container


# Application container instance
_container: Container | None = None


def get_app_container() -> Container:
    """Get the application's DI container."""
    global _container
    if _container is None:
        _container = bootstrap()
    return _container
