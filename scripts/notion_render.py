import os
import posixpath
import re
from datetime import datetime
from urllib.parse import unquote, urlsplit

from sync_contracts import (
    DAILY_LOGS_CATEGORY_NAME,
    NOTION_PROP_DATE,
    NOTION_PROP_LEVEL_1,
    NOTION_PROP_LEVEL_2,
    NOTION_PROP_LEVEL_3,
    NOTION_PROP_LEVEL_4,
    NOTION_PROP_LEVEL_5,
    NOTION_PROP_SOURCE_HEADING,
    NOTION_PROP_SOURCE_ID,
    NOTION_PROP_SYNC_KEY,
    NOTION_PROP_TITLE,
    normalize_sync_key_part,
)


SOURCE_ID_COMMENT_RE = re.compile(
    r"<!--\s*(?:[a-zA-Z0-9][a-zA-Z0-9_-]*-)?source-id\s*:\s*"
    r"[a-fA-F0-9]{8,64}\s*-->\s*",
    re.IGNORECASE,
)


IMAGE_TOKEN_RE = re.compile(
    r"!\[\[([^\]]+)\]\]|!\[[^\]\n]*\]\(([^)\n]+)\)"
)


def append_rich_text(parts, content, bold=False, code=False, link_url=None):
    limit = 1900
    for i in range(0, len(content), limit):
        chunk = content[i:i + limit]
        obj = {
            "type": "text",
            "text": {"content": chunk}
        }
        if link_url:
            obj["text"]["link"] = {"url": link_url}
        annotations = {}
        if bold:
            annotations["bold"] = True
        if code:
            annotations["code"] = True
        if annotations:
            obj["annotations"] = annotations
        parts.append(obj)

def append_equation_text(parts, expression, bold=False):
    expression = expression.strip()
    if not expression:
        return
    obj = {
        "type": "equation",
        "equation": {"expression": expression}
    }
    if bold:
        obj["annotations"] = {"bold": True}
    parts.append(obj)

def append_text_with_equations(parts, text, bold=False):
    equation_pattern = re.compile(r"(?<!\$)\$([^$\n]+?)\$(?!\$)")
    pos = 0

    for match in equation_pattern.finditer(text):
        append_rich_text(parts, text[pos:match.start()], bold=bold)
        append_equation_text(parts, match.group(1), bold=bold)
        pos = match.end()

    append_rich_text(parts, text[pos:], bold=bold)

def append_formatted_plain_text(parts, text):
    pattern = re.compile(r"(`[^`\n]*`|\*\*.*?\*\*)")
    pos = 0

    for match in pattern.finditer(text):
        append_text_with_equations(parts, text[pos:match.start()])

        seg = match.group(0)
        if seg.startswith("**") and seg.endswith("**"):
            append_text_with_equations(parts, seg[2:-2], bold=True)
        elif seg.startswith("`") and seg.endswith("`"):
            append_rich_text(parts, seg[1:-1], code=True)

        pos = match.end()

    append_text_with_equations(parts, text[pos:])

def parse_inline_formatting(text):
    """Parses links, bold, inline code, and splits >2000 char segments."""
    parts = []
    link_pattern = re.compile(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)")
    pos = 0

    for match in link_pattern.finditer(text):
        append_formatted_plain_text(parts, text[pos:match.start()])
        append_rich_text(parts, match.group(1), link_url=match.group(2))
        pos = match.end()

    append_formatted_plain_text(parts, text[pos:])

    if not parts:
        return [{"type": "text", "text": {"content": ""}}]
    return parts

def split_plain_text(text):
    """Splits plain text into list of rich text objects without inline format parsing, max 2000 chars."""
    parts = []
    limit = 1900
    if not text:
        return [{"type": "text", "text": {"content": ""}}]
    for i in range(0, len(text), limit):
        parts.append({
            "type": "text",
            "text": {"content": text[i:i + limit]}
        })
    return parts

def get_callout_icon(callout_type):
    emoji_map = {
        "info": "\u2139\ufe0f",
        "tip": "\U0001f4a1",
        "warning": "\u26a0\ufe0f",
        "caution": "\u26a0\ufe0f",
        "danger": "\U0001f6a8",
        "note": "\U0001f4dd",
        "question": "\u2753",
        "success": "\u2705",
        "failure": "\u274c"
    }
    return emoji_map.get(callout_type.lower(), "\U0001f4dd")

def get_callout_title(callout_type, title):
    title = title.strip()
    if title:
        return title
    if callout_type.lower() in {"note", "info", "tip", "warning", "caution", "danger", "question", "success", "failure"}:
        return callout_type.upper()
    return callout_type.strip()

