import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import quote

from atomic_io import StateFileError, atomic_write_json, load_json_state
from process_lock import (
    LOCK_BUSY_EXIT_CODE,
    ProcessLockUnavailable,
    VaultProcessLock,
    command_text,
    lock_is_delegated_by_parent,
    print_lock_error,
)


CATEGORY_LEVELS = 5
METADATA_SCHEMA_VERSION = 5
DEFAULT_OUTPUT_DIR = "Subject_Hierarchical"
DEFAULT_REVIEW_DIR = "Topic_Reviews_Hierarchical"
DEFAULT_METADATA_FILE = "organizer_metadata_hierarchical.json"
PRODUCTION_OUTPUT_DIR = "Subject"
PRODUCTION_REVIEW_DIR = "Topic_Reviews"
PRODUCTION_METADATA_FILE = "organizer_metadata.json"
AUTO_GENERATED_SUBJECT = "<!-- AUTO-GENERATED: Log2Topic hierarchical subject. -->"
AUTO_GENERATED_REVIEW = "<!-- AUTO-GENERATED: Log2Topic hierarchical review. -->"
SOURCE_ID_MARKER_NAME = "research-notes-source-id"
HEADING_RE = re.compile(r"^(#{1,5})[ \t]+(.*?)[ \t]*$")
SOURCE_ID_RE = re.compile(
    r"<!--\s*(?:[a-zA-Z0-9][a-zA-Z0-9_-]*-)?source-id\s*:\s*"
    r"([a-fA-F0-9]{8,64})\s*-->",
    re.IGNORECASE,
)
ISSUE_HINT_KEYWORDS = (
    "문제",
    "이슈",
    "오류",
    "에러",
    "확인",
    "검토",
    "필요",
    "개선",
    "주의",
    "todo",
    "fixme",
    "?",
)


def normalize_name(value):
    value = re.sub(r"[`*_~]", "", value or "")
    value = re.sub(r"[_-]+", " ", value)
    return re.sub(r"\s+", " ", value).strip().casefold()


def normalize_rel_path(path):
    return path.replace("\\", "/")


def sanitize_filename(name):
    name = re.sub(r'[\\/*?:"<>|]', "_", name or "")
    return name.strip().rstrip(".") or "Untitled"


def split_markdown_table_row(line):
    return [part.strip() for part in line.strip().strip("|").split("|")]


def is_table_divider(cells):
    return cells and all(re.fullmatch(r"[:\-\s]+", cell or "") for cell in cells)


def is_category_header(cells):
    joined = " ".join(cells[:CATEGORY_LEVELS]).casefold()
    return "level 1" in joined or "대분류" in joined or "대주제" in joined


def is_ascii_word(term):
    return bool(re.fullmatch(r"[a-z0-9]+", term))


def text_contains_term(term, text):
    if is_ascii_word(term):
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text))
    return term in text


def keyword_matches_text(keyword, text, text_no_spaces):
    terms = keyword.casefold().split()
    if terms and all(text_contains_term(term, text) for term in terms):
        return True

    compact = keyword.casefold().replace(" ", "")
    if not compact:
        return False
    if len(terms) == 1 and is_ascii_word(compact) and len(compact) <= 3:
        return False
    return compact in text_no_spaces


@dataclass
class RuleNode:
    path: tuple
    keywords: list = field(default_factory=list)
    explicit: bool = False


class RuleTree:
    def __init__(self):
        self.nodes = {}
        self.children = defaultdict(dict)
        self.errors = []
        self.warnings = []

    def ensure_path(self, path, explicit=False):
        for size in range(1, len(path) + 1):
            partial = tuple(path[:size])
            node = self.nodes.setdefault(partial, RuleNode(path=partial))
            if size == len(path) and explicit:
                node.explicit = True
            parent = partial[:-1]
            normalized = normalize_name(partial[-1])
            existing = self.children[parent].get(normalized)
            if existing and existing != partial[-1]:
                self.errors.append(
                    f"Ambiguous sibling names under {' > '.join(parent) or '(root)'}: "
                    f"{existing!r} and {partial[-1]!r}"
                )
            self.children[parent][normalized] = partial[-1]
        return self.nodes[tuple(path)]

    def add_rule(self, path, keywords, line_number):
        node = self.ensure_path(path, explicit=True)
        existing = set(node.keywords)
        for keyword in keywords:
            normalized = keyword.strip().casefold()
            if normalized and normalized not in existing:
                node.keywords.append(normalized)
                existing.add(normalized)
        if node.explicit and not keywords:
            self.warnings.append(
                f"Line {line_number}: {' > '.join(path)} has no supplemental keywords. "
                "Heading matching will still work."
            )

    def match_child(self, parent_path, heading_text):
        canonical = self.children.get(tuple(parent_path), {}).get(normalize_name(heading_text))
        if not canonical:
            return None
        return tuple(parent_path) + (canonical,)

    def resolve_manual_path(self, values):
        current = ()
        for value in values:
            matched = self.match_child(current, value)
            if not matched:
                return None
            current = matched
        return current

    def has_children(self, path):
        return bool(self.children.get(tuple(path)))

    def iter_keyword_nodes(self, level1):
        for path, node in self.nodes.items():
            if path and path[0] == level1 and node.keywords:
                yield path, node


def parse_rules_from_markdown(rules_filepath):
    tree = RuleTree()
    with open(rules_filepath, "r", encoding="utf-8") as file_obj:
        lines = file_obj.readlines()

    inherited = [""] * CATEGORY_LEVELS
    for line_number, raw_line in enumerate(lines, 1):
        line = raw_line.strip()
        if not line.startswith("|"):
            continue
        cells = split_markdown_table_row(line)
        if len(cells) < CATEGORY_LEVELS:
            continue
        if is_table_divider(cells) or is_category_header(cells):
            continue

        path_cells = cells[:CATEGORY_LEVELS]
        for index, cell in enumerate(path_cells):
            if not cell:
                continue
            inherited[index] = cell
            for child_index in range(index + 1, CATEGORY_LEVELS):
                inherited[child_index] = ""

        populated = [index for index, value in enumerate(inherited) if value]
        if not populated:
            continue
        deepest = max(populated)
        if any(not inherited[index] for index in range(deepest + 1)):
            tree.errors.append(f"Line {line_number}: category level is missing before a child level.")
            continue

        path = tuple(inherited[: deepest + 1])
        keyword_cell = cells[CATEGORY_LEVELS] if len(cells) > CATEGORY_LEVELS else ""
        keywords = [value.strip() for value in keyword_cell.split(",") if value.strip()]
        tree.add_rule(path, keywords, line_number)

    if not tree.nodes:
        tree.errors.append("No category rows were found in Classification_Rules.md.")
    return tree


