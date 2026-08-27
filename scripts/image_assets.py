import ntpath
import os
import urllib.parse
import xml.etree.ElementTree as ElementTree


IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".bmp",
    ".tif",
    ".tiff",
    ".svg",
}

BLOCKED_IMAGE_DIRECTORIES = {
    ".git",
    ".obsidian",
    ".agents",
    ".codex",
    ".gemini",
    "scripts",
    "subject",
    "topic_reviews",
    "_generated",
}

_EXTENSION_FORMATS = {
    ".png": "png",
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".gif": "gif",
    ".webp": "webp",
    ".bmp": "bmp",
    ".tif": "tiff",
    ".tiff": "tiff",
    ".svg": "svg",
}

_FORMAT_MIME_TYPES = {
    "png": "image/png",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "bmp": "image/bmp",
    "tiff": "image/tiff",
    "svg": "image/svg+xml",
}


class ImageReferenceError(ValueError):
    def __init__(self, reference, reason):
        self.reference = str(reference or "")
        self.reason = reason
        super().__init__(f"Unsafe local image reference '{self.reference}': {reason}")


def normalize_image_reference(reference):
    value = str(reference or "").replace("\\", "/").strip()
    if "\x00" in value:
        raise ImageReferenceError(reference, "the path contains a null byte")
    value = urllib.parse.unquote(value)
    value = value.split("#", 1)[0].split("|", 1)[0].strip()
    return value


def _relative_parts(normalized):
    return [part for part in normalized.split("/") if part not in {"", "."}]


def _validate_reference_syntax(reference, normalized):
    if not normalized:
        raise ImageReferenceError(reference, "the path is empty")
    if ntpath.isabs(normalized) or os.path.isabs(normalized):
        raise ImageReferenceError(reference, "absolute paths are not allowed")
    if urllib.parse.urlsplit(normalized).scheme:
        raise ImageReferenceError(reference, "local image references cannot use a URL scheme")

    parts = _relative_parts(normalized)
    extension = os.path.splitext(parts[-1] if parts else "")[1].casefold()
    if extension not in IMAGE_EXTENSIONS:
        raise ImageReferenceError(reference, "the file extension is not an allowed image type")
    return parts


def _is_within(path, root):
    try:
        return os.path.commonpath([os.path.normcase(path), os.path.normcase(root)]) == os.path.normcase(root)
    except ValueError:
        return False


def detect_image_format(filepath):
    try:
        with open(filepath, "rb") as file_obj:
            header = file_obj.read(16)
    except OSError as exc:
        raise ImageReferenceError(filepath, f"the file could not be read ({exc})") from exc

    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if header.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "webp"
    if header.startswith(b"BM"):
        return "bmp"
    if header.startswith((b"II*\x00", b"MM\x00*")):
        return "tiff"
    if os.path.splitext(filepath)[1].casefold() == ".svg":
        try:
            with open(filepath, "rb") as file_obj:
                for _event, element in ElementTree.iterparse(file_obj, events=("start",)):
                    root_name = element.tag.rsplit("}", 1)[-1].casefold()
                    return "svg" if root_name == "svg" else None
        except (ElementTree.ParseError, OSError, UnicodeError):
            return None
    return None


def validate_local_image_file(filepath, vault_dir=None, reference=None):
    display_reference = reference if reference is not None else filepath
    absolute_path = os.path.realpath(os.path.abspath(filepath))

    if vault_dir:
        vault_root = os.path.realpath(os.path.abspath(vault_dir))
        if not _is_within(absolute_path, vault_root):
            raise ImageReferenceError(display_reference, "the resolved file is outside the Vault")

        relative_path = os.path.relpath(absolute_path, vault_root)
        relative_parts = [part.casefold() for part in relative_path.replace("\\", "/").split("/")]
        blocked = next(
            (part for part in relative_parts[:-1] if part in BLOCKED_IMAGE_DIRECTORIES),
            None,
        )
        if blocked:
            raise ImageReferenceError(
                display_reference,
                f"files under the protected '{blocked}' directory cannot be uploaded",
            )

    if not os.path.isfile(absolute_path):
        raise ImageReferenceError(display_reference, "the resolved path is not a regular file")

    extension = os.path.splitext(absolute_path)[1].casefold()
    expected_format = _EXTENSION_FORMATS.get(extension)
    if not expected_format:
        raise ImageReferenceError(display_reference, "the file extension is not an allowed image type")

    detected_format = detect_image_format(absolute_path)
    if detected_format != expected_format:
        raise ImageReferenceError(
            display_reference,
            "the file contents do not match the declared image type",
        )
    return absolute_path


def image_mime_type(filepath):
    validated_path = validate_local_image_file(filepath)
    detected_format = detect_image_format(validated_path)
    return _FORMAT_MIME_TYPES[detected_format]


def resolve_local_image_path(image_ref, vault_dir):
    if not vault_dir:
        return None

    normalized = normalize_image_reference(image_ref)
    parts = _validate_reference_syntax(image_ref, normalized)
    basename = parts[-1]
    vault_root = os.path.realpath(os.path.abspath(vault_dir))

    candidates = [
        os.path.join(vault_root, *parts),
        os.path.join(vault_root, "attachments", *parts),
        os.path.join(vault_root, "attachments", basename),
    ]

    seen = set()
    for candidate in candidates:
        candidate_key = os.path.normcase(os.path.abspath(candidate))
        if candidate_key in seen:
            continue
        seen.add(candidate_key)
        if os.path.lexists(candidate):
            return validate_local_image_file(candidate, vault_root, image_ref)

    target_lower = basename.casefold()
    for root, dirs, files in os.walk(vault_root):
        dirs[:] = sorted(
            directory
            for directory in dirs
            if directory.casefold() not in BLOCKED_IMAGE_DIRECTORIES
        )
        for filename in sorted(files):
            if filename.casefold() != target_lower:
                continue
            candidate = os.path.join(root, filename)
            return validate_local_image_file(candidate, vault_root, image_ref)
    return None
