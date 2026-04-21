# Explicación detallada de `biblioteca.py`

## 1. Propósito general
`biblioteca.py` es la aplicación principal de Flask para administrar una biblioteca universitaria. Incluye autenticación, control de roles, CRUD de usuarios/categorías/libros, gestión de préstamos y reportes.

## 2. Estructura por bloques

### 2.1 Configuración base
- Se crea `app = Flask(__name__)`.
- Se define `app.secret_key` para manejo de sesión.
- Se configura una cadena de conexión por defecto para Azure SQL y se permite sobrescribirla con variable de entorno `AZURE_SQL_CONNECTION_STRING`.

### 2.2 Conexión a base de datos
Funciones principales:
- `obtener_driver_sql_server()`: detecta qué driver ODBC de SQL Server está instalado.
- `normalizar_cadena_conexion()`: asegura formato compatible de la cadena de conexión.
- `reemplazar_nombre_driver()`: sustituye/agrega el driver en la cadena final.
- `obtener_conexion_bd()`: abre la conexión `pyodbc.connect(...)` y lanza errores claros si falta driver o falla autenticación.

### 2.3 Funciones utilitarias de acceso a datos
- `consultar_bd(sql, params=None, one=False)`: ejecuta SELECT y devuelve lista de diccionarios o un solo registro.
- `ejecutar_bd(sql, params=None)`: ejecuta INSERT/UPDATE/DELETE, hace commit e intenta devolver último ID (`SCOPE_IDENTITY()`).

### 2.4 Autenticación y autorización
- `usuario_actual()`: lee `session['user_id']` y trae el usuario.
- `requerir_inicio_sesion()`: redirige al login si no hay sesión.
- `requerir_administrador()`: permite acciones administrativas solo a rol `admin`.

### 2.5 Consultas de dominio
- `obtener_usuario_por_username`, `obtener_usuario_por_id`.
- `obtener_libro`, `obtener_categoria`.
- `buscar_libros`: busca por texto y filtra por categoría.
- `contar_prestamos_libro`, `contar_prestamos_usuario`.
- `prestamos_por_fecha`: resume cantidad de préstamos por fecha.

## 3. Rutas HTTP

### 3.1 Sesión y navegación
- `/` (`inicio`): redirección a panel o login según sesión.
- `/iniciar_sesion` (`iniciar_sesion`): valida credenciales y crea sesión.
- `/cerrar_sesion` (`cerrar_sesion`): limpia sesión.
- `/panel` (`panel`): tablero con métricas y top de uso.

### 3.2 Usuarios (admin)
- `/users` listar.
- `/users/new` crear.
- `/users/edit/<int:user_id>` editar.
- `/users/delete/<int:user_id>` eliminar.

### 3.3 Categorías
- `/categories` listar.
- `/categories/new` crear (admin).
- `/categories/edit/<int:category_id>` editar (admin).
- `/categories/delete/<int:category_id>` eliminar (admin, con validación de dependencia de libros).

### 3.4 Libros
- `/books` listar y filtrar.
- `/books/new` crear (admin).
- `/books/edit/<int:book_id>` editar (admin), ajustando disponibilidad cuando cambia el total.
- `/books/delete/<int:book_id>` eliminar (admin, bloquea si hay préstamos activos).

### 3.5 Préstamos
- `/loans` (`gestionar_prestamos`):
  - acción `borrow`: crea préstamo y descuenta disponibilidad.
  - acción `return`: marca devolución y repone disponibilidad.
  - admin ve todos; usuario normal solo sus préstamos.

### 3.6 Reportes (admin)
- `/reportes` (`reportes`): top usuarios, top libros y resumen por fecha.

## 4. Integración con plantillas (Jinja)
`@app.context_processor` (`inyectar_usuario`) expone variables globales a todas las vistas:
- `usuario_actual`
- `es_admin`
- `categorias`
- `obtener_categoria`
- `contar_prestamos_usuario`
- `contar_prestamos_libro`

Esto evita repetir consultas en cada ruta para elementos de navegación o contadores comunes.

## 5. Manejo de errores
`@app.errorhandler(Exception)` captura errores no controlados:
- si es `HTTPException`, se devuelve normal.
- si es excepción general, se registra en logs y retorna página 500 simple.

## 6. Ejecución
Cuando se ejecuta directamente (`python biblioteca.py`):
- host `0.0.0.0`
- puerto `PORT` o `5000`
- `debug=False`

En contenedor se usa Gunicorn, no el servidor de desarrollo de Flask.