def is_page_title(heading_text, log_name, first_heading, tree):
    if not first_heading or tree.match_child((), heading_text):
        return False
    normalized_heading = normalize_name(heading_text)
    normalized_log = normalize_name(log_name)
    return (
        normalized_heading == normalized_log
        or "일지" in heading_text
        or bool(re.fullmatch(r"[\d.\-\s]+(?:일지)?", heading_text.strip()))
    )


@dataclass
class SourceUnit:
    title: str
    lines: list
    category_path: tuple
    heading_path: tuple
    start_line: int
    occurrence: int = 1

    @property
    def content(self):
        return "\n".join(self.lines).strip()


@dataclass
class SourceMarkerPlan:
    filepath: str
    source_rel_path: str
    original_content: str
    markers: list
    heading_count: int
    document_root_count: int
    normalized_marker_count: int = 0


def parse_markdown_into_units(filepath, tree):
    with open(filepath, "r", encoding="utf-8") as file_obj:
        lines = file_obj.read().splitlines()

    log_name = os.path.splitext(os.path.basename(filepath))[0].strip()
    category_context = ()
    heading_context = [""] * CATEGORY_LEVELS
    units = []
    current = None
    first_heading = True

    def finish_current():
        nonlocal current
        if current and current.content:
            units.append(current)
        current = None

    for line_number, line in enumerate(lines, 1):
        match = HEADING_RE.match(line)
        if not match:
            if current is None:
                current = SourceUnit(log_name, [], category_context, tuple(), line_number)
            current.lines.append(line)
            continue

        hashes, heading_text = match.groups()
        level = len(hashes)
        heading_text = heading_text.strip()
        if not heading_text:
            if current is None:
                current = SourceUnit(log_name, [], category_context, tuple(), line_number)
            current.lines.append(line)
            first_heading = False
            continue

        if level == 1 and is_page_title(heading_text, log_name, first_heading, tree):
            first_heading = False
            continue
        first_heading = False

        heading_context[level - 1] = heading_text
        for index in range(level, CATEGORY_LEVELS):
            heading_context[index] = ""

        previous_context = category_context
        if level == 1:
            matched_path = tree.match_child((), heading_text)
            category_context = matched_path or ()
        else:
            parent_path = previous_context[: level - 1]
            matched_path = None
            if len(parent_path) == level - 1:
                matched_path = tree.match_child(parent_path, heading_text)
            category_context = matched_path or parent_path

        # H1/H2 remain author-facing content boundaries, matching the legacy
        # organizer's useful granularity. H3-H5 split only when they change the
        # recognized category path; ordinary nested headings stay in the unit.
        starts_new_unit = current is None or level <= 2 or category_context != previous_context
        if starts_new_unit:
            finish_current()
            current = SourceUnit(
                title=heading_text,
                lines=[line],
                category_path=category_context,
                heading_path=tuple(value for value in heading_context if value),
                start_line=line_number,
            )
        else:
            current.lines.append(line)

    finish_current()

    occurrence_counts = defaultdict(int)
    for unit in units:
        signature = tuple(normalize_name(value) for value in unit.heading_path) or (
            normalize_name(unit.title),
        )
        occurrence_counts[signature] += 1
        unit.occurrence = occurrence_counts[signature]
    return log_name, units


def clean_match_text(value):
    value = re.sub(r"!\[\[.*?\]\]", " ", value)
    value = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", value)
    value = re.sub(r"<!--.*?-->", " ", value, flags=re.DOTALL)
    return value.casefold()


def node_matches(node, text, text_no_spaces):
    return any(keyword_matches_text(keyword, text, text_no_spaces) for keyword in node.keywords)


def is_prefix(prefix, path):
    return len(prefix) <= len(path) and tuple(path[: len(prefix)]) == tuple(prefix)


def qualify_keyword_path(path, primary_path, tree, text, text_no_spaces):
    node = tree.nodes[path]
    if not node_matches(node, text, text_no_spaces):
        return False

    for level in range(2, len(path)):
        ancestor = path[:level]
        if is_prefix(ancestor, primary_path):
            continue
        ancestor_node = tree.nodes.get(ancestor)
        if ancestor_node and ancestor_node.keywords:
            if not node_matches(ancestor_node, text, text_no_spaces):
                return False
    return True


def remove_ancestor_candidates(paths):
    unique = []
    for path in sorted(set(paths), key=lambda value: (-len(value), value)):
        if any(is_prefix(path, existing) for existing in unique):
            continue
        unique.append(path)
    return sorted(unique)


def extract_manual_categories(content, tree):
    lines = content.splitlines()
    checked = 0
    for index, raw_line in enumerate(lines):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or SOURCE_ID_RE.fullmatch(stripped):
            continue
        checked += 1
        match = re.match(r"^(Category|분류)\s*:\s*(.*)$", stripped, re.IGNORECASE)
        if match:
            resolved = []
            invalid = []
            raw_paths = [value.strip() for value in match.group(2).split(",") if value.strip()]
            for raw_path in raw_paths:
                values = [value.strip() for value in re.split(r"[/>]", raw_path) if value.strip()]
                path = tree.resolve_manual_path(values)
                if path:
                    resolved.append(path)
                else:
                    invalid.append(raw_path)
            del lines[index]
            return resolved, invalid, "\n".join(lines).strip()
        if checked >= 4:
            break
    return [], [], content


def classify_unit(unit, tree, level1_hint=None):
    manual_paths, invalid_manual, clean_content = extract_manual_categories(unit.content, tree)
    clean_content = SOURCE_ID_RE.sub("", clean_content).strip()
    if manual_paths:
        return {
            "paths": sorted(set(manual_paths)),
            "primary_path": manual_paths[0],
            "basis_by_path": {path: "manual" for path in manual_paths},
            "needs_review": bool(invalid_manual),
            "issues": [f"Unknown manual category: {value}" for value in invalid_manual],
            "content": clean_content,
        }

    manual_issues = [f"Unknown manual category: {value}" for value in invalid_manual]

    primary = tuple(unit.category_path)
    inherited_legacy_level1 = False
    if not primary and level1_hint:
        matched_root = tree.match_child((), level1_hint)
        if matched_root:
            primary = matched_root
            inherited_legacy_level1 = True
    if not primary:
        missing_path = ("Unclassified", "Missing Level 1")
        return {
            "paths": [missing_path],
            "primary_path": (),
            "basis_by_path": {missing_path: "missing-level-1"},
            "needs_review": True,
            "issues": manual_issues + ["No recognized Level 1 Heading is active."],
            "content": clean_content,
        }

    # Supplemental keywords should describe the section's opening context, not
    # every topic mentioned later in a long meeting note or test transcript.
    corpus = " ".join(unit.heading_path) + "\n" + clean_content[:800]
    text = clean_match_text(corpus)
    text_no_spaces = re.sub(r"\s+", "", text)
    candidates = []
    for path, _node in tree.iter_keyword_nodes(primary[0]):
        if path == primary or is_prefix(path, primary):
            continue
        if qualify_keyword_path(path, primary, tree, text, text_no_spaces):
            candidates.append(path)
    candidates = remove_ancestor_candidates(candidates)

    descendants = [path for path in candidates if is_prefix(primary, path)]
    divergent = [path for path in candidates if not is_prefix(primary, path)]
    paths = remove_ancestor_candidates((descendants or [primary]) + divergent)
    basis_by_path = {}
    for path in paths:
        if path == primary:
            if inherited_legacy_level1:
                basis_by_path[path] = "legacy-level1"
            else:
                basis_by_path[path] = (
                    "heading-fallback" if tree.has_children(primary) else "heading-exact"
                )
        else:
            basis_by_path[path] = (
                "keyword-refinement" if is_prefix(primary, path) else "keyword-supplement"
            )

    needs_review = bool(manual_issues)
    issues = list(manual_issues)
    if paths == [primary] and tree.has_children(primary):
        needs_review = True
        issues.append(f"Stopped at parent category: {' > '.join(primary)}")

    return {
        "paths": paths,
        "primary_path": primary,
        "basis_by_path": basis_by_path,
        "needs_review": needs_review,
        "issues": issues,
        "content": clean_content,
        "legacy_level1_hint": inherited_legacy_level1,
    }


