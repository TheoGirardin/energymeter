# Couper la consommation du GPU NVIDIA au repos

Machine : Lenovo Legion Y540-15IRH (81SX), i5-9300H, GTX 1660 Ti mobile 6 Go.
Driver : NVIDIA 595.84 open kernel module (Ubuntu, nvidia-driver-595-open).
OS : Ubuntu 26.04, GNOME Wayland.

## Le problème

Le GPU consomme :

- ~5 à 7 W en idle avec le driver chargé (p8, 669 MiB de VRAM utilisée par le compositeur au départ)
- 0 W si le driver est déchargé

5 W permanents = ~0,9 kWh/mois pour rien quand aucune tache IA/dev n'utilise
le GPU. L'objectif : couper cette conso au repos, sans casser l'usage
transitoire du GPU par les agents IA (voxtype, Ollama, containers CUDA).

## Pourquoi c'est compliqué sur ce châssis

Trois blocages indépendants se cumulent :

1. **Bug SBIOS (firmware)** : le driver NVIDIA refuse outright le Runtime D3
   automatique (`Runtime D3 status: Not supported`). dmesg :

   ```
   NVRM: PlatformRequestHandler failed to get platform power mode
         from SBIOS [NV_ERR_INVALID_DATA 0x25]
   ```

   BIOS BHCN44WW (01/2022), dernière version publiée par Lenovo pour ce
   modèle. Aucun contournement logiciel possible.

