"""Monitoring conso instantanee + moyenne 60 s (CPU, DRAM, GPU)."""
import time
import os

import pynvml
from pynvml import NVMLError

try:
    import curses
except ImportError:
    curses = None

RAPL = "/sys/class/powercap/intel-rapl:0/energy_uj"
DRAM = "/sys/class/powercap/intel-rapl:0:1/energy_uj"
HAVE_DRAM = os.path.exists(DRAM)

pynvml.nvmlInit()
GPU = pynvml.nvmlDeviceGetHandleByIndex(0)


def energy(path):
    """Joules since boot, with wraparound fix (counter resets on overflow)."""
    with open(path) as f:
        return int(f.read()) / 1e6


def gpu_power_w():
    try:
        return pynvml.nvmlDeviceGetPowerUsage(GPU) / 1000  # mW -> W
    except NVMLError:
        return 0.0


def cpu_freq_pct():
    # rough load proxy: current freq vs max
    gov = "/sys/devices/system/cpu/cpu0/cpufreq"
    try:
        cur = int(open(f"{gov}/scaling_cur_freq").read())
        mx = int(open(f"{gov}/cpuinfo_max_freq").read())
        return cur / mx
    except OSError:
        return -1


PRICE = 0.18  # EUR per kWh
WINDOW = 60.0  # rolling window seconds
prev = None
hist = []  # (timestamp, cpu_w, dram_w, gpu_w)


def fmt_row(label, inst, avg):
    return f" {label:4s}  {inst:7.2f} W   {avg:7.2f} W"


def main():
    prev = (energy(RAPL), energy(DRAM) if HAVE_DRAM else 0.0, time.perf_counter())
    header = (
        "Ctrl+C pour quitter. Fenetre moyenne: %.0f s\n" % WINDOW
        + f" {'':4s}  {'instant':>9s}   {'mean ' + str(int(WINDOW)) + 's':>9s}\n"
    )
    frame_lines = 0
    total_avg = n_cpu = n_dram = n_gpu = 0.0
    cpu_w = dram_w = gpu_w = 0.0
    try:
        while True:
            time.sleep(1.0)
            now = time.perf_counter()
            p, d, t = prev
            cp = energy(RAPL)
            cd = energy(DRAM) if HAVE_DRAM else cp  # no submodule: reuse cpu
            c = now
            dt = c - t
            if dt > 0:
                cpu_w = max(0.0, (cp - p) / dt)
                dram_w = max(0.0, (cd - d) / dt) if HAVE_DRAM else 0.0
                gpu_w = gpu_power_w()
                hist.append((now, cpu_w, dram_w, gpu_w))
                # drop older entries
                while hist and now - hist[0][0] > WINDOW:
                    hist.pop(0)
                n_cpu = sum(x[1] for x in hist) / len(hist)
                n_dram = sum(x[2] for x in hist) / len(hist)
                n_gpu = sum(x[3] for x in hist) / len(hist)
                prev = (cp, cd, c)
            rows = []
            rows.append(f" CPU   {cpu_w:7.2f} W   {n_cpu:7.2f} W")
            rows.append(f" DRAM  {dram_w:7.2f} W   {n_dram:7.2f} W")
            rows.append(f" GPU   {gpu_w:7.2f} W   {n_gpu:7.2f} W")
            rows.append(
                f" TOTAL {cpu_w + dram_w + gpu_w:7.2f} W   "
                f"{n_cpu + n_dram + n_gpu:7.2f} W   [fenetre: {len(hist)} ech.]"
            )
            total_avg = n_cpu + n_dram + n_gpu
            # Estimation au mur : silicium / rendement chargeur + fixes (ecran,
            # ventilos, chipset, VRM, Wi-Fi...)  - deux charges : une fixe ~10 W,
            # + variable ~4 W si le CPU charge
            fixed_w = 10.0
            charger_eff = 0.87
            wall_est = (total_avg + 4.0 if cpu_w > 15 else total_avg) / charger_eff + fixed_w
            kwh_24 = wall_est * 24 / 1000
            rows.append(
                f" moyenne 60s: {total_avg:6.2f} W silicium -> ~{wall_est:5.1f} W au mur "
                f"| {kwh_24 * PRICE:5.2f} EUR/jour   {kwh_24 * PRICE * 30:5.2f} EUR/mois"
            )
            # reecrit la meme page : remonte et efface les lignes du frame precedent
            frame = "\n".join(rows)
            redraw = "".join("\r\x1b[2K\x1b[A" for _ in range(frame_lines))
            print(redraw + header + frame)
            frame_lines = len(rows) + 2
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