def is_meaningless_content(content):
    body = re.sub(r"^#{1,5}\s+.*$", "", content, flags=re.MULTILINE)
    body = SOURCE_ID_RE.sub("", body)
    body = re.sub(r"[-*_\s]", "", body)
    return not body


def is_document_preamble(unit):
    if unit.heading_path:
        return False
    meaningful = []
    for raw_line in unit.content.splitlines():
        line = raw_line.strip()
        if not line or line in {"---", "***", "___"}:
            continue
        if re.match(r"^\*\*(Date|날짜)\*\*\s*:", line, re.IGNORECASE):
            continue
        if re.match(r"^(date|created|modified)\s*:", line, re.IGNORECASE):
            continue
        meaningful.append(line)
    return not meaningful


def extract_date_prefix(log_name):
    match = re.match(r"^(\d{2}\.\d{2}\.\d{2}|\d{6})", log_name)
    return match.group(1) if match else None


def escape_markdown_link_label(value):
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("[", "\\[")
        .replace("]", "\\]")
    )


def make_markdown_link(from_rel_path, target_rel_path, label=None):
    source_dir = os.path.dirname(normalize_rel_path(from_rel_path)) or "."
    target = normalize_rel_path(target_rel_path)
    relative_target = normalize_rel_path(os.path.relpath(target, source_dir))
    encoded_target = quote(relative_target, safe="/-._~")
    display_text = label or os.path.splitext(os.path.basename(target))[0]
    return f"[{escape_markdown_link_label(display_text)}]({encoded_target})"


def load_metadata(path):
    metadata = load_json_state(
        path,
        missing_default={},
        expected_type=dict,
        label="classification metadata",
    )
    if "entries" in metadata and not isinstance(metadata["entries"], dict):
        raise StateFileError(
            f"Invalid classification metadata {path}: 'entries' must be an object."
        )
    return metadata


def build_id_indexes(metadata):
    by_anchor = {}
    by_heading = defaultdict(list)
    entries = metadata.get("entries", {}) if isinstance(metadata, dict) else {}
    for source_id, entry in entries.items():
        if not isinstance(entry, dict):
            continue
        anchor = entry.get("source_anchor")
        if anchor:
            by_anchor[anchor] = source_id
        source_path = entry.get("source_path", "")
        heading = normalize_name(entry.get("source_heading", ""))
        if source_path and heading:
            by_heading[(source_path, heading)].append(source_id)
    return by_anchor, by_heading


def build_legacy_level1_hints(metadata, tree):
    hints = defaultdict(set)
    entries = metadata.get("entries", {}) if isinstance(metadata, dict) else {}
    for entry in entries.values():
        if not isinstance(entry, dict):
            continue
        source_path = normalize_rel_path(entry.get("source_path", ""))
        heading = normalize_name(entry.get("source_heading", ""))
        if not source_path or not heading:
            continue
        for generated_path in entry.get("generated_paths", []):
            parts = [part for part in normalize_rel_path(generated_path).split("/") if part]
            if len(parts) < 3 or parts[0].casefold() != "subject":
                continue
            matched_root = tree.match_child((), parts[1])
            if matched_root:
                hints[(source_path, heading)].add(matched_root[0])
    return hints


def resolve_legacy_level1_hint(source_rel_path, unit, hints):
    candidates = set()
    for heading in reversed(unit.heading_path):
        candidates.update(hints.get((source_rel_path, normalize_name(heading)), set()))
        if len(candidates) == 1:
            return next(iter(candidates))
        if len(candidates) > 1:
            return None
    candidates.update(hints.get((source_rel_path, normalize_name(unit.title)), set()))
    return next(iter(candidates)) if len(candidates) == 1 else None


def make_source_anchor(source_rel_path, unit):
    heading_key = "/".join(normalize_name(value) for value in unit.heading_path)
    return f"{normalize_rel_path(source_rel_path)}::{heading_key}::{unit.occurrence}"


def source_unit_fingerprint(unit):
    return hashlib.sha256(unit.content.encode("utf-8")).hexdigest()


def resolve_source_id(
    source_rel_path,
    unit,
    content,
    new_indexes,
    legacy_indexes,
    used_ids,
    allow_legacy_heading=True,
):
    marker = SOURCE_ID_RE.search(content)
    if marker:
        source_id = marker.group(1).lower()
    else:
        anchor = make_source_anchor(source_rel_path, unit)
        source_id = new_indexes[0].get(anchor)
        if not source_id and allow_legacy_heading:
            legacy_candidates = legacy_indexes[1].get(
                (source_rel_path, normalize_name(unit.title)), []
            )
            if len(legacy_candidates) == 1 and legacy_candidates[0] not in used_ids:
                source_id = legacy_candidates[0]
        if not source_id:
            source_id = hashlib.sha1(anchor.encode("utf-8")).hexdigest()[:16]

    if source_id in used_ids and marker:
        raise RuntimeError(
            f"Duplicate permanent Source ID '{source_id}' in "
            f"{source_rel_path}:{unit.start_line}."
        )
    if source_id in used_ids:
        anchor = make_source_anchor(source_rel_path, unit)
        source_id = hashlib.sha1(f"{anchor}::{source_id}".encode("utf-8")).hexdigest()[:16]
    used_ids.add(source_id)
    return source_id


def find_frontmatter_end(lines):
    if not lines or lines[0].strip() != "---":
        return None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return index
    return None


def source_id_comment(source_id):
    return f"<!-- {SOURCE_ID_MARKER_NAME}: {source_id.lower()} -->"


def normalize_source_id_comments(content):
    changed = 0

    def replace(match):
        nonlocal changed
        replacement = source_id_comment(match.group(1))
        if match.group(0) != replacement:
            changed += 1
        return replacement

    return SOURCE_ID_RE.sub(replace, content), changed


