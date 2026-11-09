# 🤝 Guía de Contribución a ArchiveConverter

¡Gracias por tu interés en colaborar con **ArchiveConverter**! Este es un proyecto de código abierto impulsado por la comunidad con el firme propósito de devolver a los usuarios el control y la privacidad sobre sus documentos.

---

## 🧭 Principios Fundamentales del Proyecto

Antes de desarrollar cualquier funcionalidad, ten en cuenta los siguientes pilares irrenunciables:

1. **100% Offline y Privado:** Ninguna función, librería o herramienta debe conectarse a servidores externos, enviar telemetría ni requerir credenciales de usuario. Todas las operaciones se realizan localmente en la máquina del usuario.
2. **Cero Publicidad y Cero Rastreadores:** El proyecto nunca incluirá anuncios, enlaces patrocinados ni análisis de comportamiento.
3. **Calidad y Fidelidad en la Conversión:** Preferimos conversiones estructuralmente correctas (ej: reconstrucción de párrafos/tablas con `pdf2docx`, auto-ajuste de Excel con `openpyxl`/ReportLab) antes que aproximaciones visuales planas o capturas de baja calidad.

---

## 🛠️ Configuración del Entorno de Desarrollo

1. **Clonar el repositorio:**
   ```bash
   git clone https://github.com/tu-usuario/ArchiveConverter.git
   cd ArchiveConverter
   ```

2. **Crear y activar un entorno virtual (Python 3.11+):**
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\activate
   ```

3. **Instalar dependencias de desarrollo y producción:**
   ```powershell
   pip install --upgrade pip
   pip install -r requirements.txt
   pip install pyinstaller
   ```

4. **Ejecutar la suite de pruebas unitarias:**
   ```powershell
   python -m unittest discover tests
   ```

5. **Lanzar la interfaz gráfica en modo local:**
   ```powershell
   python main.py
   ```

---

## 🌿 Flujo de Trabajo con Ramas (Branches) y Pull Requests

1. Crea una rama descriptiva para tu cambio:
   ```bash
   git checkout -b feature/nueva-herramienta-pdf
   # o
   git checkout -b fix/error-excel-orientacion
   ```
2. Realiza tus modificaciones manteniendo el estilo de código limpio y comentarios descriptivos.
3. Agrega pruebas unitarias dentro del directorio `tests/` para cualquier nueva función o caso de error corregido.
4. Asegúrate de que todos los tests pasen con éxito antes de enviar:
   ```bash
   python -m unittest discover tests
   ```
5. Realiza tus commits con mensajes claros:
   ```bash
   git commit -m "feat(pdf): añadir soporte para extracción de metadatos"
   ```
6. Abre un **Pull Request** explicando detalladamente la motivación del cambio y las pruebas realizadas.

---

## 📝 Convenciones de Código

- Código en Python compatible con Python 3.11 en adelante.
- Uso de `pathlib.Path` para manipulación de rutas multiplataforma.
- Tipado estático con `typing` (`Optional`, `Dict`, `List`, `Tuple`, etc.).
- Manejo de excepciones defensivo: fallos en conversiones deben devolver mensajes legibles al usuario sin provocar cierres inesperados de la aplicación.

¡Gracias por hacer de ArchiveConverter una herramienta más útil, rápida y segura para todos!
