"""Bounded data-image decoding without network access or image rendering."""

import base64
import binascii
from dataclasses import dataclass
import hashlib
import io
import math
import re
import struct
import urllib.parse
import xml.etree.ElementTree as ET
import zlib


MAX_INLINE_IMAGE_BYTES = 5 * 1024 * 1024
MAX_DATA_URL_LENGTH = MAX_INLINE_IMAGE_BYTES * 3 + 256
MAX_IMAGE_DIMENSION = 8192
MAX_IMAGE_PIXELS = 16_000_000
MAX_SVG_BYTES = 1024 * 1024
MAX_SVG_ELEMENTS = 5000
MAX_SVG_DEPTH = 64
SVG_NAMESPACE = "http://www.w3.org/2000/svg"
MIME_EXTENSIONS = {
    "image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif",
    "image/webp": ".webp", "image/svg+xml": ".svg",
}
SVG_ELEMENTS = {
    "svg", "g", "defs", "path", "rect", "circle", "ellipse", "line",
    "polyline", "polygon", "text", "tspan", "title", "desc",
    "linearGradient", "radialGradient", "stop", "clipPath", "mask",
}
SVG_ATTRIBUTES = {
    "id", "version", "viewBox", "preserveAspectRatio", "width", "height",
    "x", "y", "x1", "x2", "y1", "y2", "cx", "cy", "r", "rx", "ry",
    "dx", "dy", "d", "points", "transform", "gradientTransform",
    "gradientUnits", "spreadMethod", "fx", "fy", "fr", "offset",
    "clipPathUnits", "maskUnits", "maskContentUnits", "role",
}
SVG_STYLE_PROPERTIES = {
    "fill", "fill-rule", "fill-opacity", "stroke", "stroke-width",
    "stroke-linecap", "stroke-linejoin", "stroke-miterlimit",
    "stroke-dasharray", "stroke-dashoffset", "stroke-opacity", "opacity",
    "color", "font-family", "font-size", "font-weight", "font-style",
    "text-anchor", "dominant-baseline", "alignment-baseline", "text-decoration",
    "display", "visibility", "clip-path", "clip-rule", "mask",
    "stop-color", "stop-opacity", "vector-effect", "paint-order",
}


class InlineImageError(ValueError):
    """Reasons are safe to show; never include the original data URL."""


def is_data_image_reference(reference):
    return str(reference or "").strip().casefold().startswith("data:")


def data_image_reference_key(reference):
    digest = hashlib.sha256(str(reference).strip().encode("utf-8")).hexdigest()
    return "data:sha256:" + digest


@dataclass(frozen=True)
class InlineImage:
    data: bytes
    mime_type: str

    @property
    def sha1(self):
        return hashlib.sha1(self.data).hexdigest()

    @property
    def filename(self):
        return "inline-" + hashlib.sha256(self.data).hexdigest() + MIME_EXTENSIONS[self.mime_type]


def _check_dimensions(width, height):
    if (width <= 0 or height <= 0 or width > MAX_IMAGE_DIMENSION
            or height > MAX_IMAGE_DIMENSION or width * height > MAX_IMAGE_PIXELS):
        raise InlineImageError("image dimensions exceed the supported limit")


def _validate_style_value(value):
    # Reject CSS escape tricks, at-rules, comments, and non-local URLs.
    if any(token in value.casefold() for token in ("\\", "@", "/*", "expression", "javascript:", "data:")):
        raise InlineImageError("SVG contains unsupported style content")
    urls = re.findall(r"url\s*\([^)]*\)", value, flags=re.I)
    for url in urls:
        if not re.fullmatch(r"url\(\s*['\"]?#[A-Za-z_][\w.-]*['\"]?\s*\)", url, flags=re.I):
            raise InlineImageError("SVG external references are not supported")
    remaining = re.sub(r"url\s*\([^)]*\)", "", value, flags=re.I)
    if re.search(r"url\s*\(|[<>]", remaining, flags=re.I):
        raise InlineImageError("SVG contains unsupported style content")


