# MyHP

Herramienta y biblioteca Python para comunicación con calculadoras HP Prime (G1 / G2).

## Funciones

MyHP se ejecuta en una computadora y se comunica con la calculadora por USB.
Actualmente, la detección USB está implementada para Linux (`hidraw`).

- Detecta calculadoras HP Prime G1 y G2 conectadas y muestra modelo, identificadores USB, firmware, build y número de serie (`info`).
- Envía archivos de texto como notas a la calculadora (`send note`).
- Envía programas al catálogo de programas (`send prgm`), incluidos archivos PPL y scripts MicroPython compatibles con la Prime.
- Convierte una imagen PNG en un programa PPL que la dibuja en pantalla y la envía al catálogo (`send image`).
- También puede preparar el visor como paquete `.hpappdir` y probar su envío directo a Apps (`send image --app`).
- Lista las notas, programas y aplicaciones almacenados, o todos los objetos que devuelve el catálogo (`list`).
- Recupera una nota y la muestra en pantalla o la guarda en un archivo (`get note`).
- Vacía el contenido de una nota (`delete note`). El protocolo usado no tiene un comando de borrado independiente; la nota se sobrescribe con contenido vacío.

La biblioteca también incluye funciones para formar y fragmentar paquetes del protocolo HP Prime, interpretar respuestas y contenido del catálogo, calcular CRC16 y normalizar nombres y texto para transferirlos.

## Comandos

```bash
myhp info
myhp send note nota.txt [--name NOMBRE]
myhp send prgm programa.hpprgm [--name NOMBRE]
myhp send image imagen.png [--name NOMBRE] [--width 160] [--height 120] [--app]
myhp list [notes|prgms|apps|all]
myhp get note NOMBRE [--output archivo.txt]
myhp delete note NOMBRE
```

Los comandos aceptan `-d` o `--device` para indicar una ruta de dispositivo `hidraw` concreta, por ejemplo `/dev/hidraw1`.

`send image` admite PNG de 8 bits por canal sin entrelazado. La imagen se reduce proporcionalmente al tamaño máximo indicado (hasta 320×240), se convierte a color de 16 bits y se empaqueta como visor PPL. Al ejecutarlo desde **Programas**, muestra la imagen hasta que se pulse una tecla. La primera versión no incluye zoom ni navegación entre imágenes.

Para instalarla como aplicación en **Apps**:

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