def render_source_id_markers(original_content, markers):
    newline = "\r\n" if "\r\n" in original_content else "\n"
    had_final_newline = original_content.endswith(("\n", "\r"))
    normalized_content, normalized_count = normalize_source_id_comments(original_content)
    lines = normalized_content.splitlines()
    existing_ids = {
        match.group(1).lower()
        for match in SOURCE_ID_RE.finditer(original_content)
    }
    frontmatter_end = find_frontmatter_end(lines)
    pending = []

    for line_number, source_id in markers:
        source_id = source_id.lower()
        if source_id in existing_ids:
            continue
        start_index = line_number - 1
        if start_index < 0 or start_index > len(lines):
            raise RuntimeError(
                f"Invalid Source ID insertion line {line_number}."
            )
        is_heading = (
            start_index < len(lines)
            and HEADING_RE.match(lines[start_index]) is not None
        )
        if is_heading:
            insert_index = start_index + 1
            placement = "heading"
        else:
            insert_index = start_index
            if frontmatter_end is not None and insert_index <= frontmatter_end:
                insert_index = frontmatter_end + 1
            placement = "document-root"
        while insert_index < len(lines) and not lines[insert_index].strip():
            insert_index += 1
        pending.append((insert_index, source_id, placement))
        existing_ids.add(source_id)

    for insert_index, source_id, _placement in sorted(pending, reverse=True):
        lines.insert(insert_index, source_id_comment(source_id))

    updated = newline.join(lines)
    if had_final_newline:
        updated += newline
    heading_count = sum(placement == "heading" for _, _, placement in pending)
    document_root_count = len(pending) - heading_count
    return updated, len(pending), heading_count, document_root_count, normalized_count


