<div align="center">

<img src="assets/banner.png" alt="myhp — HP Prime G2 Linux USB HID CLI & AI Agent Bridge" width="100%" />

<br />

**Controla tu calculadora HP Prime (G1 / G2) directamente desde la terminal o con tu agente de IA.**

[![Platform](https://img.shields.io/badge/platform-Linux%20(hidraw)-FCC624?style=flat-square&logo=linux&logoColor=black)](#)
[![Hardware](https://img.shields.io/badge/calculator-HP%20Prime%20G1%20%7C%20G2-0096D6?style=flat-square)](#)
[![Protocol](https://img.shields.io/badge/protocol-USB%20HID%20V1%20%2F%20V2-314360?style=flat-square)](#)
[![Python](https://img.shields.io/badge/python-3.9%2B-3776AB?style=flat-square&logo=python&logoColor=white)](#)

</div>

---

Olvídate de interfaces gráficas pesadas. **myhp** te permite gestionar tu **HP Prime** desde la línea de comandos en un segundo, ideal para integrarlo en tu flujo de estudio o dárselo como herramienta a **tu agente de IA**:

- 📝 **Apuntes al instante:** genera resúmenes o formularios con tu agente y mándalos directo a **Notas**.
- 🧮 **Código sin fricción:** escribe scripts en **PPL** o **MicroPython** y súbelos al catálogo de **Programas**.
- 🖼️ **Fórmulas e imágenes en alta resolución:** empaqueta diagramas, tablas y capturas (`.png`, `.jpg`, `.bmp`) en una **App nativa** que abre directo en pantalla con zoom y desplazamiento táctil.

> 🐧 **Soporte de plataforma:** Exclusivo para **Linux** (cualquier distribución con soporte `hidraw` en el kernel: **NixOS, Arch, Ubuntu/Debian, Fedora**, etc.). **No hay soporte para Windows ni macOS por ahora.**

---

## 🛠️ Instalación

```bash
pip install -e .
```

Si tu usuario no tiene permisos sobre `/dev/hidraw*`, habilita la regla `udev`:

```bash
sudo tee /etc/udev/rules.d/99-hp-prime.rules << 'EOF'
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="03f0", ATTRS{idProduct}=="0441", MODE="0666"
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="03f0", ATTRS{idProduct}=="1541", MODE="0666"
EOF
sudo udevadm control --reload-rules && sudo udevadm trigger
```

---

## 🚀 Uso

> 💡 **Flag global:** agrega `-d /dev/hidrawX` antes de cualquier comando si necesitas apuntar a un puerto específico (`myhp -d /dev/hidraw1 info`).

### 1. 🔍 Conectar e inspeccionar la calculadora

Ver modelo detectado, número de serie y versión de firmware:

```bash
myhp info
```

Explorar qué tienes guardado en memoria (`all`, `notes`, `prgms`, `apps`):

```bash
myhp list              # Todo el catálogo
myhp list notes        # Solo notas
myhp list prgms        # Solo programas PPL / MicroPython
myhp list apps         # Solo aplicaciones instaladas
```

---

### 2. 📝 Gestionar Notas (`note`)

Enviar un archivo de texto directo a la app **Notas**:

```bash
myhp send note apuntes.txt
myhp send note apuntes.txt -n "Resistencia"     # Con nombre personalizado
```

Leer en pantalla o respaldar una nota de la calculadora a tu PC:

```bash
myhp get note "Resistencia"                     # Imprime en la terminal
myhp get note "Resistencia" -o backup.txt       # Guarda en un archivo local
```

Vaciar o eliminar una nota en la calculadora:

```bash
myhp delete note "Resistencia"
```

---

### 3. 💻 Enviar Programas PPL y MicroPython (`prgm`)

Subir código PPL (`.hpprgm` / `.txt`) o scripts de MicroPython (`.py`) al catálogo de **Programas**:

```bash
myhp send prgm vigas.txt                      # Usa el nombre del archivo (VIGAS)
myhp send prgm vigas.txt -n SOLVER_VIGAS      # Nombre personalizado en la Prime
myhp send prgm circuito.py -n CIRCUITO        # Script MicroPython
```

---

### 4. 🖼️ Enviar Fórmulas, Tablas e Imágenes (`gallery` / `image`)

#### Opción A — App de Galería nativa (recomendado)
Crea una aplicación en **Apps** con tus imágenes originales (`.png`, `.jpg`, `.jpeg`, `.bmp`) sin pérdida de calidad. Al tocar la app en la calculadora, **abre directo en la primera imagen** (`+`/`-` o pellizco para zoom, arrastrar para mover, `◄`/`►` para cambiar de imagen, `Esc` para elegir de la lista):

```bash
# Enviar una sola imagen (ej. hoja de fórmulas)
myhp send gallery FORMULAS form.png

# Agrupar varias imágenes o carpetas enteras en una sola App
myhp send gallery FORMULAS form1.png form2.jpg ./tablas/

# Personalizar el icono de la App (32x32) o guardar el paquete .hpappdir en disco
myhp send gallery FORMULAS ./imagenes/ --icon icono.png
myhp send gallery FORMULAS ./imagenes/ --output ./build
```

#### Opción B — Imagen dibujada en código PPL (`image`)
Convierte un `.png` ligero en un programa PPL autocontenido:

```bash
myhp send image grafico.png -n GRAFICO
myhp send image grafico.png -n GRAFICO --width 240 --height 180
myhp send image grafico.png -n GRAFICO --app --output ./build
```
