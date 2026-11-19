"""Project organisation for PhaseForgeStudio.

A project is a lightweight manifest (``project.json``) that registers
existing directories as named resources for each framework.  It never
moves files — it only records where they live and their relationships.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


class ProjectNotFoundError(KeyError):
    """Raised when a project name or path is not registered."""


class InvalidProjectError(ValueError):
    """Raised when a project.json is missing required fields."""


_manifest_name = "project.json"


@dataclass
class ProjectResource:
    """A named resource directory registered to a project.

    Attributes:
        name: Short name for this resource (e.g. ``"structures"``, ``"blade"``).
        path: Absolute path to the directory.
        framework: Framework that produced or owns this resource.
        description: Optional one-line description.
        created: Unix timestamp when this resource was registered.
    """

    name: str
    path: str
    framework: str = ""
    description: str = ""
    created: float = field(default_factory=time.time)


@dataclass
class Project:
    """A research project manifest.

    Attributes:
        name: Project name.
        root: Absolute path to the project root.
        description: Optional project description.
        created: Unix timestamp.
        resources: Named resource directories.
        chemical_systems: Set of chemical systems studied (e.g. ``["Hf-Cr-B"]``).
        notes: Free-form notes.
    """

    name: str
    root: str
    description: str = ""
    created: float = field(default_factory=time.time)
    resources: list[ProjectResource] = field(default_factory=list)
    chemical_systems: list[str] = field(default_factory=list)
    notes: str = ""

    def manifest_path(self) -> Path:
        """Return the absolute path to this project's manifest.

        Returns:
            Path to ``project.json``.
        """
        return Path(self.root) / _manifest_name

    def resource(self, name: str) -> ProjectResource | None:
        """Find a registered resource by name.

        Args:
            name (str): Resource name.

        Returns:
            ``ProjectResource`` or ``None`` if not found.
        """
        return next((r for r in self.resources if r.name == name), None)

    def add_resource(
        self,
        name: str,
        path: str | Path,
        framework: str = "",
        description: str = "",
    ) -> ProjectResource:
        """Register a directory as a named project resource.

        Existing resources with the same name are overwritten.

        Args:
            name (str): Resource name.
            path (str | Path): Absolute path to register.
            framework (str): Owning framework key.
            description (str): Optional description.

        Returns:
            The new ``ProjectResource``.
        """
        abs_path = str(Path(path).expanduser().resolve())
        self.resources = [r for r in self.resources if r.name != name]
        res = ProjectResource(
            name=name,
            path=abs_path,
            framework=framework,
            description=description,
        )
        self.resources.append(res)
        return res

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable snapshot.

        Returns:
            Dict suitable for ``json.dumps``.
        """
        d = asdict(self)
        return d

    def save(self) -> None:
        """Write the project manifest to ``project.json`` in ``root``.

        Raises:
            OSError: If the manifest cannot be written.
        """
        p = self.manifest_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.as_dict(), indent=2))

    @classmethod
    def load(cls, root: str | Path) -> Project:
        """Load a project from its ``project.json`` manifest.

        Args:
            root (str | Path): Project root directory.

        Returns:
            Populated ``Project`` instance.

        Raises:
            ProjectNotFoundError: If no manifest exists.
            InvalidProjectError: If the manifest is malformed.
        """
        p = Path(root) / _manifest_name
        if not p.exists():
            raise ProjectNotFoundError(f"No project.json found at {root}")
        try:
            data = json.loads(p.read_text())
        except json.JSONDecodeError as e:
            raise InvalidProjectError(f"Malformed project.json at {p}: {e}") from e
        resources = [ProjectResource(**r) for r in data.pop("resources", [])]
        return cls(**{**data, "resources": resources})

    @classmethod
    def create(cls, root: str | Path, name: str, description: str = "") -> Project:
        """Create and save a new project at *root*.

        Args:
            root (str | Path): Directory to create the project in.
            name (str): Project name.
            description (str): Optional description.

        Returns:
            New ``Project`` instance with manifest written to disk.
        """
        proj = cls(name=name, root=str(Path(root).expanduser().resolve()), description=description)
        # Register standard sub-directories
        for subdir, fw in [
            ("structures", "mf"),
            ("phaseforge", "pf"),
            ("blade", "blade"),
            ("paipai", "paipai"),
            ("orchid", "orchid"),
            ("shared_data", ""),
            ("comparisons", ""),
            ("figures", ""),
        ]:
            full = Path(root) / subdir
            full.mkdir(parents=True, exist_ok=True)
            proj.add_resource(subdir, str(full), framework=fw, description=f"{subdir} files")
        proj.save()
        return proj


# ---------------------------------------------------------------------------
# Project registry (session-level cache)
# ---------------------------------------------------------------------------


class ProjectRegistry:
    """In-memory registry of known projects (re-reads manifests on demand).

    Projects are discovered by scanning configured ``project_roots`` directories
    for ``project.json`` manifests.
    """

    def __init__(self) -> None:
        """Initialise empty registry."""
        self._projects: dict[str, Project] = {}

    def scan(self, search_dirs: list[str | Path]) -> list[Project]:
        """Scan directories for project.json manifests and register them.

        Args:
            search_dirs (list[str | Path]): Directories to scan (non-recursive).

        Returns:
            List of discovered ``Project`` instances.
        """
        found: list[Project] = []
        for base in search_dirs:
            base_path = Path(base)
            if not base_path.is_dir():
                continue
            for sub in base_path.iterdir():
                manifest = sub / _manifest_name
                if manifest.exists():
                    try:
                        proj = Project.load(sub)
                        self._projects[proj.name] = proj
                        found.append(proj)
                    except (ProjectNotFoundError, InvalidProjectError):
                        pass
        return found

    def register(self, project: Project) -> None:
        """Add a project to the registry.

        Args:
            project (Project): Project to register.
        """
        self._projects[project.name] = project

    def get(self, name: str) -> Project:
        """Return a project by name.

        Args:
            name (str): Project name.

        Returns:
            ``Project`` instance.

        Raises:
            ProjectNotFoundError: If name is not registered.
        """
        if name not in self._projects:
            raise ProjectNotFoundError(name)
        return self._projects[name]

    def list_projects(self) -> list[dict[str, Any]]:
        """Return lightweight summaries of all registered projects.

        Returns:
            List of dicts with ``name``, ``root``, ``description``, ``n_resources``.
        """
        return [
            {
                "name": p.name,
                "root": p.root,
                "description": p.description,
                "n_resources": len(p.resources),
                "chemical_systems": p.chemical_systems,
                "created": p.created,
            }
            for p in self._projects.values()
        ]


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_registry: ProjectRegistry = ProjectRegistry()
