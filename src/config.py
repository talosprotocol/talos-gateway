import os
import sys
from typing import Optional
from talos_config import ConfigurationLoader, ConfigurationError

class GatewayConfig:
    def __init__(self):
        loader = ConfigurationLoader("gateway")
        
        # Legacy Shim: Map old env vars to config dict before loading
        # This allows the loader to prioritize them if they exist (treated as defaults or pre-load)
        legacy_defaults = {}
        if os.getenv("TALOS_AUDIT_URL"):
            legacy_defaults["audit_url"] = os.getenv("TALOS_AUDIT_URL")
            print("WARNING: Using legacy env var TALOS_AUDIT_URL. Please update to config.yaml or TALOS__AUDIT_URL.", file=sys.stderr)
            
        if os.getenv("OLLAMA_URL"):
            legacy_defaults["ollama_url"] = os.getenv("OLLAMA_URL")
            
        if os.getenv("TGA_URL"):
            legacy_defaults["tga_url"] = os.getenv("TGA_URL")
            
        if os.getenv("DEV_MODE"):
            legacy_defaults["dev_mode"] = os.getenv("DEV_MODE").lower() == "true"

        # Load Configuration
        self._data = loader.load(defaults=legacy_defaults)
        
        # Verify Contracts
        # In a real app we might load this from a version file or package
        self.contracts_version = "1.2.0" 
        self.config_version = self._data.get("config_version", "1.0")
        
        # Calculate digest
        self.config_digest = loader.validate()

    @property
    def audit_url(self) -> str:
        return self._data.get("audit_url", "http://talos-audit-service:8001")

    @property
    def ollama_url(self) -> str:
        return self._data.get("ollama_url", "http://ollama:11434")

    @property
    def tga_url(self) -> str:
        return self._data.get("tga_url", "http://talos-governance-agent:8083")

    @property
    def dev_mode(self) -> bool:
        return self._data.get("dev_mode", False)
        
    @property
    def region(self) -> str:
        return self._data.get("global", {}).get("region", os.getenv("TALOS_REGION", "local"))

settings = GatewayConfig()
