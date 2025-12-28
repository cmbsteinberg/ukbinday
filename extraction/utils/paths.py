"""
Centralized path management for extraction scripts.

All paths are absolute and resolve correctly regardless of where scripts are run from.
Uses a class-based approach to encapsulate path logic.
"""

from pathlib import Path
from typing import List


class ExtractionPaths:
    """Manages all paths for the extraction pipeline"""

    def __init__(self):
        # Base directories - using __file__ to ensure paths work from anywhere
        self.utils_dir = Path(__file__).parent.resolve()
        self.extraction_dir = self.utils_dir.parent
        self.data_dir = self.extraction_dir / "data"
        self.councils_dir = self.data_dir / "councils"
        self.archive_dir = self.data_dir / "archive"

        # Ensure directories exist
        self._ensure_directories()

        # Input files
        self.input_json = self.data_dir / "input.json"

        # Processing outputs
        self.council_extraction_json = self.data_dir / "council_extraction_results.json"
        self.playwright_network_logs_json = self.data_dir / "playwright_network_logs.json"
        self.network_analysis_json = self.data_dir / "network_analysis_results.json"

        # GitHub URLs (constants, not paths)
        self.github_api_url = "https://api.github.com/repos/robbrad/UKBinCollectionData/contents/uk_bin_collection/uk_bin_collection/councils"
        self.input_json_url = "https://raw.githubusercontent.com/robbrad/UKBinCollectionData/refs/heads/master/uk_bin_collection/tests/input.json"

    def _ensure_directories(self):
        """Create necessary directories if they don't exist"""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.councils_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)

    def get_council_yaml_path(self, council_name: str) -> Path:
        """Get the path to a council's YAML file"""
        return self.councils_dir / f"{council_name}.yaml"

    def get_archive_path(self, filename: str) -> Path:
        """Get a path in the archive directory"""
        return self.archive_dir / filename

    def list_council_yamls(self) -> List[Path]:
        """List all council YAML files"""
        return sorted(self.councils_dir.glob("*.yaml"))

    def list_council_names(self) -> List[str]:
        """List all council names (stems of YAML files)"""
        return sorted([f.stem for f in self.councils_dir.glob("*.yaml")])

    def validate(self) -> dict:
        """
        Validate paths and return status information.
        Returns a dict with validation results.
        """
        return {
            "directories": {
                "utils": self.utils_dir.exists(),
                "extraction": self.extraction_dir.exists(),
                "data": self.data_dir.exists(),
                "councils": self.councils_dir.exists(),
                "archive": self.archive_dir.exists(),
            },
            "files": {
                "input_json": self.input_json.exists(),
                "council_extraction": self.council_extraction_json.exists(),
                "playwright_logs": self.playwright_network_logs_json.exists(),
                "network_analysis": self.network_analysis_json.exists(),
            },
            "council_count": len(self.list_council_names()),
        }


# Singleton instance for easy import
paths = ExtractionPaths()
