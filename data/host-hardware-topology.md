---
domain: "proxmox_host"
resource_id: "host"
content_type: "documentation"
service_names: 
  - "proxmox"
ip_address: "192.168.1.100"
hardware_dependencies: 
  - "gpu_rtx2070"
  - "igpu_uhd730"
  - "zfs_pool"
---

## 1. Hardware Specifications
* **Motherboard:** Z690 AORUS ELITE DDR4
* **CPU:** Intel Core i5-12400 (6 P-cores, 12 Threads)
* **RAM:** 40GB DDR4 (1x 32GB + 1x 8GB)
* **GPU (Dedicated):** Nvidia RTX 2070 Super (Passed dynamically between Windows & Ollama)
* **GPU (Integrated):** Intel UHD Graphics 730 (Passed to Jellyfin for transcoding)
* **Storage (Boot/VMs):** 2TB NVMe Gen 4 SSD
* **Storage (TrueNAS Pool):** 6 SATA slots utilizing:
    * 1x 500GB SSD (Cache)
    * 2x 16TB HDDs (Mirror VDEV)
    * 2x 14TB HDDs (Mirror VDEV)

### 2. Network & Services Topology
The Proxmox host operates on **192.168.1.100**.