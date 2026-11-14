# MyHP

Herramienta y biblioteca Python para comunicación con calculadoras HP Prime (G1 / G2).

## Funciones

MyHP se ejecuta en una computadora y se comunica con la calculadora por USB.
Actualmente, la detección USB está implementada para Linux (`hidraw`).

- Detecta calculadoras HP Prime G1 y G2 conectadas y muestra modelo, identificadores USB, firmware, build y número de serie (`info`).
- Envía archivos de texto como notas a la calculadora (`send note`).
- Envía programas al catálogo de programas (`send prgm`), incluidos archivos PPL y scripts MicroPython compatibles con la Prime.
- Convierte una imagen PNG en un visor PPL interactivo con soporte de color de 24 bits (`send image`).
- Crea e instala aplicaciones nativas de galería de imágenes (`send gallery`), empaquetando archivos PNG, JPG o BMP con visor PPL completo integrado en el catálogo **Apps**.
- Prepara y transfiere aplicaciones individuales como paquete `.hpappdir` (`send image --app`).
- Lista las notas, programas y aplicaciones almacenados, o todos los objetos que devuelve el catálogo (`list`).
- Recupera una nota y la muestra en pantalla o la guarda en un archivo (`get note`).
- Vacía el contenido de una nota (`delete note`). El protocolo usado no tiene un comando de borrado independiente; la nota se sobrescribe con contenido vacío.

La biblioteca también incluye funciones para formar y fragmentar paquetes del protocolo HP Prime, interpretar respuestas y contenido del catálogo, calcular CRC16 y normalizar nombres y texto para transferirlos.

## Comandos

```bash
myhp info
myhp send note nota.txt [--name NOMBRE]
myhp send prgm programa.hpprgm [--name NOMBRE]
myhp send image imagen.png [--name NOMBRE] [--width 160] [--height 120] [--app] [--output DIR]
myhp send gallery NOMBRE IMAGENES... [--icon ICON.png] [--output DIR]
myhp list [notes|prgms|apps|all]
myhp get note NOMBRE [--output archivo.txt]
myhp delete note NOMBRE
```

Los comandos aceptan `-d` o `--device` para indicar una ruta de dispositivo `hidraw` concreta, por ejemplo `/dev/hidraw1`.

### Galería de Imágenes en la Calculadora (`send gallery`)

Crea y transfiere una aplicación completa al catálogo **Apps** con soporte para múltiples imágenes (PNG, JPG o BMP):

```bash
# Enviar imágenes o carpetas directamente a la HP Prime
myhp send gallery VACACIONES ./fotos/ --icon icono.png

# O especificar imágenes individuales
myhp send gallery GRAFICOS fig1.png fig2.jpg fig3.bmp

# Generar solo el paquete local sin calculadora conectada
myhp send gallery FORMULAS ./formulas/ --output ./build/
```

- **Apertura directa**: Al abrir la aplicación desde el menú **Apps**, el visor se inicia mostrando automáticamente la primera imagen.
- **Navegación táctil**: Arrastra el dedo en la pantalla táctil para desplazarte (pan) libremente sobre la imagen en cualquier dirección.
- **Navegación por teclado**: Flechas de dirección para desplazamiento suave.
- **Zoom**: Teclas `+` y `-` para aumentar o reducir el factor de zoom, o doble toque en la pantalla táctil para alternar zoom rápidamente.
- **Restablecer vista**: Teclas `0` o `Enter` centran y reajustan la imagen.
- **Cambio de imagen**: Pulsa `Esc` para acceder al diálogo interactivo de selección de imágenes (`CHOOSE`) entre todos los archivos incluidos en la galería.
- **Directorio temporal**: Si no se proporciona `--output`, el paquete se construye en memoria/directorio temporal y se transfiere sin dejar residuos en el directorio de trabajo local.

### Visor PPL individual (`send image`)

`send image` admite PNG de 8 bits por canal sin entrelazado. La imagen se ajusta al tamaño máximo indicado (hasta 320×240), se convierte con paleta interactiva de 24 bits y se empaqueta como visor PPL.

Para instalarla como aplicación independiente en **Apps**:

```bash
myhp send image imagen.png --app --name IMAGEN
```

`--output CARPETA` permite elegir dónde guardar el paquete `.hpappdir` generado. MyHP comprueba el catálogo al terminar y reporta un error si la app no aparece. La transferencia directa está en fase experimental; los archivos de plantilla están bajo licencia MIT de hp-prime-kit (ver `myhp/data/app_templates/NOTICE`).

## Uso rápido

```bash
# Ejecución directa sin instalar
python3 -m myhp.cli info

# O instalando en modo editable
pip install -e .
myhp info
```
