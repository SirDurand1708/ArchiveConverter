import sys
import argparse
from pathlib import Path
from core import ConverterManager, PDFToolkit


def handle_conversion(args, manager):
    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"\n[ERROR] El archivo no fue encontrado: {input_path}")
        sys.exit(1)

    if not args.target_format:
        available = manager.get_supported_target_formats(input_path)
        print(f"\nArchivo: {input_path.name}")
        if available:
            print(f"Formatos disponibles para convertir: {', '.join(available)}")
            print(f"\nEjecuta: python main.py \"{args.input_file}\" <formato>")
        else:
            print("[INFO] No hay formatos de conversión registrados para este tipo de archivo aún.")
        return

    print(f"\nIniciando conversión de '{input_path.name}' a '{args.target_format}'...")
    result = manager.convert_file(
        input_path=input_path,
        target_format=args.target_format,
        output_path=args.output
    )

    if result.success:
        print(f"[OK] Conversión completada con éxito en {result.elapsed_seconds}s!")
        print(f"[->] Archivo generado: {result.output_path}")
    else:
        print(f"[FALLO] Error en la conversión ({result.elapsed_seconds}s):")
        print(f"        {result.error_message}")
        sys.exit(1)


def main():
    # Si se ejecuta sin argumentos (doble clic o desde consola), abrir la interfaz moderna
    if len(sys.argv) == 1:
        try:
            from ui_web import run_modern_gui
            run_modern_gui()
            return
        except Exception as e:
            print(f"[AVISO] Iniciando interfaz alternativa ({e}).")
            try:
                from ui import run_gui
                run_gui()
                return
            except Exception as e2:
                print(f"[ERROR] No se pudo iniciar ninguna interfaz: {e2}")
                return

    # Si se pasa un solo archivo (menú contextual del Explorador de Windows o arrastrar sobre el .exe)
    if len(sys.argv) == 2 and not sys.argv[1].startswith("-"):
        subcmds = {"gui", "merge", "split", "compress", "extract-images", "rotate", "protect", "unlock", "-h", "--help"}
        if sys.argv[1].lower() not in subcmds:
            cand = Path(sys.argv[1])
            if cand.exists() and cand.is_file():
                if hasattr(sys, 'frozen') or not hasattr(sys.stdin, 'isatty') or not sys.stdin.isatty():
                    try:
                        from ui_web import run_modern_gui
                        run_modern_gui(initial_file=str(cand.resolve()))
                        return
                    except Exception:
                        pass

    parser = argparse.ArgumentParser(
        description="ArchiveConverter - Convertidor y caja de herramientas de archivos local y privado."
    )
    subparsers = parser.add_subparsers(dest="command", help="Comandos disponibles")

    # Subcomando: gui
    parser_gui = subparsers.add_parser("gui", help="Abrir la interfaz gráfica de escritorio")
    parser_gui.add_argument("file", nargs="?", help="Archivo inicial a precargar en la interfaz")
    parser_gui.add_argument("--legacy", action="store_true", help="Abrir versión clásica CustomTkinter")

    # Subcomando: merge
    parser_merge = subparsers.add_parser("merge", help="Unir múltiples archivos PDF en uno solo")
    parser_merge.add_argument("files", nargs="+", help="Rutas de los archivos PDF a unir")
    parser_merge.add_argument("-o", "--output", default="merged.pdf", help="Ruta del archivo PDF resultante")

    # Subcomando: split
    parser_split = subparsers.add_parser("split", help="Dividir un PDF en páginas individuales o rango")
    parser_split.add_argument("file", help="Ruta del archivo PDF a dividir")
    parser_split.add_argument("-o", "--output-dir", help="Directorio donde guardar las páginas")
    parser_split.add_argument("--range", help="Rango de páginas (ej: 1-3)")

    # Subcomando: compress
    parser_compress = subparsers.add_parser("compress", help="Comprimir y optimizar un PDF")
    parser_compress.add_argument("file", help="Ruta del archivo PDF a comprimir")
    parser_compress.add_argument("-o", "--output", help="Ruta del PDF comprimido de salida")

    # Subcomando: extract-images
    parser_extract = subparsers.add_parser("extract-images", help="Extraer imágenes contenidas en un PDF")
    parser_extract.add_argument("file", help="Ruta del archivo PDF")
    parser_extract.add_argument("-o", "--output-dir", help="Directorio donde guardar las imágenes extraídas")

    # Subcomando: rotate
    parser_rotate = subparsers.add_parser("rotate", help="Rotar las páginas de un PDF")
    parser_rotate.add_argument("file", help="Ruta del archivo PDF")
    parser_rotate.add_argument("-d", "--degrees", type=int, default=90, help="Grados de rotación (90, 180, 270)")
    parser_rotate.add_argument("-o", "--output", help="Ruta del PDF rotado de salida")

    # Subcomando: protect
    parser_protect = subparsers.add_parser("protect", help="Proteger un PDF con contraseña")
    parser_protect.add_argument("file", help="Ruta del archivo PDF")
    parser_protect.add_argument("-p", "--password", required=True, help="Contraseña a establecer")
    parser_protect.add_argument("-o", "--output", help="Ruta del PDF protegido")

    # Subcomando: unlock
    parser_unlock = subparsers.add_parser("unlock", help="Desbloquear un PDF protegido")
    parser_unlock.add_argument("file", help="Ruta del archivo PDF protegido")
    parser_unlock.add_argument("-p", "--password", required=True, help="Contraseña actual del PDF")
    parser_unlock.add_argument("-o", "--output", help="Ruta del PDF desbloqueado")

    # Argumentos posicionales generales (para conversión directa: python main.py doc.pdf docx)
    parser.add_argument("input_file", nargs="?", help="Ruta del archivo a convertir")
    parser.add_argument("target_format", nargs="?", help="Formato de destino (ej: docx, pdf, png, webp)")
    parser.add_argument("-o", "--output", help="Ruta o nombre del archivo de salida")

    args = parser.parse_args()
    manager = ConverterManager()

    if args.command == "gui":
        if args.legacy:
            from ui import run_gui
            run_gui()
        else:
            from ui_web import run_modern_gui
            run_modern_gui(initial_file=args.file)
        return
    elif args.command == "merge":
        res = PDFToolkit.merge(args.files, args.output)
        print(f"[OK] {len(args.files)} PDFs unidos con éxito -> {res}")
        return
    elif args.command == "split":
        if args.range:
            parts = args.range.split("-")
            from_p, to_p = int(parts[0]), int(parts[1])
            res = PDFToolkit.split_range(args.file, from_p, to_p, output_path=args.output_dir)
            print(f"[OK] Rango {args.range} extraído -> {res}")
        else:
            files = PDFToolkit.split_all_pages(args.file, output_dir=args.output_dir)
            print(f"[OK] PDF dividido en {len(files)} páginas en {files[0].parent}")
        return
    elif args.command == "compress":
        res = PDFToolkit.compress(args.file, output_path=args.output)
        print(f"[OK] PDF optimizado y comprimido -> {res}")
        return
    elif args.command == "extract-images":
        imgs = PDFToolkit.extract_images(args.file, output_dir=args.output_dir)
        print(f"[OK] Se extrajeron {len(imgs)} imágenes en {args.output_dir or 'carpeta local'}")
        return
    elif args.command == "rotate":
        res = PDFToolkit.rotate_pages(args.file, degrees=args.degrees, output_path=args.output)
        print(f"[OK] PDF rotado en {args.degrees}° -> {res}")
        return
    elif args.command == "protect":
        res = PDFToolkit.protect(args.file, user_password=args.password, output_path=args.output)
        print(f"[OK] PDF protegido con cifrado AES-256 -> {res}")
        return
    elif args.command == "unlock":
        res = PDFToolkit.unlock(args.file, password=args.password, output_path=args.output)
        print(f"[OK] PDF desbloqueado -> {res}")
        return

    if not args.input_file:
        from ui_web import run_modern_gui
        run_modern_gui()
        return

    # Si se pasa un archivo sin formato de destino y no estamos en terminal interactivo
    if not args.target_format and (hasattr(sys, 'frozen') or not hasattr(sys.stdin, 'isatty') or not sys.stdin.isatty()):
        from ui_web import run_modern_gui
        run_modern_gui(initial_file=args.input_file)
        return

    handle_conversion(args, manager)


if __name__ == "__main__":
    main()
