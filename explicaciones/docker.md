# Explicación detallada de archivos Docker

## 1. `Dockerfile`

### 1.1 Imagen base
```dockerfile
FROM python:3.11-slim
```
Usa una imagen de Python ligera basada en Debian.

### 1.2 Variable de entorno de licencia
```dockerfile
ENV ACCEPT_EULA=Y
```
Necesaria para instalar drivers de Microsoft (`msodbcsql17/18`).

### 1.3 Instalación de dependencias del sistema
Se instala:
- utilidades (`curl`, `gnupg`, `ca-certificates`)
- soporte ODBC (`unixodbc`, `unixodbc-dev`, `tdsodbc`)
- compilación (`build-essential`)

Luego:
- agrega la llave GPG de Microsoft
- agrega el repositorio oficial de paquetes
- instala drivers ODBC de SQL Server (`msodbcsql18` y `msodbcsql17`)

Esto permite que `pyodbc` se conecte a Azure SQL/SQL Server desde el contenedor.

### 1.4 Directorio de trabajo y dependencias Python
```dockerfile
WORKDIR /app
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt
```
Primero copia `requirements.txt` y luego instala paquetes para aprovechar cache de capas.

### 1.5 Copia del código
```dockerfile
COPY . /app
```
Copia toda la app al contenedor.

### 1.6 Exposición y comando de arranque
```dockerfile
EXPOSE 5000
CMD ["gunicorn", "biblioteca:app", "--bind", "0.0.0.0:5000"]
```
Publica puerto 5000 y ejecuta la aplicación con Gunicorn en modo producción.

---

## 2. `.dockerignore`
Este archivo evita copiar contenido innecesario al contexto de build:
- `__pycache__`, `*.pyc`, `*.pyo`, `*.pyd`
- entornos virtuales (`env/`, `venv/`, `ENV/`)
- artefactos de build (`build/`, `dist/`, `*.egg-info`)
- `.git`

Beneficios:
- builds más rápidos
- imágenes más pequeñas
- menor exposición de archivos no requeridos

---

## 3. Relación Docker + aplicación
- `requirements.txt` instala Flask, pyodbc y gunicorn.
- El `Dockerfile` instala tanto dependencias Python como drivers ODBC del sistema.
- La app inicia con `gunicorn biblioteca:app`.
- La conexión a base de datos se controla por `AZURE_SQL_CONNECTION_STRING` dentro del contenedor.