def create_callout_block(callout_type, title, children=None):
    content = get_callout_title(callout_type, title)
    callout_payload = {
        "rich_text": parse_inline_formatting(content),
        "icon": {"emoji": get_callout_icon(callout_type)}
    }
    if children:
        callout_payload["children"] = children

    return {
        "object": "block",
        "type": "callout",
        "callout": callout_payload
    }

def append_callout_blocks(
    blocks,
    callout_type,
    title,
    lines,
    image_base_url,
    vault_dir,
    cloudinary_config,
    image_block_factory,
):
    body = "\n".join(lines).strip()
    child_blocks = []
    if body:
        child_blocks = markdown_to_notion_blocks(
            body,
            image_base_url=image_base_url,
            vault_dir=vault_dir,
            cloudinary_config=cloudinary_config,
            image_block_factory=image_block_factory,
        )
    blocks.append(create_callout_block(callout_type, title, children=child_blocks))

def create_table_block(rows):
    valid_rows = [r for r in rows if r]
    if not valid_rows or len(valid_rows[0]) == 0:
        return {
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": "[빈 테이블 오류: 행이나 열이 없습니다]"}}]
            }
        }

    table_width = len(valid_rows[0])
    table_row_blocks = []

    for row in valid_rows:
        cells_json = []
        for cell in row:
            cells_json.append(parse_inline_formatting(cell))
        while len(cells_json) < table_width:
            cells_json.append([])
        cells_json = cells_json[:table_width]

        table_row_blocks.append({
            "type": "table_row",
            "table_row": {
                "cells": cells_json
            }
        })

    return {
        "object": "block",
        "type": "table",
        "table": {
            "table_width": table_width,
            "has_column_header": True,
            "children": table_row_blocks
        }
    }

def create_equation_block(expression):
    return {
        "object": "block",
        "type": "equation",
        "equation": {
            "expression": expression.strip()
        }
    }

def create_divider_block():
    return {
        "object": "block",
        "type": "divider",
        "divider": {}
    }

def split_line_by_image_tokens(stripped_line):
    parts = []
    pos = 0

    for match in IMAGE_TOKEN_RE.finditer(stripped_line):
        text = stripped_line[pos:match.start()]
        if text:
            parts.append(("text", text))
        parts.append(("image", (match.group(1) or match.group(2)).strip()))
        pos = match.end()

    if pos == 0:
        return []

    tail = stripped_line[pos:]
    if tail:
        parts.append(("text", tail))
    return parts

def get_leading_indent_width(line):
    match = re.match(r"^[ \t]*", line)
    indent_text = match.group(0) if match else ""
    return sum(4 if ch == "\t" else 1 for ch in indent_text)

def create_list_item_block(block_type, text):
    return {
        "object": "block",
        "type": block_type,
        block_type: {
            "rich_text": parse_inline_formatting(text)
        }
    }

def append_list_item_block(blocks, list_stack, indent_width, block):
    while list_stack and indent_width <= list_stack[-1]["indent"]:
        list_stack.pop()

    if list_stack:
        parent = list_stack[-1]["block"]
        parent_type = parent["type"]
        parent[parent_type].setdefault("children", []).append(block)
    else:
        blocks.append(block)

    list_stack.append({
        "indent": indent_width,
        "block": block
    })

