# Explicación de `biblioteca.py`

## Resumen general
`biblioteca.py` es la aplicación principal en Flask para gestionar una biblioteca universitaria. Incluye:
- Inicio/cierre de sesión de usuarios.
- Gestión de usuarios, categorías y libros.
- Registro de préstamos y devoluciones.
- Reportes básicos.
- Conexión a Azure SQL mediante `pyodbc`.

## Partes principales

### 1) Configuración inicial
- Se crea la app de Flask y una `secret_key`.
- Se define una cadena de conexión por defecto para Azure SQL.
- La conexión real se obtiene desde la variable de entorno `AZURE_SQL_CONNECTION_STRING`.

### 2) Conexión a base de datos
- `obtener_driver_sql_server()`: detecta drivers ODBC compatibles instalados.
- `normalizar_cadena_conexion(...)`: ajusta formato de usuario/contraseña y parámetros requeridos.
- `reemplazar_nombre_driver(...)`: fuerza el driver correcto dentro de la cadena.
- `obtener_conexion_bd()`: abre conexión y lanza errores claros si falta driver o credenciales.

### 3) Utilidades de consulta
- `consultar_bd(...)`: ejecuta `SELECT` y devuelve filas como diccionarios.
- `ejecutar_bd(...)`: ejecuta `INSERT/UPDATE/DELETE`, hace `commit` y devuelve último id cuando aplica.

### 4) Control de sesión y permisos
- `usuario_actual()`: obtiene el usuario logueado desde sesión.
- `requerir_inicio_sesion()`: bloquea acceso si no hay sesión.
- `requerir_admin()`: restringe acciones administrativas.

### 5) Funciones de dominio
- Búsqueda y consulta de usuarios/libros/categorías.
- Conteos de préstamos por usuario y por libro.
- Resumen de préstamos por fecha.

### 6) Rutas web
- `/` redirige a login o panel.
- `/login`, `/logout`, `/dashboard` para autenticación y panel.
- `/users/*` CRUD de usuarios.
- `/categories/*` CRUD de categorías.
- `/books/*` CRUD y búsqueda de libros.
- `/loans` para préstamos/devoluciones.
- `/reports` para reportes.

### 7) Contexto global de plantillas
`@app.context_processor` inyecta datos comunes (usuario actual, si es admin, categorías y funciones de apoyo) para usarlos desde Jinja.

### 8) Manejo de errores
`@app.errorhandler(Exception)` captura errores no controlados y responde con un mensaje de error interno.
