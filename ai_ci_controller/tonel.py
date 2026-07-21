from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


TONEL_SUFFIXES = (".class.st", ".trait.st", ".extension.st")
HEADER_KINDS = ("Class", "Extension", "Trait", "Package")

HEADER_START_RE = re.compile(r"^(Class|Extension|Trait|Package)\s*\{")
CATEGORY_CHUNK_RE = re.compile(r"^\{\s*#category\s*:")
METHOD_PATTERN_RE = re.compile(
    r"^(?P<receiver>[A-Za-z_][A-Za-z0-9_]*)\s+(?:(?P<side>class)\s+)?>>\s*(?P<signature>.+?)\s*\[\s*$"
)
KEYWORD_PART_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*:)")
UNARY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
BINARY_RE = re.compile(r"^[-+*/\\~<>=&|@%,?!]+$")
HEADER_PAIR_RE = re.compile(r"#(?P<key>[A-Za-z][A-Za-z0-9]*)\s*:\s*(?P<value>.+?)(?=,\s*#[A-Za-z]|\s*\}$)", re.DOTALL)


@dataclass(frozen=True)
class TonelMethod:
    receiver: str
    class_side: bool
    selector: str
    category: str
    line: int

    @property
    def reference(self) -> str:
        side = " class" if self.class_side else ""
        return f"{self.receiver}{side} >> {self.selector}"


@dataclass(frozen=True)
class TonelFile:
    path: str
    kind: str
    name: str
    superclass: str
    package: str
    instance_variables: list[str]
    class_variables: list[str]
    traits: str
    comment: str
    methods: list[TonelMethod]
    errors: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        if self.kind == "Extension":
            return f"Extension of {self.name}"
        parts = [f"{self.name}"]
        if self.superclass:
            parts.append(f"< {self.superclass}")
        if self.package:
            parts.append(f"[{self.package}]")
        return " ".join(parts)


def is_tonel_path(path: str) -> bool:
    lowered = path.lower()
    return any(lowered.endswith(suffix) for suffix in TONEL_SUFFIXES) or lowered.endswith(".st")


def parse_tonel(path: str, text: str) -> TonelFile:
    masked, mask_errors = mask_literals(text)
    errors = list(mask_errors)

    header = find_header(masked, text)
    if header is None:
        errors.append("no Class/Extension/Trait definition found")
        return TonelFile(
            path=path,
            kind="",
            name="",
            superclass="",
            package="",
            instance_variables=[],
            class_variables=[],
            traits="",
            comment=extract_leading_comment(text, masked),
            methods=[],
            errors=errors,
        )

    kind, fields, header_end_line = header
    name = unquote(fields.get("name", ""))
    superclass = unquote(fields.get("superclass", ""))
    package = unquote(fields.get("package", "")) or unquote(fields.get("category", ""))

    if not name:
        errors.append(f"{kind} definition is missing #name")
    if kind == "Class" and "superclass" not in fields:
        errors.append(f"Class '{name or path}' is missing #superclass")
    if kind in ("Class", "Trait") and not package:
        errors.append(f"{kind} '{name or path}' is missing #package")

    if kind == "Package":
        return TonelFile(
            path=path,
            kind=kind,
            name=name,
            superclass="",
            package=name,
            instance_variables=[],
            class_variables=[],
            traits="",
            comment="",
            methods=[],
            errors=errors,
        )

    methods, method_errors = parse_methods(masked, text, start_line=header_end_line)
    errors.extend(method_errors)

    if kind == "Class" and name:
        for method in methods:
            if method.receiver != name:
                errors.append(
                    f"line {method.line}: method receiver '{method.receiver}' "
                    f"does not match class '{name}'"
                )

    errors.extend(check_balance(masked))

    return TonelFile(
        path=path,
        kind=kind,
        name=name,
        superclass=superclass,
        package=package,
        instance_variables=parse_name_list(fields.get("instVars", "")),
        class_variables=parse_name_list(fields.get("classVars", "")),
        traits=fields.get("traits", "").strip(),
        comment=extract_leading_comment(text, masked),
        methods=methods,
        errors=errors,
    )


def mask_literals(text: str) -> tuple[str, list[str]]:
    out = list(text)
    errors: list[str] = []
    index = 0
    length = len(text)

    while index < length:
        char = text[index]
        if char == "$":
            index += 2
            continue
        if char not in ("'", '"'):
            index += 1
            continue

        quote = char
        cursor = index + 1
        closed = False
        while cursor < length:
            if text[cursor] != quote:
                if text[cursor] != "\n":
                    out[cursor] = " "
                cursor += 1
                continue
            if cursor + 1 < length and text[cursor + 1] == quote:
                out[cursor] = " "
                out[cursor + 1] = " "
                cursor += 2
                continue
            closed = True
            break

        if not closed:
            kind = "string" if quote == "'" else "comment"
            errors.append(f"line {line_of(text, index)}: unterminated {kind} literal")
            for position in range(index + 1, length):
                if text[position] != "\n":
                    out[position] = " "
            break

        index = cursor + 1

    return "".join(out), errors


def find_header(masked: str, text: str) -> tuple[str, dict[str, str], int] | None:
    for match in re.finditer(r"^(Class|Extension|Trait|Package)\s*\{", masked, flags=re.MULTILINE):
        kind = match.group(1)
        open_brace = masked.index("{", match.start())
        close_brace = matching_brace(masked, open_brace)
        if close_brace is None:
            continue
        body = text[open_brace + 1 : close_brace]
        return kind, parse_header_fields(body), line_of(text, close_brace)
    return None


