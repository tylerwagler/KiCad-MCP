"""S-expression parser for KiCad files.

KiCad uses S-expressions (Lisp-like syntax) for all its file formats:
.kicad_pcb, .kicad_sch, .kicad_mod, .kicad_pro.

This parser:
- Handles quoted strings, unquoted atoms, and nested parenthesized expressions
- Preserves original number formatting for round-trip fidelity
- Provides XPath-like query API for navigating the tree
"""

from __future__ import annotations

from collections.abc import Iterator


class SExp:
    """A node in an S-expression tree.

    An SExp is either:
    - An atom: a leaf node with a string value (and optional _original_str)
    - A list: a node with a name (first child) and child nodes

    Usage::

        tree = parse('(kicad_pcb (version 20241229) (generator "pcbnew"))')
        tree.name          # "kicad_pcb"
        tree["version"]    # SExp with value "20241229"
        tree.find("generator").value  # "pcbnew"
    """

    __slots__ = ("name", "value", "children", "_original_str")

    def __init__(
        self,
        name: str | None = None,
        value: str | None = None,
        children: list[SExp] | None = None,
        _original_str: str | None = None,
    ) -> None:
        self.name = name
        self.value = value
        self.children: list[SExp] = children if children is not None else []
        self._original_str = _original_str

    @property
    def is_atom(self) -> bool:
        return self.name is None and self.value is not None

    @property
    def is_list(self) -> bool:
        return self.name is not None

    def __getitem__(self, key: str) -> SExp:
        """Get the first child node with the given name.

        Returns the *first child whose value follows that name* for simple
        key-value pairs like ``(version 20241229)``.

        Raises KeyError if not found.
        """
        for child in self.children:
            if child.name == key:
                return child
        raise KeyError(f"No child named {key!r}")

    def get(self, key: str, default: SExp | None = None) -> SExp | None:
        """Get the first child node with the given name, or default."""
        for child in self.children:
            if child.name == key:
                return child
        return default

    def find(self, name: str) -> SExp | None:
        """Find the first descendant (direct child) with the given name."""
        for child in self.children:
            if child.name == name:
                return child
        return None

    def find_all(self, name: str) -> list[SExp]:
        """Find all direct children with the given name."""
        return [child for child in self.children if child.name == name]

    def find_recursive(self, name: str) -> Iterator[SExp]:
        """Find all descendants (recursive) with the given name."""
        for child in self.children:
            if child.name == name:
                yield child
            if child.children:
                yield from child.find_recursive(name)

    @property
    def first_value(self) -> str | None:
        """Get the value of the first atom child, e.g. for (version 20241229) -> '20241229'."""
        for child in self.children:
            if child.is_atom:
                return child.value
        return None

    @property
    def atom_values(self) -> list[str]:
        """Get all atom values among direct children."""
        return [child.value for child in self.children if child.is_atom and child.value is not None]

    def to_string(self, indent: int = 0) -> str:
        """Serialize back to S-expression string.

        Uses _original_str for atoms to preserve number formatting.
        List nodes with only atom children stay on one line.
        List nodes with nested list children use multi-line indented format.
        """
        if self.is_atom:
            if self._original_str is not None:
                return self._original_str
            if self.value is not None:
                return _quote_if_needed(self.value)
            return ""

        parts: list[str] = []
        if self.name is not None:
            parts.append(self.name)
        for child in self.children:
            parts.append(child.to_string(indent))

        # If no children have nested lists, stay on one line
        has_nested = any(child.is_list for child in self.children)
        if not has_nested:
            return "(" + " ".join(parts) + ")"

        # Multi-line with indentation
        prefix = "  " * indent
        child_prefix = "  " * (indent + 1)
        lines: list[str] = []
        # Opening: name on same line
        lines.append(prefix + "(" + (self.name or ""))
        for child in self.children:
            if child.is_atom:
                # Inline atoms after the name on the first line
                lines[0] += " " + child.to_string(indent + 1)
            else:
                lines.append(child_prefix + child.to_string(indent + 1).lstrip())
        lines[-1] += ")"
        if indent == 0:
            return "\n".join(lines)
        # Strip the leading prefix since the caller adds its own
        result = "\n".join(lines)
        return result[len(prefix) :]

    def __repr__(self) -> str:
        if self.is_atom:
            return f"SExp(value={self.value!r})"
        child_count = len(self.children)
        return f"SExp(name={self.name!r}, children={child_count})"

    def deep_copy(self) -> SExp:
        """Create a deep copy of this S-expression tree.

        Returns:
            A new SExp node with all children recursively copied.
        """
        if self.is_atom:
            return SExp(
                value=self.value,
                _original_str=self._original_str,
            )

        # Deep copy all children
        new_children = [child.deep_copy() for child in self.children]
        return SExp(
            name=self.name,
            children=new_children,
        )


