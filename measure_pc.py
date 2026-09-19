import time
import matplotlib
matplotlib.use("Agg")
from energymeter import EnergyMeter

# Hardware: Intel i5-9300H (RAPL package-0), GTX 1660 Ti Mobile laptop,
# SK hynix HFS256GD9TNG-L3A0B 256GB NVMe SSD (PCIe 3.0 x4)
em = EnergyMeter(
    disk_avg_speed=1600 * 1e6,  # MB/s: effective NVMe read throughput (mid-load)
    disk_active_power=4.5,      # W: NVMe active read/write power (specs: ~4-5 W)
    disk_idle_power=0.05,       # W: NVMe idle/standby power (laptop NVMe, ~50 mW)
    label="PC Consumption",
    include_idle=False,
)

em.begin()
# Workload of reference: 5 s of full CPU load + 5 s of GPU load
start = time.perf_counter()
while time.perf_counter() - start < 5:
    sum(i * i for i in range(20000))

start = time.perf_counter()
import pynvml
pynvml.nvmlInit()
hnd = pynvml.nvmlDeviceGetHandleByIndex(0)
try:
    while time.perf_counter() - start < 5:
        pynvml.nvmlDeviceGetPowerUsage(hnd)
        # spin CPU side too so the GPU-initiated work is attributed
        sum(i * i for i in range(2000))
except KeyboardInterrupt:
    pass  # Ctrl+C: keep partial measurement instead of dropping it

em.end()

print("\n--- Energy per component (Joules) ---")
print(em.get_total_joules_per_component())
import numpy as np
data = {k: float(np.sum(v)) for k, v in em.get_total_joules_per_component().items()}
data["total"] = data["cpu"] + data["dram"] + data["gpu"] + data["disk"]
print(f"Total CPU+DRAM+GPU+disk: {data['total']:.1f} J  (~{data['total']/3600:.2f} Wh)")
print(f"~{data['total']/3600/1000*0.28:.4f} kWh at 0.28 EUR/kWh over the workload")
em.cleanup()
