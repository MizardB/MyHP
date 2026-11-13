"""Command Line Interface for HP Prime communication."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from myhp.apps import build_app_directory
from myhp.formats import PrimeFileType, sanitize_note_name, sanitize_program_name
from myhp.images import png_icon, png_to_ppl
from myhp.usb import PrimeDevice, find_prime_devices


def _get_target_device(device_arg: str | None) -> PrimeDevice | None:
    """Resolve and open target device or report error."""
    devs = find_prime_devices()
    if not devs:
        print("Error: No se encontró ninguna calculadora HP Prime conectada.", file=sys.stderr)
        print("Comprueba la conexión USB y los permisos sobre /dev/hidraw*", file=sys.stderr)
        return None

    if device_arg:
        target = next((d for d in devs if d.hidraw_path == device_arg), None)
        if not target:
            print(f"Error: Dispositivo especificado {device_arg} no coincide con una HP Prime.", file=sys.stderr)
            return None
        return PrimeDevice(target.hidraw_path, model_hint=target.model_name)

    return PrimeDevice(devs[0].hidraw_path, model_hint=devs[0].model_name)


def cmd_send_note(args: argparse.Namespace) -> int:
    """Send a text note to the HP Prime Notes catalog."""
    file_path = Path(args.file)
    if not file_path.is_file():
        print(f"Error: No existe el archivo '{args.file}'.", file=sys.stderr)
        return 1

    try:
        content = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = file_path.read_bytes()

    note_name = args.name if args.name else file_path.stem
    safe_name = sanitize_note_name(note_name)

    prime = _get_target_device(args.device)
    if not prime:
        return 1

    try:
        with prime:
            chunks = prime.send_file(safe_name, content, file_type=PrimeFileType.NOTE)
            print(f"Nota '{safe_name}' enviada con éxito a {prime.hidraw_path} ({chunks} paquetes HID).")
    except PermissionError:
        print(f"Error: Permiso denegado al abrir {prime.hidraw_path}.", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"Error al enviar la nota: {e}", file=sys.stderr)
        return 3

    return 0


def cmd_send_prgm(args: argparse.Namespace) -> int:
    """Send a program (PPL or MicroPython) to the HP Prime Program catalog."""
    file_path = Path(args.file)
    if not file_path.is_file():
        print(f"Error: No existe el archivo '{args.file}'.", file=sys.stderr)
        return 1

    try:
        content = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = file_path.read_bytes()

    prgm_name = args.name if args.name else file_path.stem
    safe_name = sanitize_program_name(prgm_name)

    prime = _get_target_device(args.device)
    if not prime:
        return 1

    ext = file_path.suffix.lower()
    type_label = "MicroPython" if ext == ".py" else "PPL"

    try:
        with prime:
            chunks = prime.send_file(safe_name, content, file_type=PrimeFileType.PRGM)
            print(
                f"Programa {type_label} '{safe_name}' enviado con éxito a {prime.hidraw_path} ({chunks} paquetes HID)."
            )
    except PermissionError:
        print(f"Error: Permiso denegado al abrir {prime.hidraw_path}.", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"Error al enviar el programa: {e}", file=sys.stderr)
        return 3

    return 0


def cmd_send_image(args: argparse.Namespace) -> int:
    """Convert a PNG to a PPL image viewer and send it as a program."""
    file_path = Path(args.file)
    if not file_path.is_file():
        print(f"Error: No existe el archivo '{args.file}'.", file=sys.stderr)
        return 1
    try:
        image_data = file_path.read_bytes()
        requested_name = args.name if args.name else file_path.stem
        safe_name = sanitize_program_name(requested_name).upper()
        if args.app:
            content = png_to_ppl(image_data, safe_name, args.width, args.height, entrypoint="START")
            icon = png_icon(image_data)
            output_dir = Path(args.output) if args.output else file_path.parent
            app_directory = build_app_directory(safe_name, content, icon, output_dir)
        else:
            content = png_to_ppl(image_data, safe_name, args.width, args.height)
    except (OSError, ValueError) as e:
        print(f"Error al convertir la imagen: {e}", file=sys.stderr)
        return 1

    prime = _get_target_device(args.device)
    if not prime:
        return 1
    try:
        with prime:
            if args.app:
                chunks = prime.send_app(safe_name, str(app_directory))
                installed = any(
                    item.file_type == PrimeFileType.APP and item.name.lstrip("&").lower() == safe_name.lower()
                    for item in prime.list_content()
                )
                if not installed:
                    print(
                        f"El paquete de '{safe_name}' se transmitió ({chunks} paquetes HID), "
                        "pero no aparece en el catálogo Apps.",
                        file=sys.stderr,
                    )
                    print(f"Paquete local preparado: {app_directory}", file=sys.stderr)
                    return 3
                print(f"Aplicación '{safe_name}' instalada desde {file_path.name} en "
                      f"{prime.hidraw_path} ({chunks} paquetes HID).")
                print(f"En la calculadora: abre Apps y selecciona {safe_name}.")
                print(f"Paquete local: {app_directory}")
            else:
                chunks = prime.send_file(safe_name, content, file_type=PrimeFileType.PRGM)
                print(
                    f"Visor PPL '{safe_name}' creado desde {file_path.name} y enviado a "
                    f"{prime.hidraw_path} ({chunks} paquetes HID)."
                )
                print(f"En la calculadora: abre Programas y ejecuta {safe_name}().")
    except PermissionError:
        print(f"Error: Permiso denegado al abrir {prime.hidraw_path}.", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"Error al enviar el visor de imagen: {e}", file=sys.stderr)
        return 3
    return 0



def cmd_list(args: argparse.Namespace) -> int:
    """List objects stored in the HP Prime memory."""
    prime = _get_target_device(args.device)
    if not prime:
        return 1

    type_filter = args.type.lower() if args.type else "all"

    try:
        with prime:
            items = prime.list_content()
    except PermissionError:
        print(f"Error: Permiso denegado al abrir {prime.hidraw_path}.", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"Error al listar contenido de la calculadora: {e}", file=sys.stderr)
        return 3

    # Filter items
    if type_filter in ("note", "notes"):
        filtered = [it for it in items if it.file_type == PrimeFileType.NOTE]
    elif type_filter in ("prgm", "prgms", "programs", "progs"):
        filtered = [it for it in items if it.file_type == PrimeFileType.PRGM]
    elif type_filter in ("app", "apps"):
        filtered = [it for it in items if it.file_type == PrimeFileType.APP]
    else:
        filtered = items

    if not filtered:
        print(f"No se encontraron elementos de tipo '{type_filter}'.")
        return 0

    print(f"{'TIPO':<10} {'NOMBRE':<30} {'TAMAÑO (bytes)':>15}")
    print("-" * 58)
    for it in filtered:
        print(f"{it.type_name:<10} {it.name:<30} {it.size:>15}")
    print("-" * 58)
    print(f"Total: {len(filtered)} elemento(s)")

    return 0


def cmd_get_note(args: argparse.Namespace) -> int:
    """Retrieve and display or save a note from the HP Prime."""
    prime = _get_target_device(args.device)
    if not prime:
        return 1

    try:
        with prime:
            entry = prime.get_file(args.name, file_type=PrimeFileType.NOTE)
    except PermissionError:
        print(f"Error: Permiso denegado al abrir {prime.hidraw_path}.", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"Error al leer la nota: {e}", file=sys.stderr)
        return 3

    if not entry:
        print(f"Error: No se encontró la nota '{args.name}' en la calculadora.", file=sys.stderr)
        return 1

    text = entry.get_text_content()

    if args.output:
        out_path = Path(args.output)
        out_path.write_text(text, encoding="utf-8")
        print(f"Nota '{args.name}' guardada con éxito en {out_path}.")
    else:
        print(text)

    return 0


def cmd_delete_note(args: argparse.Namespace) -> int:
    """Delete/clear a note from the HP Prime memory."""
    prime = _get_target_device(args.device)
    if not prime:
        return 1

    try:
        with prime:
            prime.delete_file(args.name, file_type=PrimeFileType.NOTE)
            print(f"Nota '{args.name}' vaciada/eliminada en {prime.hidraw_path}.")
            print("Aviso: El protocolo Prime vacía el contenido de la nota.")
    except PermissionError:
        print(f"Error: Permiso denegado al abrir {prime.hidraw_path}.", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"Error al eliminar la nota: {e}", file=sys.stderr)
        return 3

    return 0


def cmd_info(args: argparse.Namespace) -> int:
    """Execute the info command to display calculator status."""
    devs = find_prime_devices()

    if not devs:
        print("Error: No se encontró ninguna calculadora HP Prime conectada.", file=sys.stderr)
        print("Comprueba la conexión USB y los permisos sobre /dev/hidraw*", file=sys.stderr)
        return 1

    # Filter by specific node if specified
    if args.device:
        target_dev = next((d for d in devs if d.hidraw_path == args.device), None)
        if not target_dev:
            print(f"Error: Dispositivo especificado {args.device} no coincide con una HP Prime.", file=sys.stderr)
            return 1
        devs = [target_dev]

    for d in devs:
        print("==================================================")
        print(f"Dispositivo detectado: {d.model_name}")
        print(f"  Nodo de dispositivo : {d.hidraw_path}")
        print(f"  USB VID:PID         : 0x{d.vid:04X}:0x{d.pid:04X}")
        if d.product_string:
            print(f"  Producto USB        : {d.product_string}")
        if d.manufacturer_string:
            print(f"  Fabricante          : {d.manufacturer_string}")

        try:
            with PrimeDevice(d.hidraw_path, model_hint=d.model_name) as prime:
                # Optional check ready
                try:
                    prime.check_ready()
                except Exception:
                    pass

                info = prime.get_info()
                print("--------------------------------------------------")
                print(f"  Número de serie     : {info.serial or 'N/A'}")
                print(f"  Versión de Firmware : {info.firmware or 'N/A'}")
                print(f"  Número de Build     : {info.build}")
                if info.raw_header:
                    print(f"  Identificador STAR  : {info.raw_header}")
        except PermissionError:
            print(f"  Error: Permiso denegado al abrir {d.hidraw_path}.", file=sys.stderr)
            print("  Asegúrate de tener permisos rw o regla udev configurada.", file=sys.stderr)
            return 2
        except Exception as e:
            print(f"  Error comunicando con la calculadora: {e}", file=sys.stderr)
            return 3

    print("==================================================")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Main CLI entrypoint."""
    parser = argparse.ArgumentParser(
        prog="myhp",
        description="Herramienta de comunicación con calculadoras HP Prime (G1 / G2)",
    )
    parser.add_argument(
        "-d", "--device",
        help="Ruta explícita al nodo hidraw (ej: /dev/hidraw1)",
        default=None,
    )

    subparsers = parser.add_subparsers(dest="command", help="Comandos disponibles")

    # Command: info
    info_parser = subparsers.add_parser("info", help="Muestra información del modelo, firmware y serie")
    info_parser.set_defaults(func=cmd_info)

    # Command: send
    send_parser = subparsers.add_parser("send", help="Envía archivos (notas, programas) a la calculadora")
    send_subparsers = send_parser.add_subparsers(dest="subcommand", help="Tipo de elemento a enviar")

    # Command: send note
    note_parser = send_subparsers.add_parser("note", help="Envía una nota a la app de Notas")
    note_parser.add_argument("file", help="Ruta al archivo de texto a enviar como nota")
    note_parser.add_argument("-n", "--name", help="Nombre de la nota en la calculadora (opcional)", default=None)
    note_parser.set_defaults(func=cmd_send_note)

    # Command: send prgm
    prgm_parser = send_subparsers.add_parser("prgm", help="Envía un programa PPL o script MicroPython")
    prgm_parser.add_argument("file", help="Ruta al archivo (.hpprgm, .py o .txt)")
    prgm_parser.add_argument("-n", "--name", help="Nombre del programa en la calculadora (opcional)", default=None)
    prgm_parser.set_defaults(func=cmd_send_prgm)

    # Command: send image (PNG converted to a PPL viewer)
    image_parser = send_subparsers.add_parser("image", help="Convierte un PNG en visor PPL o aplicación y lo envía")
    image_parser.add_argument("file", help="Ruta a la imagen PNG")
    image_parser.add_argument("-n", "--name", help="Nombre del programa (opcional)", default=None)
    image_parser.add_argument("--width", type=int, default=160, help="Ancho máximo en píxeles (1–320)")
    image_parser.add_argument("--height", type=int, default=120, help="Alto máximo en píxeles (1–240)")
    image_parser.add_argument("--app", action="store_true", help="Instala el visor como aplicación en Apps")
    image_parser.add_argument("--output", help="Carpeta donde guardar el paquete .hpappdir (opcional)")
    image_parser.set_defaults(func=cmd_send_image)

    # Command: list
    list_parser = subparsers.add_parser("list", help="Lista objetos almacenados en la memoria de la calculadora")
    list_parser.add_argument(
        "type",
        nargs="?",
        choices=["notes", "prgms", "apps", "all"],
        default="all",
        help="Tipo de elementos a listar (notes, prgms, apps, all)",
    )
    list_parser.set_defaults(func=cmd_list)

    # Command: get
    get_parser = subparsers.add_parser("get", help="Obtiene y muestra o descarga un archivo de la calculadora")
    get_subparsers = get_parser.add_subparsers(dest="subcommand", help="Tipo de elemento a obtener")

    # Command: get note
    get_note_parser = get_subparsers.add_parser("note", help="Obtiene el contenido de una nota")
    get_note_parser.add_argument("name", help="Nombre de la nota en la calculadora")
    get_note_parser.add_argument("-o", "--output", help="Ruta al archivo de salida donde guardar la nota", default=None)
    get_note_parser.set_defaults(func=cmd_get_note)

    # Command: delete
    del_parser = subparsers.add_parser("delete", help="Elimina/vacía un elemento en la memoria de la calculadora")
    del_subparsers = del_parser.add_subparsers(dest="subcommand", help="Tipo de elemento a eliminar")

    # Command: delete note
    del_note_parser = del_subparsers.add_parser("note", help="Elimina/vacía una nota")
    del_note_parser.add_argument("name", help="Nombre de la nota a eliminar")
    del_note_parser.set_defaults(func=cmd_delete_note)

    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 1

    if args.command == "send" and not getattr(args, "subcommand", None):
        send_parser.print_help()
        return 1

    if args.command == "get" and not getattr(args, "subcommand", None):
        get_parser.print_help()
        return 1

    if args.command == "delete" and not getattr(args, "subcommand", None):
        del_parser.print_help()
        return 1

    return args.func(args)



if __name__ == "__main__":
    sys.exit(main())