def atomic_replace_text(filepath, content, stat_source=None):
    directory = os.path.dirname(filepath)
    descriptor, temp_path = tempfile.mkstemp(
        prefix=".research-notes-source-id-",
        suffix=".tmp",
        dir=directory,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as file_obj:
            file_obj.write(content)
        if stat_source and os.path.exists(stat_source):
            shutil.copystat(stat_source, temp_path)
        os.replace(temp_path, filepath)
    except Exception:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def build_source_marker_plans(
    daily_logs_dir,
    vault_dir,
    tree,
    new_indexes,
    legacy_indexes,
    allow_legacy_heading=True,
):
    plans = []
    used_ids = set()
    existing_count = 0

    for root, dirnames, filenames in os.walk(daily_logs_dir):
        dirnames.sort()
        for filename in sorted(filenames):
            if not filename.casefold().endswith(".md"):
                continue
            filepath = os.path.join(root, filename)
            with open(filepath, "r", encoding="utf-8", newline="") as file_obj:
                original_content = file_obj.read()
            source_rel_path = normalize_rel_path(os.path.relpath(filepath, vault_dir))
            _log_name, units = parse_markdown_into_units(filepath, tree)
            with open(filepath, "r", encoding="utf-8", newline="") as file_obj:
                if file_obj.read() != original_content:
                    raise RuntimeError(
                        f"Source file changed while it was being scanned: {source_rel_path}"
                    )

            markers = []
            heading_count = 0
            document_root_count = 0
            for unit in units:
                if is_document_preamble(unit):
                    continue
                classification = classify_unit(unit, tree)
                if is_meaningless_content(classification["content"]):
                    continue
                found_markers = SOURCE_ID_RE.findall(unit.content)
                if len(found_markers) > 1:
                    raise RuntimeError(
                        f"Multiple Source ID markers belong to one source unit: "
                        f"{source_rel_path}:{unit.start_line}"
                    )
                source_id = resolve_source_id(
                    source_rel_path,
                    unit,
                    unit.content,
                    new_indexes,
                    legacy_indexes,
                    used_ids,
                    allow_legacy_heading=allow_legacy_heading,
                )
                if found_markers:
                    existing_count += 1
                    continue
                markers.append((unit.start_line, source_id))
                first_line = unit.content.splitlines()[0] if unit.content else ""
                if HEADING_RE.match(first_line):
                    heading_count += 1
                else:
                    document_root_count += 1

            _normalized_content, normalized_marker_count = normalize_source_id_comments(
                original_content
            )
            if markers or normalized_marker_count:
                plans.append(
                    SourceMarkerPlan(
                        filepath=filepath,
                        source_rel_path=source_rel_path,
                        original_content=original_content,
                        markers=markers,
                        heading_count=heading_count,
                        document_root_count=document_root_count,
                        normalized_marker_count=normalized_marker_count,
                    )
                )
    return plans, existing_count


def persist_source_marker_plans(plans, backup_root, vault_dir, dry_run=False):
    total = sum(len(plan.markers) for plan in plans)
    heading_count = sum(plan.heading_count for plan in plans)
    document_root_count = sum(plan.document_root_count for plan in plans)
    normalized_count = sum(plan.normalized_marker_count for plan in plans)
    if dry_run or not plans:
        return total, heading_count, document_root_count, normalized_count, None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    batch_backup_root = os.path.join(backup_root, "automatic", timestamp)
    prepared = []
    committed = []
    try:
        for plan in plans:
            (
                updated,
                inserted,
                rendered_headings,
                rendered_roots,
                rendered_normalized,
            ) = render_source_id_markers(plan.original_content, plan.markers)
            if (
                inserted != len(plan.markers)
                or rendered_headings != plan.heading_count
                or rendered_roots != plan.document_root_count
                or rendered_normalized != plan.normalized_marker_count
            ):
                raise RuntimeError(
                    f"Source ID insertion plan changed unexpectedly: {plan.source_rel_path}"
                )
            backup_path = os.path.join(
                batch_backup_root,
                os.path.relpath(plan.filepath, vault_dir),
            )
            os.makedirs(os.path.dirname(backup_path), exist_ok=True)
            shutil.copy2(plan.filepath, backup_path)

            descriptor, temp_path = tempfile.mkstemp(
                prefix=".research-notes-source-id-",
                suffix=".tmp",
                dir=os.path.dirname(plan.filepath),
            )
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as file_obj:
                file_obj.write(updated)
            shutil.copystat(plan.filepath, temp_path)
            prepared.append((plan, temp_path, backup_path))

        for plan, temp_path, backup_path in prepared:
            with open(plan.filepath, "r", encoding="utf-8", newline="") as file_obj:
                current_content = file_obj.read()
            if current_content != plan.original_content:
                raise RuntimeError(
                    f"Source file changed before Source IDs were saved: "
                    f"{plan.source_rel_path}"
                )
            os.replace(temp_path, plan.filepath)
            committed.append((plan, backup_path))

    except Exception as exc:
        rollback_failures = []
        for plan, backup_path in reversed(committed):
            try:
                atomic_replace_text(
                    plan.filepath,
                    plan.original_content,
                    stat_source=backup_path,
                )
            except Exception as rollback_exc:
                rollback_failures.append(
                    f"{plan.source_rel_path}: {rollback_exc}"
                )
        for _plan, temp_path, _backup_path in prepared:
            try:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
            except OSError:
                pass
        rollback_note = (
            f" Rollback failures: {'; '.join(rollback_failures)}"
            if rollback_failures
            else ""
        )
        raise RuntimeError(
            f"Failed to persist Source ID markers.{rollback_note}"
        ) from exc

    return total, heading_count, document_root_count, normalized_count, batch_backup_root


def make_target_filename(log_name, title, source_id, claimed_paths, category_path):
    date_prefix = extract_date_prefix(log_name)
    safe_title = sanitize_filename(title)
    if date_prefix and safe_title.startswith(date_prefix):
        filename = f"{safe_title}.md"
    elif date_prefix:
        filename = f"{date_prefix} - {safe_title}.md"
    else:
        filename = f"{sanitize_filename(log_name)} - {safe_title}.md"

    key = (tuple(category_path), filename.casefold())
    if key in claimed_paths and claimed_paths[key] != source_id:
        stem, extension = os.path.splitext(filename)
        filename = f"{stem} [{source_id[:8]}]{extension}"
        key = (tuple(category_path), filename.casefold())
    claimed_paths[key] = source_id
    return filename


def build_subject_content(
    log_name,
    source_rel_path,
    unit,
    source_id,
    classification,
    path,
    generated_rel_path,
):
    source_link = make_markdown_link(generated_rel_path, source_rel_path, log_name)
    heading_path = " > ".join(unit.heading_path) or unit.title
    primary_path = " > ".join(classification["primary_path"]) or "(none)"
    lines = [
        AUTO_GENERATED_SUBJECT + "\n",
        f"**Date/Log**: {source_link}\n",
        f"**Source ID**: `{source_id}`\n",
        f"**Source Path**: `{source_rel_path}`\n",
        f"**Source Heading**: {unit.title}\n",
        f"**Source Heading Path**: {heading_path}\n",
        f"**Primary Category**: {primary_path}\n",
        f"**Category**: {' > '.join(path)}\n",
        f"**Classification Basis**: {classification['basis_by_path'][path]}\n",
        f"**Needs Review**: {'true' if classification['needs_review'] else 'false'}\n\n",
        "---\n\n",
        classification["content"].rstrip() + "\n",
    ]
    return "".join(lines)


def source_date_key(value):
    stem = os.path.splitext(os.path.basename(value))[0]
    dotted = re.match(r"^(\d{2})\.(\d{2})\.(\d{2})", stem)
    if dotted:
        return f"20{dotted.group(1)}-{dotted.group(2)}-{dotted.group(3)}"
    compact = re.match(r"^(\d{2})(\d{2})(\d{2})", stem)
    if compact:
        return f"20{compact.group(1)}-{compact.group(2)}-{compact.group(3)}"
    return "0000-00-00"


def extract_review_text(content):
    cleaned = []
    in_code_block = False
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if line.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block or not line:
            continue
        if line.startswith("#") or line.startswith("![[") or line.startswith("![]("):
            continue
        if line in {"---", "***", "___"} or re.fullmatch(r"\|?\s*:?[-]+.*", line):
            continue
        if line.startswith("|") and line.endswith("|"):
            continue
        line = re.sub(r"^>\s*(?:\[![^]]+\]\s*)?", "", line).strip()
        if line.startswith("#"):
            continue
        line = re.sub(r"^[-*+]\s+", "", line).strip()
        line = re.sub(r"^\d+[.)]\s+", "", line).strip()
        if not line:
            continue
        cleaned.append(re.sub(r"\s+", " ", line)[:240])

    summaries = cleaned[:2]
    issue_lines = []
    lowered_keywords = tuple(keyword.casefold() for keyword in ISSUE_HINT_KEYWORDS)
    for line in cleaned:
        lowered = line.casefold()
        if any(keyword in lowered for keyword in lowered_keywords):
            issue_lines.append(line)
        if len(issue_lines) >= 3:
            break
    return summaries, issue_lines


def merge_review_records(records):
    merged = {}
    for record in records:
        key = record.get("source_id") or f"{record['source_path']}:{record['source_line']}"
        current = merged.get(key)
        if current is None:
            current = dict(record)
            current["subject_documents"] = []
            current["matched_categories"] = []
            current["summary_lines"] = list(record.get("summary_lines", []))
            current["issue_lines"] = list(record.get("issue_lines", []))
            merged[key] = current

        document = (
            record["generated_path"],
            tuple(record["category_path"]),
            record["title"],
        )
        if document not in current["subject_documents"]:
            current["subject_documents"].append(document)
        category = tuple(record["category_path"])
        if category not in current["matched_categories"]:
            current["matched_categories"].append(category)
        for summary in record.get("summary_lines", []):
            if summary not in current["summary_lines"] and len(current["summary_lines"]) < 2:
                current["summary_lines"].append(summary)
        for issue in record.get("issue_lines", []):
            if issue not in current["issue_lines"]:
                current["issue_lines"].append(issue)

    values = list(merged.values())
    for record in values:
        record["subject_documents"].sort(key=lambda value: (value[1], value[0]))
        record["matched_categories"].sort()
        record["generated_path"] = record["subject_documents"][0][0]
    values.sort(
        key=lambda value: (
            source_date_key(value["source_log"]),
            value["source_path"],
            value["source_line"],
        )
    )
    return values


def append_review_record(
    lines,
    record,
    category_path,
    review_rel_path,
    include_source_id=False,
):
    subject_path, _full_category, _title = record["subject_documents"][0]
    subject_link = make_markdown_link(review_rel_path, subject_path, record["title"])
    source_link = make_markdown_link(
        review_rel_path,
        record["source_path"],
        record["source_log"],
    )
    source_id_part = (
        f" / Source ID: `{record['source_id']}`" if include_source_id else ""
    )
    lines.append(f"- {subject_link} / 원본: {source_link}{source_id_part}\n")

    if len(record["subject_documents"]) > 1:
        links = []
        for path, full_category, _document_title in record["subject_documents"]:
            relative_category = full_category[len(category_path):]
            label = " > ".join(relative_category) or full_category[-1]
            links.append(make_markdown_link(review_rel_path, path, label))
        lines.append(f"  - 하위 문서: {', '.join(links)}\n")
    if record["summary_lines"]:
        lines.append(f"  - {record['summary_lines'][0]}\n")


def write_reviews(vault_dir, review_dir_name, generated_records, dry_run=False):
    grouped = defaultdict(list)
    for record in generated_records:
        full_path = tuple(record["category_path"])
        for depth in range(1, len(full_path) + 1):
            grouped[full_path[:depth]].append(record)

    merged_groups = {
        category_path: merge_review_records(records)
        for category_path, records in grouped.items()
    }
    group_paths = set(merged_groups)
    children = {
        category_path: sorted(
            child
            for child in group_paths
            if len(child) == len(category_path) + 1 and is_prefix(category_path, child)
        )
        for category_path in group_paths
    }
    review_paths = {}
    for category_path in group_paths:
        leaf = category_path[-1]
        prefix = "[종합 리뷰]" if children[category_path] else "[리뷰]"
        review_paths[category_path] = normalize_rel_path(
            os.path.join(
                review_dir_name,
                *category_path,
                f"{prefix} {sanitize_filename(leaf)}.md",
            )
        )

    desired = {}
    for category_path in sorted(group_paths):
        review_rel_path = review_paths[category_path]
        records = merged_groups[category_path]
        child_paths = children[category_path]
        leaf = category_path[-1]
        is_aggregate = bool(child_paths)
        detail_limit = 20 if len(category_path) == 1 else 50 if len(category_path) == 2 else None
        detail_records = records[-detail_limit:] if detail_limit else records
        omitted_count = len(records) - len(detail_records)
        recent_records = list(reversed(detail_records[-5:]))
        issue_limit = 20 if len(category_path) <= 2 else 12
        issue_items = []
        for record in reversed(records):
            for issue_line in record["issue_lines"]:
                item = (record, issue_line)
                if item not in issue_items:
                    issue_items.append(item)
                if len(issue_items) >= issue_limit:
                    break
            if len(issue_items) >= issue_limit:
                break

        source_logs = {record["source_path"] for record in records}
        heading_label = "종합 리뷰" if is_aggregate else "리뷰"
        latest_link = (
            make_markdown_link(
                review_rel_path,
                recent_records[0]["generated_path"],
                recent_records[0]["title"],
            )
            if recent_records
            else "-"
        )
        lines = [
            AUTO_GENERATED_REVIEW + "\n",
            f"# {leaf} {heading_label}\n\n",
            f"**Category**: {' > '.join(category_path)}\n",
            f"**Entries**: {len(records)}\n",
            f"**Source Logs**: {len(source_logs)}\n\n",
            "---\n\n",
            "## 리뷰 스냅샷\n\n",
            f"- 최신 기록: {latest_link}\n",
            f"- 관련 원본 로그 수: {len(source_logs)}\n",
            f"- 확인할 이슈 후보: {len(issue_items)}\n\n",
        ]

        if child_paths:
            lines.append("## 하위 리뷰\n\n")
            for child_path in child_paths:
                child_link = make_markdown_link(
                    review_rel_path,
                    review_paths[child_path],
                    child_path[-1],
                )
                lines.append(
                    f"- {child_link} / 소스 {len(merged_groups[child_path])}건\n"
                )
            lines.append("\n")

        lines.append("## 최근 업데이트\n\n")
        if recent_records:
            for record in recent_records:
                append_review_record(lines, record, category_path, review_rel_path)
        else:
            lines.append("- 최근 업데이트가 없습니다.\n")

        lines.append("\n## 진행 흐름\n\n")
        if omitted_count:
            lines.append(
                f"- 상위 리뷰에서는 최근 {len(detail_records)}건을 표시합니다. "
                f"이전 {omitted_count}건은 하위 리뷰에서 확인할 수 있습니다.\n"
            )
        current_date = None
        for record in detail_records:
            date_key = source_date_key(record["source_log"])
            if date_key != current_date:
                current_date = date_key
                if date_key != "0000-00-00":
                    lines.append(f"\n### {date_key}\n\n")
            append_review_record(
                lines,
                record,
                category_path,
                review_rel_path,
                include_source_id=True,
            )

        lines.append("\n## 확인할 이슈 후보\n\n")
        if issue_items:
            for record, issue_line in issue_items:
                subject_link = make_markdown_link(
                    review_rel_path,
                    record["generated_path"],
                    record["title"],
                )
                lines.append(f"- {subject_link}: {issue_line}\n")
        else:
            lines.append("- 자동 추출된 이슈 후보가 없습니다.\n")

        lines.append("\n## 관련 소스 문서\n\n")
        if omitted_count:
            lines.append(f"- 최근 {len(detail_records)}건만 표시합니다.\n")
        for record in detail_records:
            append_review_record(
                lines,
                record,
                category_path,
                review_rel_path,
                include_source_id=True,
            )

        desired[review_rel_path] = "".join(lines)

    if not dry_run:
        for rel_path, content in desired.items():
            full_path = os.path.join(vault_dir, rel_path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as file_obj:
                file_obj.write(content)
        cleanup_generated_root(vault_dir, review_dir_name, set(desired), AUTO_GENERATED_REVIEW)
    return sorted(desired)


def cleanup_generated_root(vault_dir, root_name, desired_paths, marker):
    root_path = os.path.join(vault_dir, root_name)
    if not os.path.isdir(root_path):
        return 0
    desired = {os.path.normcase(os.path.normpath(path)) for path in desired_paths}
    deleted = 0
    for dirpath, _dirnames, filenames in os.walk(root_path):
        for filename in filenames:
            if not filename.casefold().endswith(".md"):
                continue
            full_path = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(full_path, vault_dir)
            if os.path.normcase(os.path.normpath(rel_path)) in desired:
                continue
            try:
                with open(full_path, "r", encoding="utf-8") as file_obj:
                    first_line = file_obj.readline().strip()
                marker_kind = (
                    "hierarchical subject"
                    if marker == AUTO_GENERATED_SUBJECT
                    else "hierarchical review"
                )
                is_managed_marker = (
                    first_line.startswith("<!-- AUTO-GENERATED: ")
                    and first_line.endswith(f" {marker_kind}. -->")
                )
                if first_line == marker or is_managed_marker:
                    os.remove(full_path)
                    deleted += 1
            except OSError:
                pass
    for dirpath, _dirnames, _filenames in os.walk(root_path, topdown=False):
        if dirpath == root_path:
            continue
        try:
            if not os.listdir(dirpath):
                os.rmdir(dirpath)
        except OSError:
            pass
    return deleted


def write_report(report_path, stats, issues, dry_run):
    lines = [
        "# Hierarchical Classification Report\n\n",
        f"- Mode: {'dry-run' if dry_run else 'write'}\n",
        f"- Generated: {datetime.now().isoformat(timespec='seconds')}\n",
        f"- Source files: {stats['source_files']}\n",
        f"- Source units: {stats['source_units']}\n",
        f"- Generated subject files: {stats['generated_files']}\n",
        f"- Keyword refinements: {stats['keyword_refinements']}\n",
        f"- Keyword supplements: {stats['keyword_supplements']}\n",
        f"- Legacy Level 1 hints: {stats['legacy_level1_hints']}\n",
        f"- Needs review: {stats['needs_review']}\n",
        f"- Missing Level 1: {stats['missing_level1']}\n\n",
        f"- Existing Source ID markers: {stats['source_id_markers_existing']}\n",
        f"- Source ID markers inserted: {stats['source_id_markers']}\n",
        f"- Source ID markers normalized: {stats['source_id_markers_normalized']}\n",
        f"- Document-root markers inserted: {stats['source_id_document_root_markers']}\n\n",
        "## Review Items\n\n",
    ]
    if issues:
        for issue in issues:
            lines.append(
                f"- `{issue['source_path']}:{issue['line']}` {issue['title']}: "
                f"{'; '.join(issue['issues'])}\n"
            )
    else:
        lines.append("- None\n")

    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as file_obj:
        file_obj.write("".join(lines))


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Generate hierarchical Subject and review trees. The default writes to "
            "parallel preview folders; --production explicitly enables production roots."
        )
    )
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--review-dir", default=DEFAULT_REVIEW_DIR)
    parser.add_argument("--metadata-file", default=DEFAULT_METADATA_FILE)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--validate-rules", action="store_true")
    parser.add_argument("--no-reviews", action="store_true")
    parser.add_argument(
        "--production",
        action="store_true",
        help="Allow the exact Subject/Topic_Reviews/organizer_metadata.json production targets.",
    )
    source_id_group = parser.add_mutually_exclusive_group()
    source_id_group.add_argument(
        "--initialize-source-ids",
        action="store_true",
        help=(
            "Persist missing Source ID comments in preview mode too. Production "
            "mode already persists them automatically."
        ),
    )
    source_id_group.add_argument(
        "--no-persist-source-ids",
        action="store_true",
        help=(
            "Emergency read-only mode: do not persist missing Source ID comments. "
            "This weakens identity stability for new source units."
        ),
    )
    return parser.parse_args(argv)


