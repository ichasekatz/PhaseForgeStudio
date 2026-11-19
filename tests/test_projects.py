"""Tests for phaseforge_studio.core.projects.

Covers Project creation, manifest save/load, resource management,
and ProjectRegistry scan/get/list.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from unittest import TestCase

import pytest

from phaseforge_studio.core.projects import (
    InvalidProjectError,
    Project,
    ProjectNotFoundError,
    ProjectRegistry,
    ProjectResource,
)


class _TmpDir(TestCase):
    """Base class providing self.tmp as a temporary directory Path."""

    def setUp(self) -> None:
        """Create a temporary directory."""
        self._td = tempfile.mkdtemp()
        self.tmp = Path(self._td)

    def tearDown(self) -> None:
        """Remove the temporary directory."""
        shutil.rmtree(self._td, ignore_errors=True)


class TestProjectCreateAndSave(_TmpDir):
    """Project.create() writes a valid manifest and registers sub-dirs."""

    def test_create_writes_manifest(self) -> None:
        """Project.create() writes project.json to the root."""
        Project.create(self.tmp, name="TestProject")
        assert (self.tmp / "project.json").exists()

    def test_create_registers_standard_subdirs(self) -> None:
        """Project.create() registers 'structures', 'blade', 'paipai', 'orchid'."""
        proj = Project.create(self.tmp, name="TestProject")
        names = {r.name for r in proj.resources}
        assert {"structures", "blade", "paipai", "orchid", "phaseforge"} <= names

    def test_create_makes_subdirectories(self) -> None:
        """Project.create() creates the standard sub-directories on disk."""
        Project.create(self.tmp, name="TestProject")
        assert (self.tmp / "structures").is_dir()
        assert (self.tmp / "blade").is_dir()

    def test_save_overwrites_manifest(self) -> None:
        """save() updates the on-disk manifest when attributes change."""
        proj = Project.create(self.tmp, name="TestProject")
        proj.description = "new description"
        proj.save()
        data = json.loads((self.tmp / "project.json").read_text())
        assert data["description"] == "new description"


class TestProjectLoad(_TmpDir):
    """Project.load() restores a project from its manifest."""

    def test_load_round_trips_name(self) -> None:
        """A saved project can be reloaded with the same name."""
        Project.create(self.tmp, name="AlFeSystem")
        reloaded = Project.load(self.tmp)
        assert reloaded.name == "AlFeSystem"

    def test_load_round_trips_resources(self) -> None:
        """Resources are preserved through save/load."""
        proj = Project.create(self.tmp, name="AlFeSystem")
        n_resources = len(proj.resources)
        reloaded = Project.load(self.tmp)
        assert len(reloaded.resources) == n_resources

    def test_load_missing_manifest_raises(self) -> None:
        """load() raises ProjectNotFoundError when no manifest exists."""
        with pytest.raises(ProjectNotFoundError):
            Project.load(self.tmp)

    def test_load_malformed_json_raises_invalid(self) -> None:
        """load() raises InvalidProjectError for a malformed manifest."""
        (self.tmp / "project.json").write_text("{bad json}")
        with pytest.raises(InvalidProjectError):
            Project.load(self.tmp)


class TestProjectResource(_TmpDir):
    """Project.add_resource() and resource() methods."""

    def test_add_resource_returns_record(self) -> None:
        """add_resource() returns a ProjectResource with the given name."""
        proj = Project.create(self.tmp, name="P")
        extra = self.tmp / "extra"
        extra.mkdir()
        res = proj.add_resource("extra", extra, framework="mf")
        assert isinstance(res, ProjectResource)
        assert res.name == "extra"

    def test_add_resource_overwrites_same_name(self) -> None:
        """Adding a resource with an existing name replaces the old one."""
        proj = Project.create(self.tmp, name="P")
        s1 = self.tmp / "s1"
        s2 = self.tmp / "s2"
        s1.mkdir()
        s2.mkdir()
        proj.add_resource("structures", s1, framework="mf")
        proj.add_resource("structures", s2, framework="mf")
        matches = [r for r in proj.resources if r.name == "structures"]
        assert len(matches) == 1
        assert matches[0].path.endswith("s2")

    def test_resource_lookup_by_name(self) -> None:
        """resource() finds a registered resource by name."""
        proj = Project.create(self.tmp, name="P")
        assert proj.resource("blade") is not None

    def test_resource_missing_name_returns_none(self) -> None:
        """resource() returns None for an unregistered name."""
        proj = Project.create(self.tmp, name="P")
        assert proj.resource("does_not_exist") is None


class TestProjectAsDict(_TmpDir):
    """Project.as_dict() returns JSON-serialisable data."""

    def test_as_dict_contains_name(self) -> None:
        """as_dict() contains the project name."""
        proj = Project.create(self.tmp, name="AlFe")
        d = proj.as_dict()
        assert d["name"] == "AlFe"

    def test_as_dict_resources_is_list(self) -> None:
        """as_dict() resources field is a list."""
        proj = Project.create(self.tmp, name="AlFe")
        d = proj.as_dict()
        assert isinstance(d["resources"], list)


class TestProjectRegistry(_TmpDir):
    """ProjectRegistry.scan(), register(), get(), list_projects()."""

    def test_scan_finds_project(self) -> None:
        """scan() discovers a project.json in a sub-directory."""
        sub = self.tmp / "mySub"
        sub.mkdir()
        Project.create(sub, name="Sub")
        reg = ProjectRegistry()
        found = reg.scan([self.tmp])
        assert any(p.name == "Sub" for p in found)

    def test_scan_ignores_missing_dirs(self) -> None:
        """scan() silently skips directories that do not exist."""
        reg = ProjectRegistry()
        found = reg.scan([self.tmp / "nonexistent"])
        assert found == []

    def test_get_returns_registered_project(self) -> None:
        """get() retrieves a manually registered project by name."""
        proj = Project.create(self.tmp, name="AlFe")
        reg = ProjectRegistry()
        reg.register(proj)
        assert reg.get("AlFe").name == "AlFe"

    def test_get_unknown_raises(self) -> None:
        """get() raises ProjectNotFoundError for an unknown name."""
        reg = ProjectRegistry()
        with pytest.raises(ProjectNotFoundError):
            reg.get("Ghost")

    def test_list_projects_summary_keys(self) -> None:
        """list_projects() entries contain name, root, description, n_resources."""
        proj = Project.create(self.tmp, name="AlFe")
        reg = ProjectRegistry()
        reg.register(proj)
        summaries = reg.list_projects()
        assert len(summaries) == 1
        assert {"name", "root", "description", "n_resources"} <= summaries[0].keys()

    def test_scan_skips_malformed_manifests(self) -> None:
        """scan() skips sub-directories with malformed project.json."""
        bad = self.tmp / "bad"
        bad.mkdir()
        (bad / "project.json").write_text("{bad}")
        reg = ProjectRegistry()
        found = reg.scan([self.tmp])
        assert not any(str(bad) in str(p.root) for p in found)
