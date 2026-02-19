"""Document wrapper for KiCad S-expression files.

Handles file I/O, encoding, and provides a convenient API for loading
and saving KiCad files (.kicad_pcb, .kicad_sch, .kicad_mod, .kicad_pro).
"""

from __future__ import annotations

from pathlib import Path

from .parser import SExp, parse


class Document:
    """A loaded KiCad S-expression file.

    Usage::

        doc = Document.load("board.kicad_pcb")
        doc.root.name  # "kicad_pcb"
        doc.root["version"].first_value  # "20241229"
        doc.save()  # writes back to same path
        doc.save("copy.kicad_pcb")  # writes to new path
    """

    __slots__ = ("path", "root", "_raw_text")

    def __init__(self, path: Path, root: SExp, raw_text: str) -> None:
        self.path = path
        self.root = root
        self._raw_text = raw_text

    @classmethod
    def load(cls, path: str | Path) -> Document:
        """Load and parse a KiCad S-expression file.

        Args:
            path: Path to the .kicad_pcb, .kicad_sch, .kicad_mod, or .kicad_pro file.

        Returns:
            A Document wrapping the parsed tree.

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: If the file cannot be parsed.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        raw_text = path.read_text(encoding="utf-8")
        root = parse(raw_text)
        return cls(path=path, root=root, raw_text=raw_text)

    def save(self, path: str | Path | None = None) -> Path:
        """Write the S-expression tree back to a file.

        Args:
            path: Optional new path. If None, overwrites the original file.

        Returns:
            The path the file was written to.
        """
        target = Path(path) if path is not None else self.path
        text = self.root.to_string() + "\n"
        target.write_text(text, encoding="utf-8")
        return target

    @property
    def file_type(self) -> str:
        """Return the file type based on extension (e.g., 'kicad_pcb', 'kicad_sch')."""
        return self.path.suffix.lstrip(".")

    def __repr__(self) -> str:
        return f"Document({self.path.name!r}, root={self.root.name!r})"