def validate_output_targets(args):
    output_name = normalize_rel_path(args.output_dir).strip("/")
    review_name = normalize_rel_path(args.review_dir).strip("/")
    metadata_name = os.path.basename(args.metadata_file)

    if args.production:
        expected = (
            PRODUCTION_OUTPUT_DIR,
            PRODUCTION_REVIEW_DIR,
            PRODUCTION_METADATA_FILE,
        )
        actual = (output_name, review_name, metadata_name)
        if actual != expected:
            return (
                "Production mode requires --output-dir Subject, "
                "--review-dir Topic_Reviews, and --metadata-file organizer_metadata.json."
            )
        return ""

    forbidden_roots = {
        PRODUCTION_OUTPUT_DIR.casefold(),
        PRODUCTION_REVIEW_DIR.casefold(),
        "daily_logs",
        "attachments",
    }
    if output_name.casefold() in forbidden_roots or review_name.casefold() in forbidden_roots:
        return "Preview mode must not use production or source roots."
    return ""


def should_persist_source_ids(args):
    return (
        args.production or args.initialize_source_ids
    ) and not args.no_persist_source_ids


def count_daily_markdown_files(daily_logs_dir):
    walk_errors = []

    def record_walk_error(error):
        walk_errors.append(error)

    count = 0
    for _root, _dirnames, filenames in os.walk(
        daily_logs_dir,
        onerror=record_walk_error,
    ):
        count += sum(
            1 for filename in filenames if filename.casefold().endswith(".md")
        )

    if walk_errors:
        details = "; ".join(str(error) for error in walk_errors)
        raise OSError(f"Could not fully scan Daily_Logs: {details}")
    return count


