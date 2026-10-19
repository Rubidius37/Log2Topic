import copy
import json
import time
import urllib.error
import urllib.request


NOTION_RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}
NOTION_MAX_ATTEMPTS = 4
NOTION_RETRY_SAFE = "safe"
NOTION_RETRY_NON_IDEMPOTENT = "non_idempotent"
NOTION_MAX_BLOCK_CHILDREN = 100
NOTION_MAX_INLINE_CHILD_DEPTH = 2


class NotionAmbiguousWriteError(RuntimeError):
    """Raised when a non-idempotent Notion write may already have succeeded."""


def notion_api_request(
    url,
    token,
    method="GET",
    data=None,
    max_attempts=NOTION_MAX_ATTEMPTS,
    retry_mode=None,
    operation_name=None,
):
    """Sends a request to the Notion API using Python's standard urllib library."""
    method = method.upper()
    if retry_mode is None:
        retry_mode = (
            NOTION_RETRY_SAFE
            if method == "GET"
            else NOTION_RETRY_NON_IDEMPOTENT
        )
    if retry_mode not in {NOTION_RETRY_SAFE, NOTION_RETRY_NON_IDEMPOTENT}:
        raise ValueError(f"Unsupported Notion retry mode: {retry_mode}")
    operation_label = operation_name or f"{method} {url}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }
    for attempt in range(1, max_attempts + 1):
        req = urllib.request.Request(
            url,
            headers=headers,
            method=method,
            data=json.dumps(data).encode("utf-8") if data else None,
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as res:
                return json.loads(res.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            retryable = exc.code in NOTION_RETRYABLE_HTTP_STATUS
            safe_to_repeat = retry_mode == NOTION_RETRY_SAFE or exc.code == 429
            if retryable and safe_to_repeat and attempt < max_attempts:
                retry_after = exc.headers.get("Retry-After", "") if exc.headers else ""
                try:
                    delay = max(float(retry_after), 0.0) if retry_after else 2 ** (attempt - 1)
                except ValueError:
                    delay = 2 ** (attempt - 1)
                print(
                    f"Notion API HTTP {exc.code}; retrying in {delay:g}s "
                    f"({attempt}/{max_attempts})..."
                )
                time.sleep(delay)
                continue
            if retryable and not safe_to_repeat:
                raise NotionAmbiguousWriteError(
                    f"Notion may have applied non-idempotent operation '{operation_label}' "
                    f"before returning HTTP {exc.code}; the request was not retried. "
                    f"Response: {error_body}"
                ) from exc
            print(f"Notion API HTTP Error: {exc.code} - {error_body}")
            raise RuntimeError(
                f"Notion API Call Failed (HTTP {exc.code}): {error_body}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            if retry_mode == NOTION_RETRY_NON_IDEMPOTENT:
                raise NotionAmbiguousWriteError(
                    f"Notion may have applied non-idempotent operation '{operation_label}' "
                    f"before the response was lost; the request was not retried: {exc}"
                ) from exc
            if attempt < max_attempts:
                delay = 2 ** (attempt - 1)
                print(
                    f"Notion API connection error; retrying in {delay}s "
                    f"({attempt}/{max_attempts}): {exc}"
                )
                time.sleep(delay)
                continue
            raise RuntimeError(
                f"Notion API connection failed after {max_attempts} attempts: {exc}"
            ) from exc

def query_pages_by_property(token, database_id, property_name, value):
    """Returns every matching Notion page for an exact rich_text property."""
    if not value:
        return []
    url = f"https://api.notion.com/v1/databases/{database_id}/query"
    results = []
    next_cursor = None
    while True:
        payload = {
            "page_size": 100,
            "filter": {
                "property": property_name,
                "rich_text": {
                    "equals": value
                }
            }
        }
        if next_cursor:
            payload["start_cursor"] = next_cursor
        try:
            res = notion_api_request(
                url,
                token,
                method="POST",
                data=payload,
                retry_mode=NOTION_RETRY_SAFE,
                operation_name=f"query pages by {property_name}",
            )
        except RuntimeError as e:
            if "property" in str(e).lower():
                print(
                    f"Warning: Could not query Notion property '{property_name}'. "
                    "Falling back when possible."
                )
                return []
            raise
        results.extend(res.get("results", []))
        if not res.get("has_more"):
            break
        next_cursor = res.get("next_cursor")
        if not next_cursor:
            raise RuntimeError(
                f"Notion query pagination for property '{property_name}' has no next cursor."
            )
    return results


def query_page_by_property(token, database_id, property_name, value):
    pages = query_pages_by_property(token, database_id, property_name, value)
    return select_canonical_notion_page(pages).page


def get_top_level_block_ids(token, page_id):
    """Lists every current top-level block so a page can be replaced in place."""
    block_ids = []
    next_cursor = None
    while True:
        query = {"page_size": 100}
        if next_cursor:
            query["start_cursor"] = next_cursor
        url = (
            f"https://api.notion.com/v1/blocks/{page_id}/children?"
            f"{urllib.parse.urlencode(query)}"
        )
        res = notion_api_request(url, token, method="GET")
        block_ids.extend(
            block["id"]
            for block in res.get("results", [])
            if block.get("id")
        )
        if not res.get("has_more"):
            break
        next_cursor = res.get("next_cursor")
        if not next_cursor:
            raise RuntimeError(
                f"Notion block pagination for page {page_id} has no next cursor."
            )
    return block_ids


def get_notion_block_children(block):
    if not isinstance(block, dict):
        return []
    block_type = block.get("type")
    payload = block.get(block_type, {}) if block_type else {}
    children = payload.get("children", []) if isinstance(payload, dict) else []
    return children if isinstance(children, list) else []


def notion_block_fits_single_request(block, depth=0):
    """Returns whether a block subtree fits Notion's inline append limits."""
    children = get_notion_block_children(block)
    if len(children) > NOTION_MAX_BLOCK_CHILDREN:
        return False
    if children and depth >= NOTION_MAX_INLINE_CHILD_DEPTH:
        return False
    return all(
        notion_block_fits_single_request(child, depth + 1)
        for child in children
    )


def prepare_notion_block_for_append(block):
    """Returns an API-safe block and children that must be appended later."""
    prepared = copy.deepcopy(block)
    children = get_notion_block_children(block)
    if not children or notion_block_fits_single_request(block):
        return prepared, []

    block_type = prepared.get("type")
    payload = prepared.get(block_type, {}) if block_type else {}
    if not isinstance(payload, dict):
        return prepared, []

    # A Notion table must be created with at least one row. Keep that row inline
    # and append any remaining rows after the table ID is known.
    if block_type == "table":
        first_row = copy.deepcopy(children[0])
        if not notion_block_fits_single_request(first_row, depth=1):
            raise RuntimeError("A Notion table row exceeds inline child limits.")
        payload["children"] = [first_row]
        return prepared, children[1:]

    payload.pop("children", None)
    return prepared, children


def append_notion_block_tree(
    token,
    parent_id,
    blocks,
    appended_top_level_ids=None,
    track_top_level=False,
    context="root",
):
    """Appends a block tree without exceeding per-request child limits."""
    if appended_top_level_ids is None:
        appended_top_level_ids = []

    url = f"https://api.notion.com/v1/blocks/{parent_id}/children"
    for start in range(0, len(blocks), NOTION_MAX_BLOCK_CHILDREN):
        source_chunk = blocks[start:start + NOTION_MAX_BLOCK_CHILDREN]
        prepared_chunk = []
        deferred_children = []
        for block in source_chunk:
            prepared, children = prepare_notion_block_for_append(block)
            prepared_chunk.append(prepared)
            deferred_children.append(children)

        chunk_number = start // NOTION_MAX_BLOCK_CHILDREN + 1
        res = notion_api_request(
            url,
            token,
            method="PATCH",
            data={"children": prepared_chunk},
            retry_mode=NOTION_RETRY_NON_IDEMPOTENT,
            operation_name=(
                f"append {context} block chunk {chunk_number} to {parent_id}"
            ),
        )
        results = res.get("results", [])
        result_ids = [
            result.get("id") if isinstance(result, dict) else None
            for result in results
        ]
        known_ids = [block_id for block_id in result_ids if block_id]
        if track_top_level:
            appended_top_level_ids.extend(known_ids)
        if len(results) != len(source_chunk) or len(known_ids) != len(source_chunk):
            raise RuntimeError(
                f"Notion did not return every appended block ID for {context} "
                f"({len(known_ids)}/{len(source_chunk)})."
            )

        for index, (block_id, children, source_block) in enumerate(
            zip(result_ids, deferred_children, source_chunk),
            start=start,
        ):
            if not children:
                continue
            block_type = source_block.get("type", "block")
            append_notion_block_tree(
                token,
                block_id,
                children,
                appended_top_level_ids=appended_top_level_ids,
                track_top_level=False,
                context=f"{context}/{block_type}[{index}]",
            )

    return appended_top_level_ids


def append_block_chunks(token, page_id, block_chunks, appended_ids=None):
    """Appends block chunks and returns their new top-level block IDs."""
    if appended_ids is None:
        appended_ids = []
    for chunk in block_chunks:
        append_notion_block_tree(
            token,
            page_id,
            chunk,
            appended_top_level_ids=appended_ids,
            track_top_level=True,
        )
    return appended_ids


def delete_notion_blocks(token, block_ids):
    """Best-effort deletes blocks and returns descriptions of any failures."""
    failures = []
    for block_id in block_ids:
        url = f"https://api.notion.com/v1/blocks/{block_id}"
        try:
            notion_api_request(
                url,
                token,
                method="DELETE",
                retry_mode=NOTION_RETRY_SAFE,
                operation_name=f"delete block {block_id}",
            )
        except Exception as exc:
            failures.append(f"{block_id}: {exc}")
    return failures


def replace_page_content_in_place(token, page_id, properties, block_chunks):
    """Replaces page content while preserving the page ID and external links."""
    old_block_ids = get_top_level_block_ids(token, page_id)
    appended_ids = []
    try:
        append_block_chunks(token, page_id, block_chunks, appended_ids)
        notion_api_request(
            f"https://api.notion.com/v1/pages/{page_id}",
            token,
            method="PATCH",
            data={"properties": properties},
            retry_mode=NOTION_RETRY_SAFE,
            operation_name=f"update properties for page {page_id}",
        )
    except Exception as exc:
        rollback_failures = delete_notion_blocks(token, appended_ids)
        rollback_note = (
            f" Rollback failures: {'; '.join(rollback_failures)}"
            if rollback_failures
            else ""
        )
        raise RuntimeError(
            f"Failed to prepare in-place update for page {page_id}: {exc}."
            f"{rollback_note}"
        ) from exc

    cleanup_failures = delete_notion_blocks(token, old_block_ids)
    if cleanup_failures:
        raise RuntimeError(
            "New content was uploaded, but old block cleanup was incomplete; "
            "the sync hash was not advanced. Retry the sync to self-heal. "
            f"Failures: {'; '.join(cleanup_failures)}"
        )


def build_notion_page_url(page_id):
    return f"https://www.notion.so/{page_id.replace('-', '')}"

def get_database_property_names(token, database_id):
    """Fetches the Notion database schema so optional properties can be used safely."""
    url = f"https://api.notion.com/v1/databases/{database_id}"
    res = notion_api_request(url, token, method="GET")
    return set(res.get("properties", {}).keys())

def archive_notion_page(token, page_id, label):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    try:
        notion_api_request(
            url,
            token,
            method="PATCH",
            data={"archived": True},
            retry_mode=NOTION_RETRY_SAFE,
            operation_name=f"archive page {page_id}",
        )
        print(f"-> Archived: {label}")
        return True
    except Exception as e:
        print(f"Warning: Failed to archive page {page_id}: {e}")
        return False