def markdown_to_notion_blocks(
    markdown_text,
    image_base_url=None,
    vault_dir=None,
    cloudinary_config=None,
    image_block_factory=None,
):
    lines = markdown_text.splitlines()
    blocks = []
    list_stack = []

    in_code_block = False
    code_lang = "plain text"
    code_lines = []

    in_table = False
    table_rows = []

    in_callout = False
    callout_lines = []
    callout_type = "info"
    callout_title = ""

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped_line = line.strip()

        # 0. Image Block Handling
        image_line_parts = split_line_by_image_tokens(stripped_line)
        if image_line_parts and not in_callout:
            list_stack = []
            for part_type, content in image_line_parts:
                if part_type == "image":
                    if image_block_factory is None:
                        raise ValueError("An image_block_factory is required for image rendering.")
                    blocks.append(image_block_factory(
                        content,
                        image_base_url,
                        vault_dir=vault_dir,
                        cloudinary_config=cloudinary_config
                    ))
                elif content.strip():
                    blocks.append({
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": parse_inline_formatting(content.strip())
                        }
                    })
            i += 1
            continue

        # 1. Code Block Handling
        if stripped_line.startswith("```"):
            list_stack = []
            if in_code_block:
                blocks.append({
                    "object": "block",
                    "type": "code",
                    "code": {
                        "rich_text": split_plain_text("\n".join(code_lines)),
                        "language": code_lang
                    }
                })
                in_code_block = False
                code_lines = []
            else:
                in_code_block = True
                lang = stripped_line[3:].strip()
                code_lang = lang if lang else "plain text"
                lang_mapping = {
                    "py": "python",
                    "js": "javascript",
                    "ts": "typescript",
                    "sh": "bash",
                    "cmd": "shell",
                    "bat": "shell",
                    "ps1": "powershell"
                }
                code_lang = lang_mapping.get(code_lang.lower(), code_lang)
            i += 1
            continue

        if in_code_block:
            code_lines.append(line)
            i += 1
            continue

        # 2. Equation Block Handling ($$...$$)
        single_line_equation = re.match(r"^\$\$\s*(.*?)\s*\$\$$", stripped_line)
        multi_line_equation_start = stripped_line == "$$"
        if single_line_equation or multi_line_equation_start:
            list_stack = []
            if in_table:
                blocks.append(create_table_block(table_rows))
                in_table = False
                table_rows = []
            if in_callout:
                append_callout_blocks(blocks, callout_type, callout_title, callout_lines, image_base_url, vault_dir, cloudinary_config, image_block_factory)
                in_callout = False
                callout_lines = []

            if single_line_equation:
                expression = single_line_equation.group(1)
                blocks.append(create_equation_block(expression))
                i += 1
                continue

            equation_lines = []
            i += 1
            while i < len(lines):
                next_line = lines[i]
                if next_line.strip() == "$$":
                    break
                equation_lines.append(next_line)
                i += 1

            blocks.append(create_equation_block("\n".join(equation_lines)))
            if i < len(lines) and lines[i].strip() == "$$":
                i += 1
            continue

        # 3. Horizontal Rule Handling
        if re.fullmatch(r"([-*_])(?:\s*\1){2,}", stripped_line):
            list_stack = []
            if in_table:
                blocks.append(create_table_block(table_rows))
                in_table = False
                table_rows = []
            if in_callout:
                append_callout_blocks(blocks, callout_type, callout_title, callout_lines, image_base_url, vault_dir, cloudinary_config, image_block_factory)
                in_callout = False
                callout_lines = []
            blocks.append(create_divider_block())
            i += 1
            continue

        # 4. Callout Handling (Obsidian style > [!info] ...)
        callout_start_match = re.match(r"^>\s*\[!([^\]]+)\]\s*(.*)$", stripped_line)
        if callout_start_match:
            list_stack = []
            if in_callout:
                append_callout_blocks(blocks, callout_type, callout_title, callout_lines, image_base_url, vault_dir, cloudinary_config, image_block_factory)
            in_callout = True
            callout_type = callout_start_match.group(1).strip()
            callout_title = re.sub(r"^[+-]\s*", "", callout_start_match.group(2).strip())
            callout_lines = []
            i += 1
            continue

        if in_callout:
            if stripped_line.startswith(">"):
                callout_content_line = re.sub(r"^>\s?", "", line)
                callout_lines.append(callout_content_line)
                i += 1
                continue
            else:
                append_callout_blocks(blocks, callout_type, callout_title, callout_lines, image_base_url, vault_dir, cloudinary_config, image_block_factory)
                in_callout = False
                callout_lines = []

        # 5. Table Handling
        is_table_row = stripped_line.startswith("|") and stripped_line.endswith("|")
        if is_table_row:
            list_stack = []
            if re.match(r"^\|[\s|:\-]*\|$", stripped_line):
                i += 1
                continue
            in_table = True
            cells = [cell.strip() for cell in stripped_line.split("|")[1:-1]]
            table_rows.append(cells)
            i += 1
            continue
        elif in_table:
            blocks.append(create_table_block(table_rows))
            in_table = False
            table_rows = []

        # 6. Heading Handling
        heading_match = re.match(r"^(#{1,6})\s+(.*)$", stripped_line)
        if heading_match:
            list_stack = []
            level = len(heading_match.group(1))
            heading_text = heading_match.group(2).strip()
            block_type = f"heading_{min(level, 3)}"
            blocks.append({
                "object": "block",
                "type": block_type,
                block_type: {
                    "rich_text": parse_inline_formatting(heading_text)
                }
            })
            i += 1
            continue

        # 7. List Items (Bulleted / Numbered)
        indent_width = get_leading_indent_width(line)
        list_content = line.lstrip(" \t")
        bullet_match = re.match(r"^([*\-+])\s+(.*)$", list_content)
        if bullet_match:
            bullet_text = bullet_match.group(2).strip()
            list_block = create_list_item_block("bulleted_list_item", bullet_text)
            append_list_item_block(blocks, list_stack, indent_width, list_block)
            i += 1
            continue

        number_match = re.match(r"^(\d+)\.\s+(.*)$", list_content)
        if number_match:
            num_text = number_match.group(2).strip()
            list_block = create_list_item_block("numbered_list_item", num_text)
            append_list_item_block(blocks, list_stack, indent_width, list_block)
            i += 1
            continue

        # 8. Standard Paragraph
        list_stack = []
        if stripped_line:
            if stripped_line.lower().startswith("category:") or stripped_line.startswith("분류:"):
                i += 1
                continue
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": parse_inline_formatting(line)
                }
            })
        else:
            # Empty line
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": []}
            })

        i += 1

    if in_code_block:
        blocks.append({
            "object": "block",
            "type": "code",
            "code": {
                "rich_text": split_plain_text("\n".join(code_lines)),
                "language": code_lang
            }
        })
    if in_callout:
        append_callout_blocks(blocks, callout_type, callout_title, callout_lines, image_base_url, vault_dir, cloudinary_config, image_block_factory)
    if in_table:
        blocks.append(create_table_block(table_rows))

    return blocks