2. **gnome-shell / mutter tient le driver** : avec `nvidia_drm.modeset=1`,
   la NVIDIA expose un device DRM secondaire (`/dev/dri/card2`. mutter l'ouvre
   et crée un "gbm renderer" au démarrage de session, avant toute demande
   utilisateur, et moi ne le relâche jamais tant que le driver est chargé.

3. **Apps GTK4 + Vulkan** : par défaut, GTK4 rend via Vulkan, et le loader
   Vulkan référence les 2 GPUs. Toute app ouverte tient `/dev/nvidia0`.
   Idem pour EGL : mutter charge `libnvidia-eglcore` et ouvre les devices.

## Solutions appliquées

### 1. Déplacer l'affichage sur l'iGPU Intel (pré-requis)

Dans le BIOS : "Hybrid Mode" (pas "Discrete GPU only"). Consequence :

- L'affichage tourné sur l'Intel UHD 630 (`card1`), la NVIDIA
  `display_active: Disabled`.
- `GSK_RENDERER=ngl` dans `~/.config/environment.d/90-gsk-intel.conf` :
  les apps GTK4 rendent via OpenGL-on-Intel, pas Vulkan-on-NVIDIA.

### 2. `nvidia_drm.modeset=0` - la NVIDIA quitte l'empire du DRM

Piège : le paramètre vit dans **deux fichiers**. Le vendor
(`/lib/modprobe.d/nvidia-kms.conf`, généré par ubuntu-drivers) écrase
`/etc/modprobe.d/nvidia-graphics-drivers-kms.conf`. Les deux doivent dire :

```
options nvidia_drm modeset=0
options nvidia_drm modeset=0   # idem dans /usr/lib/modprobe.d/
```

Effet : plus de `card.nvidia`, mutter échoue explicitement à ouvrir le
device GPU NVIDIA (`DRM_CLIENT_CAP_UNIVERSAL_PLANES not supported`),
gnome-shell n'occupe plus `/dev/nvidia*`.

Impact compute : aucun. CUDA et Vulkan (context/IA) passent par les
ioctl M dev, indépendants de modeset. Interdit avec modeset=0 :
`nvidia-settings` (NV-CONTROL manager d'écrans) - masqué dans
`~/.config/autostart/nvidia-settings-autostart.desktop` (étaient
autostart concerné : autostart vendor `nvidia-settings-autostart.desktop`
référencé par /etc/xdg/autostart).

### 3. EGL / Vulkan limités à l'Intel pour la session

- `~/.config/environment.d/92-egl-intel-only.conf` :

  ```
  __EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/50_mesa.json
  ```

- `~/.local/share/vulkan/icd.d/nvidia_icd.json` (chargé après le
  system path) pointe `library_path` vers un chemin inexistant :
  le loader Vulkan ne propose plus la NVIDIA aux apps session (Voxtype
  retombe sur le Vulkan Intel ; les apps CUDA Ollama/containers utilisent
  le driver coil via nvml pas le ICD Vulkan, donc pas d'impact).

### 4. Le GPU en Runtime D3hot automatique

Une fois les tenants éliminés, le runtime PM du noyau suspend le device
PCI tout seul :

```
$ fuser /dev/nvidia*        # vide
$ cat /sys/bus/pci/devices/0000:01:00.0/power/runtime_status
suspended
$ cat /sys/bus/pci/devices/0000:01:00.0/firmware_node/power_state
D3hot
```

Réveil ~instantané sur toute charge CUDA/Vulkan, re-suspend ~40 s après
la dernière utilisation. Quantifier la conso dans cet état demande un
mètre à la prise : `nvidia-smi` force le reveil pour reopener le contexte
driver, sa lecture (26 W) est celle du resume, pas du repos.

### 5. `gpu-power-cut.sh` : déchargement total à la demande

`~/Desktop/gpu-power-cut.sh` (lanceur du Bureau, version pkexec) :

```bash
#!/bin/bash
# Coupe l'alimentation du GPU en déchargeant le driver NVIDIA.
# Ne tue AUCUN process. Si un process tient /dev/nvidia* ouvert,
# le script avorte et affiche qui bloque.
set -u
if fuser /dev/nvidia* >/dev/null 2>&1; then
    echo "GPU bloqué par :"
    fuser -v /dev/nvidia* 2>&1
    echo "Ferme ces applications puis relance."
    exit 1
fi
systemctl stop nvidia-persistenced 2>/dev/null
modprobe -r nvidia_uvm nvidia_drm nvidia_modeset nvidia 2>&1
if lsmod | grep -q nvidia; then
    echo "Échec déchargement ; certains modules restent"
    exit 1
fi
echo "GPU déchargé (0 W). Il se rechargera seul au prochain usage CUDA."
```

Règle d'or : **ne jamais `fuser -k`**. Une première version du lanceur
faisait `fuser -k /dev/nvidia0` + `nvidia-smi drain` : ça a tué gnome-shell,
donc la session entière (crash). Décharger proprement est couvert par
l'avortement explicite : si quelqu'un tient le GPU, on affiche et on avertit.

### 6. voxtype : court-circuiter le GPU au besoin

Le daemon voice-to-text charge un modèle whisper par Vulkan
(`voxtype-vulkan`) et tient donc le dGPU via le loader Vulkan. Deux choix :

1. Service arrêté au repos : `systemctl --user stop voxtype.service`
   (commande sûre, à 3s près restitute l'accès au lanceur `gpu-power-cut`).
2. Utiliser le backend CPU aussi (`voxtype-onnx-avx512`, aussi long à
  démarrer) : modifier `~/.config/systemd/user/voxtype.service`
  `ExecStart=` ; `Restart=on-failure` avec `StartLimitBurst`,
  ou arrêt manuel avant de couper le GPU (sinon cycle de rechargement).

### 7. Vérification après coup

Le lanceur `gpu-status.desktop` (Bureau) écrit un snapshot dans
`/tmp/gpu-status.txt` (tenants, modules, runtime_status) sans terminal.
ne ouvre pas autre chose avant d'avoir mesuré - le plus léger readers
peut tenir le dGPU.

## Résultat mesuré

| état | conso GPU | lever |
|---|---|---|
| début (affichage sur NVIDIA) | ~5-7 W idle | driver chargé obligatoirement |
| driver chargé, tous tenants éliminés | 0 W.consum sur le bus, PCI power_state D3hot | auto suspend |
| driver déchargé (`gpu-power-cut`) | 0 W | réveil auto au premier CUDA use |

soit environ 0,9 kWh/mois de récupérés pour un usage bureautique/dev, et
le GPU en instantané disponible sans action manuelle quand un agent IA
démarrer.

## Sur quoi ça bouge et faut pas toucher

- `s/nvidia-runtimepm.conf` : fichier d'option doublon supprimé.
- `NVreg_DynamicPowerManagement=0x02` : toujours appliqué (inoffensif).
- `NVreg_PreserveVideoMemoryAllocations=1` + `TemporaryFilePath=/var/tmp` :
  conservés pour le suspend system.
- Prochaine regression : si messagerie d'état nouveau monologue récurrent
  d'update de DRIVER à mode "/settings", suivre ce doc ; tester d'abord
  `fuser -v /dev/nvidia*` pour identifier un nouveau tenant.

---



## Comparatif mesuré A/B/C (2026-09-19)

Protocole : 3 min par config, ~56 échantillons de 3 s, terminal ouvert +
monitor.py en boucle NVML (conditions identiques).

| Config | package RAPL | GPU nvidia-smi | Total silicium visible |
|---|---|---|---|
| Hybrid + optimisé (modeset=0, EGL Intel) | 13,1 W (iGPU inclus) | 5,7 W si polling NVML, 0 W suspendu | 14-19 W |
| Hybrid stock (modeset=1, EGL libre) | 14,2 W | 5,9 W D0 verrouillé | 19,9 W |
| Discrete (dGPU only, iGPU off) | 4,5 W | 10,0 W (pilote l'écran) | 14,6 W |

Piège de lecture : le package RAPL passe de 13 W à 4,5 W en discrete
parce que l'iGPU (dans package-0) est désactivé : le coût de l'affichage
sort du compteur CPU et réapparaît côté GPU (10 W). La facture murale
réelle est comparable en session active.

Au repos réel (terminal fermé, machine idle) :

- hybrid optimisé : **3,3 W** total (package 3,3 W + GPU suspendu)
- hybrid stock : ~19 W (5,9 W GPU verrouillé + session)
- discrete : ~14 W (9-10 W pour afficher un écran idle, GPU insuspendable)

Conclusion : le discrete coûte ~11 W de plus en idle ; le seul mode
restaurable à faible repos est hybrid + optimisé. Repasser en discrete
serait une régression énergétique pure.

Pour restaurer : `sudo bash ~/Desktop/restore-gpu-optimized.sh`, puis
BIOS "Hybrid Mode", puis reboot. La mesure complète repère `dmesg`
`PlatformRequestHandler` (bug SBIOS) : aucun changement de firmware
disponible pour ce châssis (BIOS BHCN44WW 01/2022 = dernier).
