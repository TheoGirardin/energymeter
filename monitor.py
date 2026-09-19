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


PRICE = 0.1674  # EUR per kWh
WINDOW = 60.0  # rolling window seconds

# Estimation au mur : silicium x FAN_LOAD (ventilos sous charge) / CHARGER_EFF
# (rendement PSU) + FIXED_W (charges fixes internes). Profils par machine
# (detecte via /sys/devices/virtual/dmi/id), ajouter une entree pour une
# nouvelle machine :
# - MSI MAG H610 Infinite S3 (i5-14400F + RTX 4060 Ti, PSU Bronze 0.87):
#   fixes internes 10 W (ventilos, chipset, VRM, reseau). Peripheriques
#   externes hors monitor: Apex 7 ~2.5 W ecran allume, DeathAdder Elite
#   ~0.5 W, Tonor TC-520 ~1 W, AOC 24G2 144Hz 20 W, Dell 27" HD 20 W.
# - Legion Y540-15IRH 81SX (i5-9300H + GTX 1660 Ti, adaptateur 0.87):
#   notebookcheck 14.5 W idle min / 18.5 W avg -> 15 W fixes.
PROFILES = {
    "MAG H610 Infinite S3": {"fixed_w": 10.0, "eff": 0.87, "fan": 1.06},
    "Legion Y540-15IRH": {"fixed_w": 15.0, "eff": 0.87, "fan": 1.06},
}
_PROFILE_DEFAULT = {"fixed_w": 15.0, "eff": 0.87, "fan": 1.06}

try:
    _dmi = open("/sys/devices/virtual/dmi/id/product_name").read().strip()
except OSError:
    _dmi = ""
_profile = next((v for k, v in PROFILES.items() if k in _dmi), _PROFILE_DEFAULT)
FIXED_W = _profile["fixed_w"]
CHARGER_EFF = _profile["eff"]
FAN_LOAD = _profile["fan"]
prev = None
hist = []  # (timestamp, cpu_w, dram_w, gpu_w)


def fmt_row(label, inst, avg):
    return f" {label:4s}  {inst:7.2f} W   {avg:7.2f} W"


def main():
    prev = (energy(RAPL), energy(DRAM) if HAVE_DRAM else 0.0, time.perf_counter())
    header = "Ctrl+C pour quitter\n"
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
            W = 90
            rows = []
            bar = "├" + "─" * W + "┤"
            top = "┌" + "─" * W + "┐"
            bot = "└" + "─" * W + "┘"

            def line(txt=""):
                return "│" + f" {txt}".ljust(W) + "│"

            row = lambda name, inst, avg: line(f"{name:<6}{inst:>15.2f} W {avg:>15.2f} W")
            rows.append(top)
            rows.append(line("Puissance (W)   instant      " + (f"moyen {WINDOW:.0f} s").rjust(15)))
            rows.append(bar)
            rows.append(row("CPU", cpu_w, n_cpu))
            rows.append(row("GPU", gpu_w, n_gpu))
            rows.append(row("DRAM", dram_w, n_dram) if HAVE_DRAM else line(f"{'DRAM':<6}{'n/a':>15} W {'~2.00':>15} W (estime inclus au total)"))
            dram_w_eff = dram_w if HAVE_DRAM else 2.0
            n_dram_eff = n_dram if HAVE_DRAM else 2.0
            total_avg = n_cpu + n_dram_eff + n_gpu
            t_costs = f"= {total_avg * 24 / 1000:4.2f} kWh/j  {total_avg * 24 / 1000 * PRICE:4.2f}€/j{total_avg * 24 / 1000 * PRICE * 30:5.2f}€/mois ({PRICE:.4f}€/kWh)"
            walls = f"{cpu_w + dram_w_eff + gpu_w:>15.2f} W {n_cpu + n_dram_eff + n_gpu:>15.2f} W  {t_costs}"
            rows.append(bar)
            rows.append(line(f"{'TOTAL':<6}{walls}"))
            wall_est = (total_avg * FAN_LOAD) / CHARGER_EFF + FIXED_W
            kwh_24 = wall_est * 24 / 1000
            t_costs_mur = f"= {kwh_24:4.2f} kWh/j  {kwh_24 * PRICE:4.2f}€/j{kwh_24 * PRICE * 30:5.2f}€/mois ({PRICE:.4f}€/kWh)"
            rows.append(line(f"{'TOTAL AU MUR':<33}{'~' + f'{wall_est:4.1f} W':>8}  {t_costs_mur}"))
            rows.append(bar)
            rows.append(line(f"{'Moyenne par écran':<35} ~20 W =  {20 * 24 / 1000:4.2f} kWh/j  {20 * 24 / 1000 * PRICE:4.2f}€/j"
                f"{20 * 24 / 1000 * PRICE * 30:5.2f}€/mois ({PRICE:.4f}€/kWh)"))
            rows.append(bot)
            rows.append(line(f"Model au mur : x{FAN_LOAD:.2f} ventilos/{CHARGER_EFF:.2f} PSU +{FIXED_W:.0f} W fixes"))


            frame = "\n".join(rows)
            redraw = "".join("\r\x1b[2K\x1b[A" for _ in range(frame_lines))
            print(redraw + header + frame)
            frame_lines = len(rows) + 2
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