def matching_brace(masked: str, open_index: int) -> int | None:
    depth = 0
    for index in range(open_index, len(masked)):
        char = masked[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    return None


def parse_header_fields(body: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for match in re.finditer(r"#(?P<key>[A-Za-z][A-Za-z0-9]*)\s*:", body):
        key = match.group("key")
        value_start = match.end()
        value_end = len(body)
        next_key = re.search(r",\s*#[A-Za-z][A-Za-z0-9]*\s*:", body[value_start:])
        if next_key:
            value_end = value_start + next_key.start()
        fields[key] = body[value_start:value_end].strip().rstrip(",").strip()
    return fields


def parse_methods(masked: str, text: str, *, start_line: int) -> tuple[list[TonelMethod], list[str]]:
    masked_lines = masked.splitlines()
    raw_lines = text.splitlines()
    methods: list[TonelMethod] = []
    errors: list[str] = []

    index = start_line
    pending_category: str | None = None
    pending_line = 0

    while index < len(masked_lines):
        masked_line = masked_lines[index]
        raw_line = raw_lines[index] if index < len(raw_lines) else ""

        if CATEGORY_CHUNK_RE.match(masked_line.strip()) and masked_line.lstrip().startswith("{"):
            pending_category = extract_category(raw_line)
            pending_line = index + 1
            index += 1
            continue

        pattern = METHOD_PATTERN_RE.match(raw_line.strip())
        if pattern and masked_line.rstrip().endswith("["):
            selector, selector_error = selector_from_signature(pattern.group("signature"))
            if selector_error:
                errors.append(f"line {index + 1}: {selector_error}")
            if pending_category is None:
                errors.append(
                    f"line {index + 1}: method '{pattern.group('receiver')}"
                    f">>{selector}' has no {{ #category : ... }} chunk header"
                )
            methods.append(
                TonelMethod(
                    receiver=pattern.group("receiver"),
                    class_side=bool(pattern.group("side")),
                    selector=selector,
                    category=pending_category or "",
                    line=index + 1,
                )
            )
            pending_category = None
            index = skip_method_body(masked_lines, index + 1)
            continue

        index += 1

    if pending_category is not None:
        errors.append(f"line {pending_line}: {{ #category : ... }} header is not followed by a method")

    return methods, errors


def skip_method_body(masked_lines: list[str], index: int) -> int:
    depth = 1
    while index < len(masked_lines):
        line = masked_lines[index]
        depth += line.count("[") - line.count("]")
        index += 1
        if depth <= 0:
            break
    return index


def extract_category(raw_line: str) -> str:
    match = re.search(r"#category\s*:\s*'(?P<value>(?:[^']|'')*)'", raw_line)
    if not match:
        return ""
    return match.group("value").replace("''", "'")


def selector_from_signature(signature: str) -> tuple[str, str]:
    signature = signature.strip()
    keyword_parts = KEYWORD_PART_RE.findall(signature)
    if keyword_parts and signature.split()[0].endswith(":"):
        return "".join(keyword_parts), ""
    if UNARY_RE.match(signature):
        return signature, ""
    tokens = signature.split()
    if tokens and BINARY_RE.match(tokens[0]):
        return tokens[0], ""
    return signature, f"could not parse method pattern '{signature}'"


def check_balance(masked: str) -> list[str]:
    pairs = {"[": "]", "(": ")", "{": "}"}
    closers = {value: key for key, value in pairs.items()}
    stack: list[tuple[str, int]] = []
    errors: list[str] = []

    for index, char in enumerate(masked):
        if char in pairs:
            stack.append((char, index))
        elif char in closers:
            if not stack:
                errors.append(f"line {line_of(masked, index)}: unmatched '{char}'")
                return errors
            opener, _ = stack.pop()
            if opener != closers[char]:
                errors.append(
                    f"line {line_of(masked, index)}: '{char}' does not close '{opener}'"
                )
                return errors

    if stack:
        opener, position = stack[-1]
        errors.append(f"line {line_of(masked, position)}: unclosed '{opener}'")
    return errors


def extract_leading_comment(text: str, masked: str) -> str:
    match = re.match(r"\s*\"", masked)
    if not match:
        return ""
    start = masked.index('"')
    end = masked.find('"', start + 1)
    if end == -1:
        return ""
    return text[start + 1 : end].strip().replace('""', '"')


def parse_name_list(value: str) -> list[str]:
    return [item.replace("''", "'") for item in re.findall(r"'((?:[^']|'')*)'", value)]


def unquote(value: str) -> str:
    value = value.strip().rstrip(",").strip()
    if len(value) >= 2 and value[0] == "'" and value[-1] == "'":
        return value[1:-1].replace("''", "'")
    return value


def line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def validate_paths(repo_dir: Path, relative_paths: list[str]) -> list[str]:
    problems: list[str] = []
    for relative in relative_paths:
        path = repo_dir / relative
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            problems.append(f"{relative}: could not read file ({exc})")
            continue
        parsed = parse_tonel(relative, text)
        problems.extend(f"{relative}: {error}" for error in parsed.errors)
    return problems