def validate_static_svg(data):
    """Accept a small, static SVG subset; reject active content instead of stripping it."""
    if len(data) > MAX_SVG_BYTES:
        raise InlineImageError("SVG exceeds the 1 MiB limit")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InlineImageError("SVG must use UTF-8") from exc
    if "\x00" in text or re.search(r"<!\s*(?:DOCTYPE|ENTITY)", text, flags=re.I):
        raise InlineImageError("SVG document types and entities are not supported")
    # Processing instructions can select external stylesheets. Only the initial
    # XML declaration is permitted, and no alternate character encoding is used.
    text_without_declaration = re.sub(r"^\s*<\?xml\s+[^?]*\?>", "", text, count=1)
    if "<?" in text_without_declaration:
        raise InlineImageError("SVG processing instructions are not supported")
    count = depth = 0
    root_dimensions = {}
    try:
        for event, element in ET.iterparse(io.StringIO(text), events=("start", "end")):
            if event == "end":
                depth -= 1
                element.clear()
                continue
            count += 1
            depth += 1
            if count > MAX_SVG_ELEMENTS or depth > MAX_SVG_DEPTH:
                raise InlineImageError("SVG complexity exceeds the supported limit")
            tag = element.tag
            if tag.startswith("{" + SVG_NAMESPACE + "}"):
                tag = tag.split("}", 1)[1]
            if tag not in SVG_ELEMENTS or (count == 1 and tag != "svg"):
                raise InlineImageError("SVG contains unsupported elements")
            for name, value in element.attrib.items():
                if name in {"{http://www.w3.org/XML/1998/namespace}space", "{http://www.w3.org/XML/1998/namespace}lang"}:
                    continue
                if name == "style":
                    for declaration in value.split(";"):
                        if not declaration.strip():
                            continue
                        prop, separator, content = declaration.partition(":")
                        if not separator or prop.strip().casefold() not in SVG_STYLE_PROPERTIES:
                            raise InlineImageError("SVG contains unsupported style properties")
                        _validate_style_value(content)
                elif name in SVG_STYLE_PROPERTIES:
                    _validate_style_value(value)
                elif name not in SVG_ATTRIBUTES and not name.startswith("aria-"):
                    raise InlineImageError("SVG contains unsupported attributes")
                if count == 1 and name in {"width", "height"}:
                    match = re.fullmatch(r"\s*([+\d.eE-]+)(px|%)?\s*", value)
                    if not match:
                        raise InlineImageError("SVG dimensions must use pixels or percentages")
                    dimension = float(match.group(1))
                    limit = 100 if match.group(2) == "%" else MAX_IMAGE_DIMENSION
                    if not math.isfinite(dimension) or not 0 < dimension <= limit:
                        raise InlineImageError("SVG dimensions exceed the supported limit")
                    if match.group(2) != "%":
                        root_dimensions[name] = dimension
    except (ET.ParseError, ValueError) as exc:
        if isinstance(exc, InlineImageError):
            raise
        raise InlineImageError("SVG is malformed") from exc
    if not count:
        raise InlineImageError("SVG is empty")
    if len(root_dimensions) == 2:
        _check_dimensions(root_dimensions["width"], root_dimensions["height"])


def _png_dimensions(data):
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise InlineImageError("image contents do not match the declared MIME type")
    offset = 8
    dimensions = None
    has_image_data = False
    while offset + 12 <= len(data):
        length = int.from_bytes(data[offset:offset + 4], "big")
        kind = data[offset + 4:offset + 8]
        end = offset + 12 + length
        if end > len(data):
            break
        payload = data[offset + 8:end - 4]
        crc = int.from_bytes(data[end - 4:end], "big")
        if zlib.crc32(kind + payload) & 0xffffffff != crc:
            break
        if dimensions is None:
            if kind != b"IHDR" or length != 13:
                break
            dimensions = struct.unpack(">II", payload[:8])
        elif kind == b"IHDR" or kind == b"acTL":
            break
        if kind == b"IDAT":
            has_image_data = has_image_data or bool(length)
        if kind == b"IEND":
            if length == 0 and end == len(data) and has_image_data:
                return dimensions
            break
        offset = end
    raise InlineImageError("PNG is malformed or uses unsupported animation")


