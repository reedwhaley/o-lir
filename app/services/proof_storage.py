from __future__ import annotations

import hashlib
from pathlib import Path

from app.config import get_settings


class ProofStorageService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.root = Path(self.settings.proof_storage_root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save_proof(
        self,
        *,
        tournament_id: str,
        entrant_id: str,
        race_number: int,
        original_filename: str,
        content: bytes,
    ) -> tuple[str, str, int]:
        sha256 = hashlib.sha256(content).hexdigest()
        suffix = Path(original_filename).suffix or '.bin'
        target_dir = self.root / tournament_id / entrant_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target_file = target_dir / f'race_{race_number}_{sha256[:12]}{suffix}'
        target_file.write_bytes(content)
        return str(target_file.resolve()), sha256, len(content)
