import hashlib
import time
import logging
from pathlib import Path

import requests

from app.config import settings

logger = logging.getLogger(__name__)

VT_BASE = "https://www.virustotal.com/api/v3"
DANGEROUS_THRESHOLD = 2   # flag if ≥2 engines detect a threat


class ScanResult:
    def __init__(self, clean: bool, reason: str = ""):
        self.clean = clean
        self.reason = reason

    def __bool__(self):
        return self.clean


class ScanService:
    def __init__(self):
        self.api_key = settings.VIRUSTOTAL_API_KEY
        self.enabled = bool(self.api_key)

    def scan_file(self, file_path: str) -> ScanResult:
        """
        Submit file to VirusTotal and wait for the report.
        Returns ScanResult(clean=True) if safe or if VT is not configured.
        """
        if not self.enabled:
            logger.info("VirusTotal key not set — skipping virus scan")
            return ScanResult(clean=True, reason="scan_disabled")

        path = Path(file_path)
        if not path.exists():
            return ScanResult(clean=False, reason="file_not_found")

        # Check by SHA256 first (avoids re-upload if already known)
        sha256 = self._sha256(path)
        result = self._get_existing_report(sha256)
        if result is not None:
            return result

        # Upload file
        file_id = self._upload(path)
        if not file_id:
            logger.warning("VirusTotal upload failed — allowing file through")
            return ScanResult(clean=True, reason="upload_failed")

        # Poll for analysis result (max 60 s)
        return self._poll_analysis(file_id)

    # ── internals ────────────────────────────────────────────────────────

    def _headers(self) -> dict:
        return {"x-apikey": self.api_key}

    def _sha256(self, path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    def _get_existing_report(self, sha256: str) -> ScanResult | None:
        try:
            r = requests.get(f"{VT_BASE}/files/{sha256}", headers=self._headers(), timeout=10)
            if r.status_code == 200:
                return self._parse_report(r.json())
        except Exception as exc:
            logger.debug(f"VT existing report lookup failed: {exc}")
        return None

    def _upload(self, path: Path) -> str | None:
        try:
            with open(path, "rb") as f:
                r = requests.post(
                    f"{VT_BASE}/files",
                    headers=self._headers(),
                    files={"file": (path.name, f)},
                    timeout=60,
                )
            if r.status_code == 200:
                return r.json()["data"]["id"]
        except Exception as exc:
            logger.warning(f"VT upload error: {exc}")
        return None

    def _poll_analysis(self, analysis_id: str, max_wait: int = 60) -> ScanResult:
        deadline = time.time() + max_wait
        while time.time() < deadline:
            try:
                r = requests.get(
                    f"{VT_BASE}/analyses/{analysis_id}",
                    headers=self._headers(),
                    timeout=10,
                )
                if r.status_code == 200:
                    data = r.json()["data"]
                    status = data.get("attributes", {}).get("status")
                    if status == "completed":
                        return self._parse_report(data)
            except Exception as exc:
                logger.debug(f"VT poll error: {exc}")
            time.sleep(5)

        logger.warning("VirusTotal analysis timed out — allowing file through")
        return ScanResult(clean=True, reason="timeout")

    @staticmethod
    def _parse_report(report: dict) -> ScanResult:
        stats = (
            report.get("data", {}).get("attributes", {}).get("last_analysis_stats")
            or report.get("attributes", {}).get("last_analysis_stats")
            or {}
        )
        malicious  = stats.get("malicious", 0)
        suspicious = stats.get("suspicious", 0)

        if malicious >= DANGEROUS_THRESHOLD:
            return ScanResult(
                clean=False,
                reason=f"{malicious} engine(s) flagged this file as malicious",
            )
        if malicious + suspicious >= DANGEROUS_THRESHOLD + 1:
            return ScanResult(
                clean=False,
                reason=f"{suspicious} engine(s) flagged this file as suspicious",
            )
        return ScanResult(clean=True, reason="clean")
