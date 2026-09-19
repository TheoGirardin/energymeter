# ai-energymeter - Estimation de consommation du PC

sudo chmod -R a+r /sys/class/powercap/intel-rapl
.venv/bin/python monitor.py

## Lancer

```bash
cd ~/work/ai-energymeter
sudo chmod -R a+r /sys/class/powercap/intel-rapl   # requis à chaque boot
.venv/bin/python measure_pc.py

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
