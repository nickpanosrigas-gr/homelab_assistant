from langchain_core.tools import tool
from src.clients.truenas import TrueNASClient
from src.agent import prompts

truenas = TrueNASClient()

@tool(description=prompts.DESC_CHECK_POOL)
def check_truenas_pool() -> str:
    return truenas.get_pool_health()

@tool(description=prompts.DESC_CHECK_DISK_HEALTH)
def check_truenas_disk_health() -> str:
    return truenas.get_disk_health()

@tool(description=prompts.DESC_CHECK_DISK_TEMPS)
def check_truenas_disk_temps() -> str:
    return truenas.get_disk_temps()

@tool(description=prompts.DESC_CHECK_ALERTS)
def check_truenas_alerts() -> str:
    return truenas.get_alerts()

STORAGE_TOOLS = [check_truenas_pool, check_truenas_disk_health, check_truenas_disk_temps, check_truenas_alerts]
STORAGE_SYSTEM_PROMPT = prompts.STORAGE_SYSTEM_PROMPT