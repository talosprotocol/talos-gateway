import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from typing import Tuple, Optional

class SecretEncryptor:
    """Helper for encrypting/decrypting secrets using AES-GCM."""
    
    def __init__(self, key: Optional[bytes] = None):
        # The master key (KEK) should be provided or loaded from env
        self.key = key or os.getenv("TALOS_MASTER_KEY", "0" * 32).encode()
        if len(self.key) != 32:
            # Pad or truncate for 256-bit AES
            self.key = (self.key + b"0" * 32)[:32]
        self.aesgcm = AESGCM(self.key)

    def encrypt(self, plaintext: str) -> Tuple[str, str, str]:
        """Encrypts a string and returns (ciphertext_hex, iv_hex, tag_hex)."""
        iv = os.urandom(12) # Standard 96-bit IV
        data = plaintext.encode()
        # AESGCM combines ciphertext and tag in its return value
        combined = self.aesgcm.encrypt(iv, data, None)
        
        tag_len = 16
        ciphertext = combined[:-tag_len]
        tag = combined[-tag_len:]
        
        return ciphertext.hex(), iv.hex(), tag.hex()

    def decrypt(self, ciphertext_hex: str, iv_hex: str, tag_hex: str) -> str:
        """Decrypts a secret and returns the plaintext."""
        ciphertext = bytes.fromhex(ciphertext_hex)
        iv = bytes.fromhex(iv_hex)
        tag = bytes.fromhex(tag_hex)
        
        combined = ciphertext + tag
        plaintext_bytes = self.aesgcm.decrypt(iv, combined, None)
        return plaintext_bytes.decode()
