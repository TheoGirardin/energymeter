# ai-energymeter - Estimation de consommation du PC

## Installation (uv)

```bash
uv venv
uv pip install ai-energymeter matplotlib numpy nvidia-ml-py
```

## Lancer One shot

```bash
cd ~/work/ai-energymeter
sudo chmod -R a+r /sys/class/powercap/intel-rapl   # requis à chaque boot
.venv/bin/python measure_pc.py
```

## Lancer monitoring

```bash
sudo chmod -R a+r /sys/class/powercap/intel-rapl
.venv/bin/python monitor.py
```

## Alternative rapide

```bash
scaphandre stdout -t 15
```

## Résultat du dernier run (10 s : 5 s CPU + 5 s GPU)

```
cpu: 350 J | dram: 14 J | gpu: 215 J | disk: 0 J | total: 579 J (~0.16 Wh)
```

## Modifier le workload

Éditer la section `em.begin()` ... `em.end()` dans `measure_pc.py` : mettre le code à mesurer entre les deux.
