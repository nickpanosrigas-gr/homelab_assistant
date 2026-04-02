from langchain_core.tools import tool
from src.clients.truenas import TrueNASClient
from src.agent import prompts

truenas = TrueNASClient()

@tool
def check_truenas_pool() -> str:
    return truenas.get_pool_health()
check_truenas_pool.__doc__ = prompts.DESC_CHECK_POOL

@tool
def check_truenas_disk_health() -> str:
    return truenas.get_disk_health()
check_truenas_disk_health.__doc__ = prompts.DESC_CHECK_DISK_HEALTH

@tool
def check_truenas_disk_temps() -> str:
    return truenas.get_disk_temps()
check_truenas_disk_temps.__doc__ = prompts.DESC_CHECK_DISK_TEMPS

@tool
def check_truenas_alerts() -> str:
    return truenas.get_alerts()
check_truenas_alerts.__doc__ = prompts.DESC_CHECK_ALERTS

STORAGE_TOOLS = [check_truenas_pool, check_truenas_disk_health, check_truenas_disk_temps, check_truenas_alerts]
STORAGE_SYSTEM_PROMPT = prompts.STORAGE_SYSTEM_PROMPT