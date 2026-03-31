import os
import re
import sys

BASE_DIR = r"d:\Coding\app-bot\bot_antigravity"

MAPPING = {
    "main.py": "app/main.py",
    "config.py": "app/config.py",
    "mt5_client.py": "app/core/mt5_client.py",
    "bot_state.py": "app/core/bot_state.py",
    "strategy.py": "app/trading/strategy.py",
    "risk.py": "app/trading/risk.py",
    "openclaw_v4.py": "app/trading/openclaw_v4.py",
    "analytics.py": "app/data/analytics.py",
    "sheets_logger.py": "app/data/sheets_logger.py",
    "news_filter.py": "app/data/news_filter.py",
    "openclaw_ai.py": "app/ai/openclaw_ai.py",
    "notifier.py": "app/utils/notifier.py",
    "utils.py": "app/utils/utils.py",
}

IMPORT_REPLACES = {
    r"\bimport config\b": "import app.config",
    r"\bimport config as cfg\b": "import app.config as cfg",
    r"\bfrom config import\b": "from app.config import",
    r"\bfrom mt5_client import\b": "from app.core.mt5_client import",
    r"\bimport mt5_client\b": "from app.core import mt5_client",
    r"\bimport bot_state\b": "from app.core import bot_state",
    r"\bfrom bot_state import\b": "from app.core.bot_state import",
    r"\bfrom strategy import\b": "from app.trading.strategy import",
    r"\bfrom risk import\b": "from app.trading.risk import",
    r"\bfrom openclaw_v4 import\b": "from app.trading.openclaw_v4 import",
    r"\bfrom analytics import\b": "from app.data.analytics import",
    r"\bfrom sheets_logger import\b": "from app.data.sheets_logger import",
    r"\bfrom news_filter import\b": "from app.data.news_filter import",
    r"\bfrom openclaw_ai import\b": "from app.ai.openclaw_ai import",
    r"\bfrom notifier import\b": "from app.utils.notifier import",
    r"\bfrom utils import\b": "from app.utils.utils import",
    r"\bimport utils\b": "from app.utils import utils",
}

def apply_refactor():
    os.chdir(BASE_DIR)
    
    # Create directories
    for folder in ["app/core", "app/trading", "app/data", "app/ai", "app/utils"]:
        os.makedirs(folder, exist_ok=True)
        open(os.path.join(folder, "__init__.py"), "w").close()
    
    open("app/__init__.py", "w").close()

    for old_file, new_file in MAPPING.items():
        if not os.path.exists(old_file):
            print(f"File {old_file} not found locally, skipping...")
            continue
            
        with open(old_file, "r", encoding="utf-8") as f:
            content = f.read()

        for old_import, new_import in IMPORT_REPLACES.items():
            content = re.sub(old_import, new_import, content)
            
        with open(new_file, "w", encoding="utf-8") as f:
            f.write(content)
            
        os.remove(old_file)
        print(f"Moved and updated {old_file} -> {new_file}")

    print("Refactor complete.")

if __name__ == "__main__":
    apply_refactor()