def format_date_for_notion(log_name):
    """Converts YY.MM.DD or YYMMDD from log_name to YYYY-MM-DD."""
    # Match YY.MM.DD (e.g. 26.03.10)
    m1 = re.match(r"^(\d{2})\.(\d{2})\.(\d{2})", log_name)
    if m1:
        return f"20{m1.group(1)}-{m1.group(2)}-{m1.group(3)}"
    # Match YYMMDD (e.g. 260623)
    m2 = re.match(r"^(\d{2})(\d{2})(\d{2})", log_name)
    if m2:
        return f"20{m2.group(1)}-{m2.group(2)}-{m2.group(3)}"
    # Fallback to current date
    return datetime.now().strftime("%Y-%m-%d")

def get_markdown_stem(path):
    filename = os.path.basename(path.replace("\\", "/"))
    return filename[:-3] if filename.lower().endswith(".md") else filename

def strip_inline_code(value):
    value = value.strip()
    if len(value) >= 2 and value.startswith("`") and value.endswith("`"):
        return value[1:-1].strip()
    return value

def extract_generated_note_metadata(markdown_content):
    metadata = {}
    patterns = {
        "source_id": r"^\*\*Source ID\*\*:\s*(.+)$",
        "source_path": r"^\*\*Source Path\*\*:\s*(.+)$",
        "source_heading": r"^\*\*Source Heading\*\*:\s*(.+)$",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, markdown_content, flags=re.MULTILINE)
        if match:
            metadata[key] = strip_inline_code(match.group(1))
    return metadata


def strip_internal_comments(markdown_content):
    return SOURCE_ID_COMMENT_RE.sub("", markdown_content)


def has_notion_property(available_properties, property_name):
    return available_properties is None or property_name in available_properties


def get_page_properties(
    filepath,
    relative_path,
    sync_key,
    note_metadata=None,
    available_properties=None,
    category_path=None,
):
    """Constructs the Notion database properties dictionary for a log file with hierarchical categories."""
    note_metadata = note_metadata or {}
    raw_title = get_markdown_stem(filepath).strip()
    date_str = format_date_for_notion(raw_title)

    clean_title = raw_title
    date_prefix_match = re.match(r"^(\d{2}\.\d{2}\.\d{2}|\d{6})\s*-\s*(.*)$", raw_title)
    if date_prefix_match:
        clean_title = date_prefix_match.group(2).strip()
    elif re.match(r"^(\d{2}\.\d{2}\.\d{2}|\d{6})$", raw_title):
        clean_title = f"{date_str} \uc77c\uc9c0"

    normalized_path = relative_path.replace("\\", "/")
    path_parts = [p for p in normalized_path.split("/") if p]

    properties = {
        NOTION_PROP_TITLE: {
            "title": [{"text": {"content": clean_title}}]
        },
        NOTION_PROP_SYNC_KEY: {
            "rich_text": [{"text": {"content": sync_key}}]
        },
        NOTION_PROP_DATE: {
            "date": {"start": date_str}
        }
    }

    if note_metadata.get("source_id") and has_notion_property(available_properties, NOTION_PROP_SOURCE_ID):
        properties[NOTION_PROP_SOURCE_ID] = {
            "rich_text": [{"text": {"content": note_metadata["source_id"]}}]
        }
    if note_metadata.get("source_heading") and has_notion_property(available_properties, NOTION_PROP_SOURCE_HEADING):
        properties[NOTION_PROP_SOURCE_HEADING] = {
            "rich_text": [{"text": {"content": note_metadata["source_heading"]}}]
        }

    if path_parts and path_parts[0].lower() == "daily_logs":
        properties[NOTION_PROP_LEVEL_1] = {
            "select": {"name": DAILY_LOGS_CATEGORY_NAME}
        }
        return properties

    if category_path:
        categories = [p for p in category_path.replace("\\", "/").split("/") if p]
    else:
        categories = []
        subject_idx = -1
        for idx, part in enumerate(path_parts):
            if part.lower() == "subject":
                subject_idx = idx
                break

    if not category_path and subject_idx != -1 and len(path_parts) > subject_idx + 1:
        categories = path_parts[subject_idx + 1:-1]

    category_keys = [
        NOTION_PROP_LEVEL_1,
        NOTION_PROP_LEVEL_2,
        NOTION_PROP_LEVEL_3,
        NOTION_PROP_LEVEL_4,
        NOTION_PROP_LEVEL_5,
    ]
    for idx, key in enumerate(category_keys):
        if idx < len(categories) and categories[idx]:
            properties[key] = {
                "select": {"name": categories[idx]}
            }

    return properties

