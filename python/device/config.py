from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DryRunConfig:
    """Deterministic dry-run controls; faults are keyed by net or component."""

    faults: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class JobInput:
    pcb_path: Path
    schematic_path: Path
    output_dir: Path
    config_path: Path
    dry_run: DryRunConfig = field(default_factory=DryRunConfig)

    @classmethod
    def from_json_file(cls, manifest_path: str | Path) -> "JobInput":
        manifest_path = Path(manifest_path).resolve()
        with manifest_path.open(encoding="utf-8") as source:
            data = json.load(source)
        return cls.from_dict(data, manifest_path.parent)

    @classmethod
    def from_dict(cls, data: dict[str, Any], base_dir: Path | None = None) -> "JobInput":
        if not isinstance(data, dict):
            raise ValueError("Job manifest must be a JSON object")
        base_dir = base_dir or Path.cwd()

        def resolve(name: str, required: bool = True) -> Path:
            value = data.get(name)
            if value is None and required:
                raise ValueError(f"Job manifest is missing {name!r}")
            path = Path(value) if value is not None else Path()
            return path if path.is_absolute() else (base_dir / path).resolve()

        config_path = resolve("config_path", required=False)
        if "config_path" not in data:
            config_path = Path(__file__).resolve().parents[1] / "inspector" / "config.yaml"
        dry_run_data = data.get("dry_run", {})
        if not isinstance(dry_run_data, dict):
            raise ValueError("dry_run must be an object")
        faults = dry_run_data.get("faults", {})
        if not isinstance(faults, dict):
            raise ValueError("dry_run.faults must be an object")

        job = cls(
            pcb_path=resolve("pcb_path"),
            schematic_path=resolve("schematic_path"),
            output_dir=resolve("output_dir"),
            config_path=config_path,
            dry_run=DryRunConfig(faults=faults),
        )
        job.validate()
        return job

    def validate(self) -> None:
        for label, path in (("PCB", self.pcb_path), ("schematic", self.schematic_path), ("config", self.config_path)):
            if not path.is_file():
                raise FileNotFoundError(f"{label} file not found: {path}")

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["pcb_path"] = str(self.pcb_path)
        result["schematic_path"] = str(self.schematic_path)
        result["output_dir"] = str(self.output_dir)
        result["config_path"] = str(self.config_path)
        return result
