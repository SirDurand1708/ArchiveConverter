import sys
import argparse
from pathlib import Path
from core import ConverterManager


def main():
    parser = argparse.ArgumentParser(
        description="ArchiveConverter CLI - Convertidor de archivos local, seguro y de alta fidelidad."
    )
    parser.add_argument("input_file", nargs="?", help="Ruta del archivo a convertir")
    parser.add_argument("target_format", nargs="?", help="Formato de destino (ej: docx, pdf, png, webp)")
    parser.add_argument("-o", "--output", help="Ruta o nombre del archivo de salida (opcional)")

    args = parser.parse_args()
    manager = ConverterManager()

    # Si no se pasan argumentos, mostrar ayuda interactiva y estado del sistema
    if not args.input_file:
        print("=" * 60)
        print("  ArchiveConverter Core Engine (Fase 1)")
        print("  100% Offline | Sin publicidad | Máxima privacidad")
        print("=" * 60)
        print("\nUso rápido:")
        print("  python main.py <archivo_origen> <formato_destino>")
        print("\nEjemplos:")
        print("  python main.py documento.pdf docx")
        print("  python main.py contrato.docx pdf")
        print("  python main.py foto.png webp")
        print("  python main.py reporte.pdf png")
        print("=" * 60)
        return

    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"\n[ERROR] El archivo no fue encontrado: {input_path}")
        sys.exit(1)

    # Si se pasa el archivo pero no el formato de destino, listar los formatos soportados
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


if __name__ == "__main__":
    main()