def _quote_if_needed(s: str) -> str:
    """Quote a string if it contains special characters."""
    if not s:
        return '""'
    needs_quoting = False
    for ch in s:
        if ch in ' \t\n\r"()\\':
            needs_quoting = True
            break
    if not needs_quoting:
        return s
    escaped = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


class _Tokenizer:
    """Low-level tokenizer for S-expression strings."""

    __slots__ = ("_text", "_pos", "_length")

    def __init__(self, text: str) -> None:
        self._text = text
        self._pos = 0
        self._length = len(text)

    def _skip_whitespace(self) -> None:
        pos = self._pos
        text = self._text
        length = self._length
        while pos < length and text[pos] in " \t\n\r":
            pos += 1
        self._pos = pos

    def peek(self) -> str | None:
        self._skip_whitespace()
        if self._pos >= self._length:
            return None
        return self._text[self._pos]

    def next_token(self) -> tuple[str, str, str] | None:
        """Return (token_type, token_value, raw_text) or None at EOF.

        Token types: 'OPEN', 'CLOSE', 'STRING', 'ATOM'
        """
        self._skip_whitespace()
        if self._pos >= self._length:
            return None

        ch = self._text[self._pos]

        if ch == "(":
            self._pos += 1
            return ("OPEN", "(", "(")

        if ch == ")":
            self._pos += 1
            return ("CLOSE", ")", ")")

        if ch == '"':
            start = self._pos
            value = self._read_quoted_string()
            raw = self._text[start : self._pos]
            return ("STRING", value, raw)

        start = self._pos
        value = self._read_atom()
        return ("ATOM", value, value)

    def _read_quoted_string(self) -> str:
        """Read a double-quoted string, handling escape sequences."""
        self._pos += 1  # skip opening quote
        result: list[str] = []
        while self._pos < self._length:
            ch = self._text[self._pos]
            if ch == "\\":
                self._pos += 1
                if self._pos < self._length:
                    result.append(self._text[self._pos])
                    self._pos += 1
                continue
            if ch == '"':
                self._pos += 1
                return "".join(result)
            result.append(ch)
            self._pos += 1
        raise ValueError("Unterminated quoted string")

    def _read_atom(self) -> str:
        """Read an unquoted atom (terminated by whitespace or parens)."""
        start = self._pos
        while self._pos < self._length:
            ch = self._text[self._pos]
            if ch in ' \t\n\r()"':
                break
            self._pos += 1
        return self._text[start : self._pos]


def parse(text: str) -> SExp:
    """Parse an S-expression string into an SExp tree.

    Args:
        text: The S-expression string to parse.

    Returns:
        The root SExp node.

    Raises:
        ValueError: If the input is malformed.
    """
    tokenizer = _Tokenizer(text)
    result = _parse_expr(tokenizer)
    return result


def parse_all(text: str) -> list[SExp]:
    """Parse text that may contain multiple top-level S-expressions."""
    tokenizer = _Tokenizer(text)
    results: list[SExp] = []
    while tokenizer.peek() is not None:
        results.append(_parse_expr(tokenizer))
    return results


def _parse_expr(tokenizer: _Tokenizer) -> SExp:
    """Parse a single S-expression from the tokenizer."""
    token = tokenizer.next_token()
    if token is None:
        raise ValueError("Unexpected end of input")

    token_type, token_value, raw_text = token

    if token_type in ("ATOM", "STRING"):
        return SExp(value=token_value, _original_str=raw_text)

    if token_type == "OPEN":
        # Read the name (first element)
        children: list[SExp] = []
        name: str | None = None

        # Peek to see if the list is empty
        if tokenizer.peek() == ")":
            tokenizer.next_token()  # consume ')'
            return SExp(name="", children=[])

        # First element is the name
        first = _parse_expr(tokenizer)
        if first.is_atom:
            name = first.value
        else:
            # Nested list as first element - treat as unnamed
            name = first.name
            children.append(first)

        # Read remaining children
        while True:
            pk = tokenizer.peek()
            if pk is None:
                raise ValueError("Unexpected end of input — unclosed '('")
            if pk == ")":
                tokenizer.next_token()  # consume ')'
                break
            children.append(_parse_expr(tokenizer))

        return SExp(name=name, children=children)

    if token_type == "CLOSE":
        raise ValueError("Unexpected ')'")

    raise ValueError(f"Unexpected token: {token_type}")
