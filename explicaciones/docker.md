# Explicación de Docker (`Dockerfile` y `.dockerignore`) para Render

## Objetivo en Render
Los archivos Docker están preparados para desplegar la app en Render usando un contenedor que ya trae:
- Python 3.11.
- Drivers ODBC necesarios.
- Drivers de Microsoft SQL Server (`msodbcsql18` y `msodbcsql17`).

Esto permite que la app Flask se conecte a Azure SQL dentro del entorno de Render.

## `Dockerfile` paso a paso
1. **Base**: `python:3.11-slim`.
2. **Dependencias del sistema**:
   - `unixodbc`, `unixodbc-dev`, `tdsodbc`, `build-essential`, etc.
   - Repositorio de Microsoft para instalar drivers SQL Server.
3. **Instalación de drivers SQL Server**:
   - Se instala `msodbcsql18` y `msodbcsql17`.
4. **App Python**:
   - Copia `requirements.txt` e instala dependencias con `pip`.
   - Copia el código de la app.
5. **Puerto y arranque**:
   - Expone `5000`.
   - Inicia con Gunicorn: `gunicorn biblioteca:app --bind 0.0.0.0:5000`.

## `.dockerignore`
Sirve para excluir archivos/carpetas que no deben entrar a la imagen, reduciendo tamaño y tiempo de build.

## Relación con Render
En Render, este Dockerfile garantiza:
- Entorno reproducible.
- Drivers ODBC disponibles al iniciar.
- Ejecución lista para producción con Gunicorn.

Para que funcione correctamente en Render, debes configurar en variables de entorno:
- `AZURE_SQL_CONNECTION_STRING`
- `PORT` (Render normalmente lo configura automáticamente)
