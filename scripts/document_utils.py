"""Shared document paths, links, images, dates, and generated-file cleanup."""

import os
import re
from urllib.parse import quote, unquote, urlsplit


AUTO_GENERATED_SUBJECT = "<!-- AUTO-GENERATED: Log2Topic hierarchical subject. -->"


AUTO_GENERATED_REVIEW = "<!-- AUTO-GENERATED: Log2Topic hierarchical review. -->"


def normalize_rel_path(path):
    return path.replace("\\", "/")


def sanitize_filename(name):
    name = re.sub(r'[\\/*?:"<>|]', "_", name or "")
    return name.strip().rstrip(".") or "Untitled"


def is_prefix(prefix, path):
    return len(prefix) <= len(path) and tuple(path[: len(prefix)]) == tuple(prefix)


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


IMAGE_TOKEN_RE = re.compile(
    r"!\[\[([^\]]+)\]\]|!\[([^\]\n]*)\]\(([^)\n]+)\)"
)


def _normalize_image_target(raw_target):
    target = unquote(str(raw_target or "").strip())
    target = target.split("#", 1)[0].strip()
    target = target.split("|", 1)[0].strip()
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1].strip()
    return target


def _is_within_directory(path, directory):
    try:
        return os.path.commonpath([os.path.realpath(path), os.path.realpath(directory)]) == os.path.realpath(directory)
    except ValueError:
        return False


def _resolve_source_image_path(raw_target, source_filepath, vault_dir):
    target = _normalize_image_target(raw_target)
    if not target or urlsplit(target).scheme:
        return None

    vault_root = os.path.realpath(os.path.abspath(vault_dir))
    source_dir = os.path.dirname(os.path.abspath(source_filepath))
    candidates = []
    if os.path.isabs(target):
        candidates.append(target)
    else:
        candidates.extend(
            (
                os.path.join(source_dir, target),
                os.path.join(vault_root, target),
                os.path.join(vault_root, "attachments", os.path.basename(target)),
            )
        )

    for candidate in candidates:
        resolved = os.path.realpath(os.path.abspath(candidate))
        if _is_within_directory(resolved, vault_root) and os.path.isfile(resolved):
            return resolved

    basename = os.path.basename(target)
    for root, _dirs, files in os.walk(vault_root):
        for filename in files:
            if filename.casefold() == basename.casefold():
                resolved = os.path.realpath(os.path.join(root, filename))
                if _is_within_directory(resolved, vault_root):
                    return resolved
    return None


def source_date_key(value):
    stem = os.path.splitext(os.path.basename(value))[0]
    dotted = re.match(r"^(\d{2})\.(\d{2})\.(\d{2})", stem)
    if dotted:
        return f"20{dotted.group(1)}-{dotted.group(2)}-{dotted.group(3)}"
    compact = re.match(r"^(\d{2})(\d{2})(\d{2})", stem)
    if compact:
        return f"20{compact.group(1)}-{compact.group(2)}-{compact.group(3)}"
    return "0000-00-00"


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
