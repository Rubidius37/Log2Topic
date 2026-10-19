NOTION_PROP_TITLE = "\uc774\ub984"
NOTION_PROP_SYNC_KEY = "Sync Key"
NOTION_PROP_DATE = "\ub0a0\uc9dc"
NOTION_PROP_LEVEL_1 = "\ub300\ubd84\ub958"
NOTION_PROP_LEVEL_2 = "\uc911\ubd84\ub958"
NOTION_PROP_LEVEL_3 = "\uc18c\ubd84\ub958"
NOTION_PROP_LEVEL_4 = "\uc0c1\uc138 \ubd84\ub958"
NOTION_PROP_LEVEL_5 = "\uc138\ubd80 \ud0dc\uc2a4\ud06c"
NOTION_PROP_SOURCE_ID = "Source ID"
NOTION_PROP_SOURCE_HEADING = "Source Heading"
DAILY_LOGS_CATEGORY_NAME = "Daily Logs (\uc6d0\ubcf8)"


def normalize_sync_key_part(value):
    return str(value or "").replace("\\", "/").strip().strip("/")
