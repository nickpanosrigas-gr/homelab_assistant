from langchain_core.tools import tool
from src.clients.truenas import TrueNASClient

# Initialize the client
truenas = TrueNASClient()

@tool
def check_truenas_pool() -> str:
    """
    Use this tool to fetch the overall health, status, and topology of the TrueNAS ZFS storage pool. 
    Use this to check capacity, free space, and overall storage health.
    """
    return truenas.get_pool_health()

@tool
def check_truenas_disk_health() -> str:
    """
    Use this tool to fetch detailed S.M.A.R.T. status, physical disk info, rotation rate, 
    and power management settings for the TrueNAS storage drives.
    """
    return truenas.get_disk_health()

@tool
def check_truenas_disk_temps() -> str:
    """
    Use this tool to fetch the current live temperatures (in Celsius) of all TrueNAS 
    hard drives and SSDs. Use this if the user asks if the drives are running hot.
    """
    return truenas.get_disk_temps()

@tool
def check_truenas_alerts() -> str:
    """
    Use this tool to fetch active system warnings and alerts from TrueNAS. 
    Use this to check for failed drives, system issues, or software updates.
    """
    return truenas.get_alerts()

# Bundle the tools
STORAGE_TOOLS = [
    check_truenas_pool, 
    check_truenas_disk_health, 
    check_truenas_disk_temps, 
    check_truenas_alerts
]

# Define the persona
STORAGE_SYSTEM_PROMPT = """You are the Storage Administrator for a homelab.
Your job is to monitor and report on TrueNAS ZFS pools, disk health, temperatures, and alerts.
Always use your tools to fetch real-time data before answering.
If a user asks about storage performance or issues, check alerts and pool health first.
Present storage sizes in Terabytes (TB) or Gigabytes (GB), and temperatures in Celsius."""