# Réduire la consommation du GPU (NVIDIA GTX 1660 Ti)

Le GPU consomme environ 7 W en idle et jusqu'à 80 W en charge.
Quand aucune tâche ne l'utilise (développement, containers, agents IA sans
calcul CUDA), on peut le faire passer en sommeil pour couper cette consommation.

## Option 1 - Runtime D3 (recommandé)

### Pourquoi

Le driver NVIDIA supporte la coupure automatique de l'alimentation du GPU
et de sa mémoire vidéo (VRAM) quand rien ne l'utilise, mais cette option
est désactivée par défaut (`Runtime D3 status: Disabled by default`).

### Ce que ça fait

Le système bascule le GPU en état D3 (coupure d'alimentation) dès qu'
aucun process ne l'utilise, et le fait repartir automatiquement en D0
(démarrage instantané) dès qu'une tâche CUDA démarre. Aucune action
manuelle, pas d'impact sur les agents IA : le GPU se réveille tout seul.

Gain attendu : ~5 W en idle (le 7 W idle descend vers 1-2 W), et 0 W quand
le GPU est complètement au repos prolongé.

### Application

1. Créer le fichier `/etc/modprobe.d/nvidia-power-management.conf` :

   ```
   options nvidia NVreg_DynamicPowerManagement=0x02
   ```

2. Reboot, puis vérifier :

   ```bash
   cat /proc/driver/nvidia/gpus/*/power   # Runtime D3 status: Enabled
   nvidia-smi --query-gpu=pstate,power.draw --format=csv
   ```

Remarque : si l'utilisation de la suspension (suspend) pose problème avec
`0x02`, ajouter `NVreg_PreserveVideoMemoryAllocations=1` à côté pour que
la VRAM soit sauvegardée.

## Option 2 - Décharger le driver quand il n'est pas utilisé

### Pourquoi

Tant que le driver NVIDIA et ses services sont chargés, ils maintiennent
le GPU actif et empêchent la coupure d'alimentation.

### Ce que ça fait

On arrête les process qui tiennent le driver ouvert (agents CUDA,
`nvidia-persistenced`, containers), ce qui permet au kernel de décharger
le module et de couper l'alimentation du GPU jusqu'à ~0 W.

```bash
# 1. Identifier ce qui tient le GPU ouvert
sudo fuser -v /dev/nvidia*

# 2. Arrêter le service de persistance si actif
sudo systemctl stop nvidia-persistenced

# 3. Sans process actif, décharger explicitement le stack :
sudo modprobe -r nvidia_uvm nvidia_drm nvidia_modeset nvidia
```

Inconvénient : si un process CUDA tourne (agents IA, containers),
le driver reste chargé de toute façon. Cette option ne sert que si tu
arrives à n'avoir aucun process CUDA au repos. À utiliser manuellement
ou via un script, pas en parallèle de sessions d'agents IA. Concrètement,
utilise le lanceur `gpu-power-cut.desktop` posé sur le Bureau.

## Statut réel sur cette machine (Y540-15IRH)

Option 1 ne fonctionne pas ici. Config appliquée correctement
(`DynamicPowerManagement: 2` vu par le driver), mais le driver refuse le
RTD3 : `Runtime D3 status: Not supported`. Cause dans `dmesg` :

```
NVRM: PlatformRequestHandler failed to get platform power mode
      from SBIOS [NV_ERR_INVALID_DATA 0x25]
```

Le SBIOS de ce châssis ne remonte pas les données ACPI nécessaires au
RTD3 (bug firmware classique sur Legion Y540 ; BIOS BHCN44WW de 01/2022,
dernière version publiée par Lenovo). Pas de contournement logiciel.

Notes : l'affichage doit rester sur l'iGPU (mode BIOS "Hybrid"),
sinon gnome-shell maintient le dGPU en D0 de toute façon.
`GSK_RENDERER=ngl` est posé dans `~/.config/environment.d/90-gsk-intel.conf`
pour que les apps GTK4 ne rendent pas sur la NVIDIA via Vulkan.

En pratique : option 2. Lanceur `gpu-power-cut.desktop` sur le Bureau :
décharge les modules NVIDIA via pkexec quand tu n'utilises pas le GPU.
Pour récupérer le GPU : n'importe quel process CUDA recharge le module
automatiquement.

## Choisir

- Sur ce Y540 : option 2 via le lanceur du Bureau (le RTD3 est bloqué
  par le SBIOS).
- Sur une machine avec un SBIOS sain : option 1, transparent et
  automatique.
