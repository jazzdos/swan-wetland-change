from pathlib import Path

from wetland_change.store import OutputStore


def test_write_read_exists_list(tmp_path: Path) -> None:
    store = OutputStore(str(tmp_path / "out"))
    assert not store.exists("a/b.txt")
    assert store.write_bytes("a/b.txt", b"hello") == "a/b.txt"
    store.write_bytes("a/c/d.txt", b"x")
    store.write_bytes("z.txt", b"y")
    assert store.exists("a/b.txt")
    assert store.read_bytes("a/b.txt") == b"hello"
    assert store.list_files("a") == ["a/b.txt", "a/c/d.txt"]
    assert store.list_files("") == ["a/b.txt", "a/c/d.txt", "z.txt"]
    assert store.list_files("missing") == []
    assert (tmp_path / "out" / "a" / "b.txt").read_bytes() == b"hello"


def test_accepts_file_uri(tmp_path: Path) -> None:
    store = OutputStore((tmp_path / "out").as_uri())
    store.write_bytes("k.txt", b"v")
    assert (tmp_path / "out" / "k.txt").exists()
    assert store.uri.startswith("file://")