def normalize_wikilink_target(raw_target):
    target = raw_target.strip()
    if "|" in target:
        target, alias = target.split("|", 1)
        display_text = alias.strip()
    else:
        display_text = ""
    target = target.split("#", 1)[0].strip()
    target = target.replace("\\", "/")
    target_no_ext = target[:-3] if target.lower().endswith(".md") else target
    if not display_text:
        display_text = os.path.basename(target_no_ext)
    return target_no_ext, display_text


def wikilink_target_aliases(path):
    normalized = normalize_sync_key_part(path)
    target_no_ext = normalized[:-3] if normalized.lower().endswith(".md") else normalized
    return {
        target_no_ext.casefold(),
        os.path.basename(target_no_ext).strip().casefold(),
    }


def build_managed_wikilink_targets(paths):
    targets = set()
    for path in paths:
        targets.update(wikilink_target_aliases(path))
    return targets


def convert_wikilinks_to_notion_links(
    markdown_content,
    url_map,
    managed_targets=None,
    unresolved_targets=None,
    source_path=None,
):
    managed_targets = managed_targets or set()
    normalized_url_map = {
        normalize_sync_key_part(path).casefold(): notion_url
        for path, notion_url in url_map.items()
    }

    def replace_wikilink(match):
        target_name, display_text = normalize_wikilink_target(match.group(1))
        target_key = target_name.lower()

        for orig_rel, notion_url in url_map.items():
            normalized_orig = orig_rel.replace("\\", "/")
            orig_no_ext = normalized_orig[:-3] if normalized_orig.lower().endswith(".md") else normalized_orig
            orig_filename = os.path.basename(orig_no_ext).strip()
            if orig_no_ext.lower() == target_key or orig_filename.lower() == target_key:
                return f"[{display_text}]({notion_url})"

        if wikilink_target_aliases(target_name) & managed_targets:
            if unresolved_targets is not None:
                unresolved_targets.append(target_name)
        return display_text

    converted = re.sub(r"(?<!!)\[\[(.*?)\]\]", replace_wikilink, markdown_content)

    def replace_markdown_link(match):
        display_text = match.group(1)
        raw_target = match.group(2).strip()
        target = (
            raw_target[1:-1]
            if raw_target.startswith("<") and raw_target.endswith(">")
            else raw_target
        )
        parsed = urlsplit(target)
        if parsed.scheme or parsed.netloc or target.startswith("#"):
            return match.group(0)

        decoded_path = unquote(parsed.path).replace("\\", "/")
        if not decoded_path:
            return match.group(0)
        if source_path:
            source_dir = posixpath.dirname(normalize_sync_key_part(source_path))
            resolved_target = posixpath.normpath(
                posixpath.join(source_dir, decoded_path)
            )
        else:
            resolved_target = posixpath.normpath(decoded_path)
        resolved_target = normalize_sync_key_part(resolved_target)

        notion_url = normalized_url_map.get(resolved_target.casefold())
        if notion_url:
            return f"[{display_text}]({notion_url})"

        if wikilink_target_aliases(resolved_target) & managed_targets:
            if unresolved_targets is not None:
                unresolved_targets.append(resolved_target)
            return display_text
        return match.group(0)

    return re.sub(
        r"(?<!!)\[((?:\\.|[^\]\\])*)\]\(([^)\n]+)\)",
        replace_markdown_link,
        converted,
    )