def _jpeg_dimensions(data):
    if not data.startswith(b"\xff\xd8") or not data.endswith(b"\xff\xd9"):
        raise InlineImageError("JPEG is malformed")
    offset = 2
    while offset + 4 <= len(data):
        if data[offset] != 0xff:
            break
        while offset < len(data) and data[offset] == 0xff:
            offset += 1
        if offset >= len(data):
            break
        marker = data[offset]
        offset += 1
        length = int.from_bytes(data[offset:offset + 2], "big")
        if length < 2 or offset + length > len(data):
            break
        if marker in {0xc0, 0xc1, 0xc2} and length >= 8:
            height, width = struct.unpack(">HH", data[offset + 3:offset + 7])
            return width, height
        if marker in {0xda, 0xd9}:
            break
        offset += length
    raise InlineImageError("JPEG dimensions could not be validated")


def _raster_dimensions(data, mime):
    if mime == "image/png":
        return _png_dimensions(data)
    if mime == "image/jpeg":
        return _jpeg_dimensions(data)
    if mime == "image/gif":
        if len(data) >= 14 and data[:6] in {b"GIF87a", b"GIF89a"} and data[-1:] == b";":
            return struct.unpack("<HH", data[6:10])
    if mime == "image/webp":
        if (len(data) >= 30 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
                and int.from_bytes(data[4:8], "little") + 8 == len(data)):
            kind, length = data[12:16], int.from_bytes(data[16:20], "little")
            payload = data[20:20 + length]
            if length <= len(data) - 20:
                if kind == b"VP8X" and length == 10 and not payload[0] & 2:
                    return 1 + int.from_bytes(payload[4:7], "little"), 1 + int.from_bytes(payload[7:10], "little")
                if kind == b"VP8 " and length >= 10 and payload[3:6] == b"\x9d\x01\x2a":
                    width, height = struct.unpack("<HH", payload[6:10])
                    return width & 0x3fff, height & 0x3fff
                if kind == b"VP8L" and length >= 5 and payload[0] == 0x2f:
                    bits = int.from_bytes(payload[1:5], "little")
                    return (bits & 0x3fff) + 1, ((bits >> 14) & 0x3fff) + 1
    raise InlineImageError("image contents do not match a supported image format")


def decode_data_image(reference):
    value = str(reference or "").strip()
    if len(value) > MAX_DATA_URL_LENGTH:
        raise InlineImageError("data URL exceeds the supported length")
    header, separator, payload = value.partition(",")
    if not is_data_image_reference(value) or not separator:
        raise InlineImageError("data URL is malformed")
    if len(header) > 256:
        raise InlineImageError("data URL header exceeds the supported length")
    parts = header[5:].casefold().split(";")
    mime = parts[0]
    if mime not in MIME_EXTENSIONS:
        raise InlineImageError("data image MIME type is not supported")
    params = parts[1:]
    if len(params) != len(set(params)) or any(p not in {"base64", "utf8", "charset=utf-8"} for p in params):
        raise InlineImageError("data URL parameters are not supported")
    if mime != "image/svg+xml" and any(p != "base64" for p in params):
        raise InlineImageError("raster image parameters are not supported")
    if re.search(r"%(?![0-9a-fA-F]{2})", payload):
        raise InlineImageError("data URL percent encoding is malformed")
    try:
        encoded = urllib.parse.unquote_to_bytes(payload)
        data = base64.b64decode(encoded, validate=True) if "base64" in params else encoded
    except (ValueError, binascii.Error) as exc:
        raise InlineImageError("data image encoding is malformed") from exc
    if not data or len(data) > MAX_INLINE_IMAGE_BYTES:
        raise InlineImageError("decoded image is empty or exceeds the 5 MiB limit")
    if mime == "image/svg+xml":
        validate_static_svg(data)
    else:
        _check_dimensions(*_raster_dimensions(data, mime))
    return InlineImage(data=data, mime_type=mime)
