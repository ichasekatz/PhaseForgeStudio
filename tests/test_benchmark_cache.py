"""Tests for benchmark_cache module."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from phaseforge_studio.benchmark_cache import (
    clear_cache,
    hash_file,
    hash_structure_dir,
    invalidate_cache,
    is_cache_valid,
    list_cache_entries,
    load_from_cache,
    make_cache_key,
    save_to_cache,
)


class TestMakeCacheKey:
    def test_returns_32_chars(self) -> None:
        key = make_cache_key("grace")
        assert len(key) == 32

    def test_deterministic(self) -> None:
        k1 = make_cache_key("grace", model_version="v1", structure_hash="abc")
        k2 = make_cache_key("grace", model_version="v1", structure_hash="abc")
        assert k1 == k2

    def test_different_mlip_different_key(self) -> None:
        k1 = make_cache_key("grace")
        k2 = make_cache_key("mace")
        assert k1 != k2

    def test_different_version_different_key(self) -> None:
        k1 = make_cache_key("grace", model_version="v1")
        k2 = make_cache_key("grace", model_version="v2")
        assert k1 != k2

    def test_different_structure_hash_different_key(self) -> None:
        k1 = make_cache_key("grace", structure_hash="aaa")
        k2 = make_cache_key("grace", structure_hash="bbb")
        assert k1 != k2

    def test_settings_affect_key(self) -> None:
        k1 = make_cache_key("grace", calculator_settings={"fmax": 0.01})
        k2 = make_cache_key("grace", calculator_settings={"fmax": 0.05})
        assert k1 != k2

    def test_extra_affects_key(self) -> None:
        k1 = make_cache_key("grace", extra={"mode": "A"})
        k2 = make_cache_key("grace", extra={"mode": "B"})
        assert k1 != k2

    def test_hex_chars_only(self) -> None:
        key = make_cache_key("test", extra={"x": 1})
        assert all(c in "0123456789abcdef" for c in key)


class TestHashFile:
    def test_returns_hex_string(self, tmp_path: Path) -> None:
        f = tmp_path / "file.txt"
        f.write_text("hello")
        h = hash_file(f)
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        h = hash_file(tmp_path / "nonexistent.txt")
        assert h == ""

    def test_different_content_different_hash(self, tmp_path: Path) -> None:
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("hello")
        f2.write_text("world")
        assert hash_file(f1) != hash_file(f2)

    def test_same_content_same_hash(self, tmp_path: Path) -> None:
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("same")
        f2.write_text("same")
        assert hash_file(f1) == hash_file(f2)


class TestHashStructureDir:
    def test_returns_32_chars(self, tmp_path: Path) -> None:
        (tmp_path / "POSCAR").write_text("structure data")
        h = hash_structure_dir(tmp_path)
        assert len(h) == 32

    def test_empty_dir(self, tmp_path: Path) -> None:
        h = hash_structure_dir(tmp_path)
        assert len(h) == 32

    def test_different_files_different_hash(self, tmp_path: Path) -> None:
        d1 = tmp_path / "d1"
        d2 = tmp_path / "d2"
        d1.mkdir()
        d2.mkdir()
        (d1 / "POSCAR").write_text("struct A")
        (d2 / "POSCAR").write_text("struct B")
        assert hash_structure_dir(d1) != hash_structure_dir(d2)


class TestSaveAndLoad:
    def test_roundtrip(self, tmp_path: Path) -> None:
        key = make_cache_key("grace")
        data = {"energy_mae": 0.05, "n_structures": 10}
        save_to_cache(key, data, tmp_path)
        loaded = load_from_cache(key, tmp_path)
        assert loaded == data

    def test_load_missing_returns_none(self, tmp_path: Path) -> None:
        result = load_from_cache("nonexistentkey12345678901234", tmp_path)
        assert result is None

    def test_save_creates_cache_dir(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "sub" / "cache"
        key = make_cache_key("test")
        save_to_cache(key, {"x": 1}, cache_dir)
        assert cache_dir.is_dir()

    def test_load_wrong_key_returns_none(self, tmp_path: Path) -> None:
        key = make_cache_key("grace")
        save_to_cache(key, {"x": 1}, tmp_path)
        # Tamper with the cache file
        path = tmp_path / f"{key}.json"
        entry = json.loads(path.read_text())
        entry["cache_key"] = "tampered" + "x" * 20
        path.write_text(json.dumps(entry))
        assert load_from_cache(key, tmp_path) is None

    def test_load_corrupt_file_returns_none(self, tmp_path: Path) -> None:
        key = make_cache_key("bad")
        (tmp_path / f"{key}.json").write_text("{{not valid json")
        assert load_from_cache(key, tmp_path) is None


class TestIsCacheValid:
    def test_valid_entry(self, tmp_path: Path) -> None:
        key = make_cache_key("grace")
        save_to_cache(key, {"x": 1}, tmp_path)
        assert is_cache_valid(key, tmp_path)

    def test_missing_entry_invalid(self, tmp_path: Path) -> None:
        key = make_cache_key("missing")
        assert not is_cache_valid(key, tmp_path)

    def test_expired_entry_invalid(self, tmp_path: Path) -> None:
        key = make_cache_key("old")
        save_to_cache(key, {"x": 1}, tmp_path)
        # Mark as old by writing a past timestamp
        path = tmp_path / f"{key}.json"
        entry = json.loads(path.read_text())
        entry["created_at"] = time.time() - 10000
        path.write_text(json.dumps(entry))
        assert not is_cache_valid(key, tmp_path, max_age_s=100)

    def test_within_max_age_valid(self, tmp_path: Path) -> None:
        key = make_cache_key("recent")
        save_to_cache(key, {"y": 2}, tmp_path)
        assert is_cache_valid(key, tmp_path, max_age_s=3600)


class TestInvalidateAndClear:
    def test_invalidate_existing(self, tmp_path: Path) -> None:
        key = make_cache_key("x")
        save_to_cache(key, {}, tmp_path)
        assert invalidate_cache(key, tmp_path)
        assert load_from_cache(key, tmp_path) is None

    def test_invalidate_missing(self, tmp_path: Path) -> None:
        assert not invalidate_cache(make_cache_key("absent"), tmp_path)

    def test_clear_all(self, tmp_path: Path) -> None:
        for suffix in ("a", "b", "c"):
            key = make_cache_key(suffix)
            save_to_cache(key, {}, tmp_path)
        count = clear_cache(tmp_path)
        assert count == 3
        assert list(tmp_path.glob("*.json")) == []

    def test_clear_empty_dir(self, tmp_path: Path) -> None:
        assert clear_cache(tmp_path / "nonexistent") == 0


class TestListCacheEntries:
    def test_empty_dir(self, tmp_path: Path) -> None:
        assert list_cache_entries(tmp_path) == []

    def test_nonexistent_dir(self, tmp_path: Path) -> None:
        assert list_cache_entries(tmp_path / "ghost") == []

    def test_lists_entries(self, tmp_path: Path) -> None:
        for suffix in ("p", "q"):
            key = make_cache_key(suffix)
            save_to_cache(key, {"v": suffix}, tmp_path)
        entries = list_cache_entries(tmp_path)
        assert len(entries) == 2
        for e in entries:
            assert "key" in e
            assert "created_at" in e
            assert "age_s" in e
            assert "size_bytes" in e
            assert e["size_bytes"] > 0