def _main_unlocked(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    args = parse_args(argv)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    vault_dir = os.path.abspath(os.path.join(script_dir, ".."))
    rules_path = os.path.join(vault_dir, "Classification_Rules.md")
    daily_logs_dir = os.path.join(vault_dir, "Daily_Logs")
    metadata_path = os.path.join(script_dir, args.metadata_file)
    report_path = os.path.join(script_dir, "reports", "hierarchical_classification_report.md")
    source_id_backup_root = os.path.join(script_dir, "source_id_backups")

    target_error = validate_output_targets(args)
    if target_error:
        print(f"Error: {target_error}")
        return 2

    tree = parse_rules_from_markdown(rules_path)
    print(f"Loaded {len(tree.nodes)} category nodes from the inherited table.")
    if tree.errors:
        for error in tree.errors:
            print(f"Rule error: {error}")
        return 2
    if args.validate_rules:
        print(f"Rule validation passed with {len(tree.warnings)} optional-keyword notices.")
        return 0

    if not os.path.isdir(daily_logs_dir):
        print(f"Error: Daily logs directory does not exist: {daily_logs_dir}")
        return 2

    try:
        source_file_count = count_daily_markdown_files(daily_logs_dir)
    except OSError as exc:
        print(f"Error: {exc}")
        print("Existing Subject, Topic_Reviews, and metadata were left unchanged.")
        return 2
    if source_file_count == 0:
        print(f"Error: No Markdown files were found under {daily_logs_dir}")
        print("Existing Subject, Topic_Reviews, and metadata were left unchanged.")
        return 2

    try:
        previous_metadata = load_metadata(metadata_path)
        legacy_metadata = load_metadata(os.path.join(script_dir, "organizer_metadata.json"))
    except StateFileError as exc:
        print(f"Error: {exc}")
        print("Existing Subject, Topic_Reviews, and metadata were left unchanged.")
        return 2
    new_indexes = build_id_indexes(previous_metadata)
    legacy_indexes = build_id_indexes(legacy_metadata)
    legacy_level1_hints = build_legacy_level1_hints(legacy_metadata, tree)
    try:
        previous_schema_version = int(previous_metadata.get("schema_version", 0))
    except (TypeError, ValueError):
        previous_schema_version = 0
    allow_legacy_heading_fallback = previous_schema_version < METADATA_SCHEMA_VERSION
    persist_source_ids = should_persist_source_ids(args)

    source_id_marker_count = 0
    source_id_heading_marker_count = 0
    source_id_document_root_marker_count = 0
    source_id_normalized_marker_count = 0
    source_id_existing_marker_count = 0
    source_id_backup_batch = None
    if persist_source_ids:
        try:
            marker_plans, source_id_existing_marker_count = build_source_marker_plans(
                daily_logs_dir,
                vault_dir,
                tree,
                new_indexes,
                legacy_indexes,
                allow_legacy_heading=allow_legacy_heading_fallback,
            )
            (
                source_id_marker_count,
                source_id_heading_marker_count,
                source_id_document_root_marker_count,
                source_id_normalized_marker_count,
                source_id_backup_batch,
            ) = persist_source_marker_plans(
                marker_plans,
                source_id_backup_root,
                vault_dir,
                dry_run=args.dry_run,
            )
        except Exception as exc:
            print(f"Error: Source ID persistence failed: {exc}")
            return 2

    used_ids = set()
    claimed_paths = {}
    entries = {}
    generated_records = []
    desired_subjects = {}
    issues = []
    stats = {
        "source_files": 0,
        "source_units": 0,
        "generated_files": 0,
        "keyword_refinements": 0,
        "keyword_supplements": 0,
        "legacy_level1_hints": 0,
        "needs_review": 0,
        "missing_level1": 0,
        "source_id_markers_existing": source_id_existing_marker_count,
        "source_id_markers": source_id_marker_count,
        "source_id_heading_markers": source_id_heading_marker_count,
        "source_id_document_root_markers": source_id_document_root_marker_count,
        "source_id_markers_normalized": source_id_normalized_marker_count,
    }

    for root, dirnames, filenames in os.walk(daily_logs_dir):
        dirnames.sort()
        for filename in sorted(filenames):
            if not filename.casefold().endswith(".md"):
                continue
            filepath = os.path.join(root, filename)
            source_rel_path = normalize_rel_path(os.path.relpath(filepath, vault_dir))
            log_name, units = parse_markdown_into_units(filepath, tree)
            stats["source_files"] += 1

            for unit in units:
                if is_document_preamble(unit):
                    continue
                level1_hint = resolve_legacy_level1_hint(
                    source_rel_path, unit, legacy_level1_hints
                )
                classification = classify_unit(unit, tree, level1_hint=level1_hint)
                if is_meaningless_content(classification["content"]):
                    continue
                stats["source_units"] += 1
                if classification.get("legacy_level1_hint"):
                    stats["legacy_level1_hints"] += 1
                source_id = resolve_source_id(
                    source_rel_path,
                    unit,
                    unit.content,
                    new_indexes,
                    legacy_indexes,
                    used_ids,
                    allow_legacy_heading=allow_legacy_heading_fallback,
                )
                source_anchor = make_source_anchor(source_rel_path, unit)

                if classification["needs_review"]:
                    stats["needs_review"] += 1
                    issues.append(
                        {
                            "source_path": source_rel_path,
                            "line": unit.start_line,
                            "title": unit.title,
                            "issues": classification["issues"],
                        }
                    )
                if not classification["primary_path"]:
                    stats["missing_level1"] += 1

                generated_paths = []
                summary_lines, issue_lines = extract_review_text(
                    classification["content"]
                )
                for path in classification["paths"]:
                    if classification["basis_by_path"][path] == "keyword-refinement":
                        stats["keyword_refinements"] += 1
                    elif classification["basis_by_path"][path] == "keyword-supplement":
                        stats["keyword_supplements"] += 1
                    filename_out = make_target_filename(
                        log_name, unit.title, source_id, claimed_paths, path
                    )
                    rel_path = normalize_rel_path(
                        os.path.join(args.output_dir, *path, filename_out)
                    )
                    content = build_subject_content(
                        log_name,
                        source_rel_path,
                        unit,
                        source_id,
                        classification,
                        path,
                        rel_path,
                    )
                    desired_subjects[rel_path] = content
                    generated_paths.append(rel_path)
                    generated_records.append(
                        {
                            "source_id": source_id,
                            "source_path": source_rel_path,
                            "source_log": log_name,
                            "source_line": unit.start_line,
                            "title": unit.title,
                            "category_path": list(path),
                            "generated_path": rel_path,
                            "summary_lines": summary_lines,
                            "issue_lines": issue_lines,
                        }
                    )

                entries[source_id] = {
                    "source_path": source_rel_path,
                    "source_log": log_name,
                    "source_heading": unit.title,
                    "source_heading_path": list(unit.heading_path),
                    "source_line": unit.start_line,
                    "source_anchor": source_anchor,
                    "source_fingerprint": source_unit_fingerprint(unit),
                    "primary_category": list(classification["primary_path"]),
                    "needs_review": classification["needs_review"],
                    "review_reasons": list(classification["issues"]),
                    "matched_categories": [
                        {
                            "path": list(path),
                            "basis": classification["basis_by_path"][path],
                        }
                        for path in classification["paths"]
                    ],
                    "generated_paths": generated_paths,
                }

    stats["generated_files"] = len(desired_subjects)
    if not args.dry_run:
        for rel_path, content in desired_subjects.items():
            full_path = os.path.join(vault_dir, rel_path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as file_obj:
                file_obj.write(content)
        deleted = cleanup_generated_root(
            vault_dir, args.output_dir, set(desired_subjects), AUTO_GENERATED_SUBJECT
        )
    else:
        deleted = 0

    review_paths = []
    if not args.no_reviews:
        review_paths = write_reviews(
            vault_dir, args.review_dir, generated_records, dry_run=args.dry_run
        )

    metadata_payload = {
        "schema_version": METADATA_SCHEMA_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "output_dir": args.output_dir,
        "review_dir": args.review_dir,
        "entries": entries,
        "review_paths": review_paths,
        "stats": stats,
    }
    if not args.dry_run:
        atomic_write_json(metadata_path, metadata_payload)
        write_report(report_path, stats, issues, dry_run=False)

    print(f"Source files: {stats['source_files']}")
    print(f"Source units: {stats['source_units']}")
    print(f"Generated subject files: {stats['generated_files']}")
    print(f"Keyword refinements: {stats['keyword_refinements']}")
    print(f"Keyword supplements: {stats['keyword_supplements']}")
    print(f"Legacy Level 1 hints: {stats['legacy_level1_hints']}")
    print(f"Needs review: {stats['needs_review']}")
    print(f"Missing Level 1: {stats['missing_level1']}")
    if persist_source_ids:
        action = "would be inserted" if args.dry_run else "inserted"
        print(f"Existing Source ID markers: {stats['source_id_markers_existing']}")
        print(f"Source ID markers {action}: {stats['source_id_markers']}")
        normalize_action = "would be normalized" if args.dry_run else "normalized"
        print(
            f"Source ID markers {normalize_action}: "
            f"{stats['source_id_markers_normalized']}"
        )
        print(
            f"Document-root Source ID markers {action}: "
            f"{stats['source_id_document_root_markers']}"
        )
        if source_id_backup_batch:
            print(
                "Source ID backups: "
                f"{normalize_rel_path(os.path.relpath(source_id_backup_batch, vault_dir))}"
            )
    print(f"Review files: {len(review_paths)}")
    if deleted:
        print(f"Removed stale generated files: {deleted}")
    if args.dry_run:
        print("Dry-run complete. No files were written.")
    else:
        mode = "Production" if args.production else "Preview"
        print(f"{mode} output written to {args.output_dir}/")
    return 0


def main(argv=None):
    args = parse_args(argv)
    if args.validate_rules or lock_is_delegated_by_parent():
        return _main_unlocked(argv)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    vault_dir = os.path.abspath(os.path.join(script_dir, ".."))
    if args.production:
        operation = "classification-production"
    elif args.dry_run:
        operation = "classification-dry-run"
    else:
        operation = "classification-preview"

    try:
        with VaultProcessLock(
            vault_dir,
            operation,
            command=command_text(__file__, argv),
        ):
            return _main_unlocked(argv)
    except ProcessLockUnavailable as exc:
        print_lock_error(exc)
        return LOCK_BUSY_EXIT_CODE


if __name__ == "__main__":
    raise SystemExit(main())
