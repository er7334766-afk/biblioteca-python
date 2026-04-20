from datetime import datetime
import logging
import os

import pyodbc
from flask import Flask, flash, redirect, render_template, request, session, url_for

app = Flask(__name__)
app.secret_key = "clave_de_prueba_cambiar"

CADENA_CONEXION_AZURE_SQL_PREDETERMINADA = (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    "Server=tcp:ed.database.windows.net,1433;"
    "Database=si;"
    "UID=ed;"
    "PWD=Honduras123/;"
    "Encrypt=yes;"
    "TrustServerCertificate=no;"
    "Connection Timeout=30;"
)

CADENA_CONEXION_AZURE_SQL = os.environ.get(
    "AZURE_SQL_CONNECTION_STRING",
    CADENA_CONEXION_AZURE_SQL_PREDETERMINADA,
)


def get_sql_server_driver():
    nombres_candidatos = [
        "ODBC Driver 18 for SQL Server",
        "ODBC Driver 17 for SQL Server",
        "ODBC Driver 13 for SQL Server",
        "SQL Server",
        "FreeTDS",
    ]
    controladores_instalados = [d for d in pyodbc.drivers()]
    for nombre_objetivo in nombres_candidatos:
        coincidencia = next(
            (d for d in controladores_instalados if d.lower() == nombre_objetivo.lower()),
            None,
        )
        if coincidencia:
            return coincidencia
    return None


def normalize_connection_string(cadena_conexion: str) -> str:
    cadena_normalizada = cadena_conexion.strip()
    if "User ID=" in cadena_normalizada and "UID=" not in cadena_normalizada:
        cadena_normalizada = cadena_normalizada.replace("User ID=", "UID=")
    if "Password=" in cadena_normalizada and "PWD=" not in cadena_normalizada:
        cadena_normalizada = cadena_normalizada.replace("Password=", "PWD=")
    if "Trusted_Connection" not in cadena_normalizada:
        if not cadena_normalizada.endswith(";"):
            cadena_normalizada += ";"
        cadena_normalizada += "Trusted_Connection=no;"
    return cadena_normalizada


def replace_driver_name(cadena_conexion: str, nombre_controlador: str) -> str:
    import re

    if re.search(r"(?i)DRIVER=\{[^}]+\}", cadena_conexion):
        return re.sub(r"(?i)DRIVER=\{[^}]+\}", f"DRIVER={{{nombre_controlador}}}", cadena_conexion)
    if re.search(r"(?i)Driver=[^;]+", cadena_conexion):
        return re.sub(r"(?i)Driver=[^;]+", f"Driver={nombre_controlador}", cadena_conexion)
    if not cadena_conexion.endswith(";"):
        cadena_conexion += ";"
    return f"DRIVER={{{nombre_controlador}}};{cadena_conexion}"


def get_db_connection():
    if not CADENA_CONEXION_AZURE_SQL:
        raise RuntimeError(
            "Configure AZURE_SQL_CONNECTION_STRING with the correct Azure SQL credentials."
        )

    cadena_conexion = normalize_connection_string(CADENA_CONEXION_AZURE_SQL)
    nombre_controlador = get_sql_server_driver()
    if nombre_controlador:
        cadena_conexion = replace_driver_name(cadena_conexion, nombre_controlador)
    else:
        controladores_instalados = [d for d in pyodbc.drivers()]
        raise RuntimeError(
            "No se encontró un driver ODBC compatible para Azure SQL en el entorno. "
            f"Drivers instalados: {controladores_instalados}. "
            "Instala 'ODBC Driver 18 for SQL Server' o 'ODBC Driver 17 for SQL Server', "
            "o despliega la app en un contenedor con el driver instalado."
        )

    try:
        return pyodbc.connect(cadena_conexion, autocommit=False)
    except pyodbc.Error as exc:
        controladores_instalados = [d for d in pyodbc.drivers()]
        raise RuntimeError(
            "Error al conectar con Azure SQL. "
            f"Driver usado: {nombre_controlador}. "
            f"Drivers instalados: {controladores_instalados}. "
            f"Detalle: {exc}"
        ) from exc


def query_db(consulta_sql, parametros=None, one=False):
    conexion = get_db_connection()
    cursor = conexion.cursor()
    cursor.execute(consulta_sql, parametros or ())
    columnas = [columna[0] for columna in cursor.description] if cursor.description else []
    filas = [dict(zip(columnas, fila)) for fila in cursor.fetchall()]
    cursor.close()
    conexion.close()
    return filas[0] if one and filas else filas


def execute_db(consulta_sql, parametros=None):
    conexion = get_db_connection()
    cursor = conexion.cursor()
    cursor.execute(consulta_sql, parametros or ())
    conexion.commit()
    ultimo_id = None
    try:
        cursor.execute("SELECT SCOPE_IDENTITY()")
        fila = cursor.fetchone()
        if fila:
            ultimo_id = fila[0]
    except Exception:
        ultimo_id = None
    cursor.close()
    conexion.close()
    return ultimo_id


def current_user():
    id_usuario = session.get("user_id")
    return get_user_by_id(id_usuario) if id_usuario else None


def require_login():
    if not session.get("user_id"):
        return redirect(url_for("login"))
    return None


def require_admin():
    usuario = current_user()
    if not usuario or usuario.get("role") != "admin":
        flash("Acceso denegado. Solo administradores.", "warning")
        return redirect(url_for("dashboard"))
    return None


def get_user_by_username(nombre_usuario):
    return query_db("SELECT * FROM usuarios WHERE username = ?", (nombre_usuario,), one=True)


def get_user_by_id(id_usuario):
    return query_db("SELECT * FROM usuarios WHERE id = ?", (id_usuario,), one=True)


def get_book(id_libro):
    return query_db("SELECT * FROM libros WHERE id = ?", (id_libro,), one=True)


def get_category(id_categoria):
    return query_db("SELECT * FROM categorias WHERE id = ?", (id_categoria,), one=True)


def search_books(consulta, id_categoria):
    sql = "SELECT * FROM libros"
    filtros = []
    parametros = []
    consulta_texto = (consulta or "").strip().lower()

    if consulta_texto:
        filtros.append("(LOWER(title) LIKE ? OR LOWER(author) LIKE ?)")
        valor_like = f"%{consulta_texto}%"
        parametros.extend([valor_like, valor_like])

    if id_categoria:
        filtros.append("category_id = ?")
        parametros.append(id_categoria)

    if filtros:
        sql += " WHERE " + " AND ".join(filtros)

    sql += " ORDER BY title"
    return query_db(sql, parametros)


def book_loans_count(id_libro):
    resultado = query_db(
        "SELECT COUNT(*) AS total FROM prestamos WHERE book_id = ?", (id_libro,), one=True
    )
    return resultado["total"] if resultado else 0


def user_loans_count(id_usuario):
    resultado = query_db(
        "SELECT COUNT(*) AS total FROM prestamos WHERE user_id = ?", (id_usuario,), one=True
    )
    return resultado["total"] if resultado else 0


def loans_by_date():
    filas = query_db(
        "SELECT CONVERT(date, start_date) AS fecha, COUNT(*) AS total FROM prestamos GROUP BY CONVERT(date, start_date) ORDER BY fecha DESC"
    )
    resumen = []
    for fila in filas:
        fecha = fila["fecha"]
        if hasattr(fecha, "strftime"):
            fecha_formateada = fecha.strftime("%Y-%m-%d")
        else:
            fecha_formateada = str(fecha)
        resumen.append((fecha_formateada, fila["total"]))
    return resumen


@app.route("/")
def index():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        nombre_usuario = request.form.get("username", "").strip()
        contrasena = request.form.get("password", "").strip()
        usuario = get_user_by_username(nombre_usuario)
        if usuario and usuario["password"] == contrasena:
            session["user_id"] = usuario["id"]
            flash(f"Bienvenido {usuario['name']}", "success")
            return redirect(url_for("dashboard"))
        flash("Usuario o contraseña inválidos.", "danger")
    return render_template("inicio_sesion.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Has cerrado sesión correctamente.", "info")
    return redirect(url_for("login"))


@app.route("/dashboard")
def dashboard():
    if redirect_result := require_login():
        return redirect_result
    usuario = current_user()
    total_libros = query_db("SELECT COUNT(*) AS total FROM libros", one=True)["total"]
    total_usuarios = query_db("SELECT COUNT(*) AS total FROM usuarios", one=True)["total"]
    total_prestamos = query_db("SELECT COUNT(*) AS total FROM prestamos WHERE returned = 0", one=True)["total"]
    prestamos_recientes = query_db("SELECT TOP 5 * FROM prestamos ORDER BY start_date DESC")
    usuarios_principales = query_db(
        "SELECT TOP 5 u.id, u.name, u.role, COUNT(p.id) AS loan_count "
        "FROM usuarios u "
        "LEFT JOIN prestamos p ON p.user_id = u.id "
        "GROUP BY u.id, u.name, u.role "
        "ORDER BY loan_count DESC"
    )
    libros_principales = query_db(
        "SELECT TOP 5 l.id, l.title, l.author, l.category_id, l.available, l.total, COUNT(p.id) AS loan_count "
        "FROM libros l "
        "LEFT JOIN prestamos p ON p.book_id = l.id "
        "GROUP BY l.id, l.title, l.author, l.category_id, l.available, l.total "
        "ORDER BY loan_count DESC"
    )
    return render_template(
        "panel.html",
        user=usuario,
        total_books=total_libros,
        total_users=total_usuarios,
        total_loans=total_prestamos,
        recent_loans=prestamos_recientes,
        top_users=usuarios_principales,
        top_books=libros_principales,
    )


@app.route("/users")
def list_users():
    if redirect_result := require_login():
        return redirect_result
    if redirect_result := require_admin():
        return redirect_result
    lista_usuarios = query_db("SELECT * FROM usuarios ORDER BY name")
    return render_template("usuarios.html", users=lista_usuarios)


@app.route("/users/new", methods=["GET", "POST"])
def add_user():
    if redirect_result := require_login():
        return redirect_result
    if redirect_result := require_admin():
        return redirect_result
    if request.method == "POST":
        execute_db(
            "INSERT INTO usuarios (username, password, role, name) VALUES (?, ?, ?, ?)",
            (
                request.form["username"].strip(),
                request.form["password"].strip(),
                request.form["role"],
                request.form["name"].strip(),
            ),
        )
        flash("Usuario agregado correctamente.", "success")
        return redirect(url_for("list_users"))
    return render_template("usuario_form.html", action="Crear", user=None)


@app.route("/users/edit/<int:user_id>", methods=["GET", "POST"])
def edit_user(user_id):
    if redirect_result := require_login():
        return redirect_result
    if redirect_result := require_admin():
        return redirect_result
    usuario_item = get_user_by_id(user_id)
    if not usuario_item:
        flash("Usuario no encontrado.", "warning")
        return redirect(url_for("list_users"))
    if request.method == "POST":
        contrasena = request.form.get("password", "").strip()
        if contrasena:
            execute_db(
                "UPDATE usuarios SET username = ?, password = ?, role = ?, name = ? WHERE id = ?",
                (
                    request.form["username"].strip(),
                    contrasena,
                    request.form["role"],
                    request.form["name"].strip(),
                    user_id,
                ),
            )
        else:
            execute_db(
                "UPDATE usuarios SET username = ?, role = ?, name = ? WHERE id = ?",
                (
                    request.form["username"].strip(),
                    request.form["role"],
                    request.form["name"].strip(),
                    user_id,
                ),
            )
        flash("Usuario actualizado correctamente.", "success")
        return redirect(url_for("list_users"))
    return render_template("usuario_form.html", action="Editar", user=usuario_item)


@app.route("/users/delete/<int:user_id>")
def delete_user(user_id):
    if redirect_result := require_login():
        return redirect_result
    if redirect_result := require_admin():
        return redirect_result
    execute_db("DELETE FROM usuarios WHERE id = ?", (user_id,))
    flash("Usuario eliminado.", "info")
    return redirect(url_for("list_users"))


@app.route("/categories")
def list_categories():
    if redirect_result := require_login():
        return redirect_result
    lista_categorias = query_db("SELECT * FROM categorias ORDER BY name")
    return render_template("categorias.html", categories=lista_categorias)


@app.route("/categories/new", methods=["GET", "POST"])
def add_category():
    if redirect_result := require_login():
        return redirect_result
    if redirect_result := require_admin():
        return redirect_result
    if request.method == "POST":
        execute_db(
            "INSERT INTO categorias (name) VALUES (?)",
            (request.form["name"].strip(),),
        )
        flash("Categoría agregada correctamente.", "success")
        return redirect(url_for("list_categories"))
    return render_template("categoria_form.html", action="Crear", category=None)


@app.route("/categories/edit/<int:category_id>", methods=["GET", "POST"])
def edit_category(category_id):
    if redirect_result := require_login():
        return redirect_result
    if redirect_result := require_admin():
        return redirect_result
    categoria = get_category(category_id)
    if not categoria:
        flash("Categoría no encontrada.", "warning")
        return redirect(url_for("list_categories"))
    if request.method == "POST":
        execute_db(
            "UPDATE categorias SET name = ? WHERE id = ?",
            (request.form["name"].strip(), category_id),
        )
        flash("Categoría actualizada correctamente.", "success")
        return redirect(url_for("list_categories"))
    return render_template("categoria_form.html", action="Editar", category=categoria)


@app.route("/categories/delete/<int:category_id>")
def delete_category(category_id):
    if redirect_result := require_login():
        return redirect_result
    if redirect_result := require_admin():
        return redirect_result
    associated = query_db(
        "SELECT COUNT(*) AS total FROM libros WHERE category_id = ?",
        (category_id,),
        one=True,
    )
    if associated and associated["total"] > 0:
        flash("No se puede eliminar una categoría con libros asignados.", "warning")
        return redirect(url_for("list_categories"))
    execute_db("DELETE FROM categorias WHERE id = ?", (category_id,))
    flash("Categoría eliminada.", "info")
    return redirect(url_for("list_categories"))


@app.route("/books")
def list_books():
    if redirect_result := require_login():
        return redirect_result
    consulta = request.args.get("q", "")
    id_categoria = request.args.get("category_id")
    id_categoria = int(id_categoria) if id_categoria and id_categoria.isdigit() else None
    libros_filtrados = search_books(consulta, id_categoria)
    lista_categorias = query_db("SELECT * FROM categorias ORDER BY name")
    return render_template(
        "libros.html",
        books=libros_filtrados,
        categories=lista_categorias,
        query=consulta,
        selected_category=id_categoria,
    )


@app.route("/books/new", methods=["GET", "POST"])
def add_book():
    if redirect_result := require_login():
        return redirect_result
    if redirect_result := require_admin():
        return redirect_result
    if request.method == "POST":
        total = int(request.form["total"])
        execute_db(
            "INSERT INTO libros (title, author, category_id, available, total, description) VALUES (?, ?, ?, ?, ?, ?)",
            (
                request.form["title"].strip(),
                request.form["author"].strip(),
                int(request.form["category_id"]),
                total,
                total,
                request.form["description"].strip(),
            ),
        )
        flash("Libro agregado correctamente.", "success")
        return redirect(url_for("list_books"))
    lista_categorias = query_db("SELECT * FROM categorias ORDER BY name")
    return render_template("libro_form.html", action="Crear", book=None, categories=lista_categorias)


@app.route("/books/edit/<int:book_id>", methods=["GET", "POST"])
def edit_book(book_id):
    if redirect_result := require_login():
        return redirect_result
    if redirect_result := require_admin():
        return redirect_result
    libro = get_book(book_id)
    if not libro:
        flash("Libro no encontrado.", "warning")
        return redirect(url_for("list_books"))
    if request.method == "POST":
        nuevo_total = int(request.form["total"])
        disponible = max(libro["available"] + (nuevo_total - libro["total"]), 0)
        execute_db(
            "UPDATE libros SET title = ?, author = ?, category_id = ?, available = ?, total = ?, description = ? WHERE id = ?",
            (
                request.form["title"].strip(),
                request.form["author"].strip(),
                int(request.form["category_id"]),
                disponible,
                nuevo_total,
                request.form["description"].strip(),
                book_id,
            ),
        )
        flash("Libro actualizado correctamente.", "success")
        return redirect(url_for("list_books"))
    lista_categorias = query_db("SELECT * FROM categorias ORDER BY name")
    return render_template("libro_form.html", action="Editar", book=libro, categories=lista_categorias)


@app.route("/books/delete/<int:book_id>")
def delete_book(book_id):
    if redirect_result := require_login():
        return redirect_result
    if redirect_result := require_admin():
        return redirect_result
    prestamos_activos = query_db(
        "SELECT COUNT(*) AS total FROM prestamos WHERE book_id = ? AND returned = 0",
        (book_id,),
        one=True,
    )
    if prestamos_activos and prestamos_activos["total"] > 0:
        flash("No se puede eliminar un libro con préstamos activos.", "warning")
        return redirect(url_for("list_books"))
    execute_db("DELETE FROM libros WHERE id = ?", (book_id,))
    flash("Libro eliminado.", "info")
    return redirect(url_for("list_books"))


@app.route("/loans", methods=["GET", "POST"])
def manage_loans():
    if redirect_result := require_login():
        return redirect_result
    usuario = current_user()
    if request.method == "POST":
        accion = request.form.get("action")
        if accion == "borrow":
            id_libro = int(request.form["book_id"])
            libro = get_book(id_libro)
            if libro and libro["available"] > 0:
                execute_db(
                    "INSERT INTO prestamos (book_id, user_id, start_date, returned) VALUES (?, ?, ?, ?)",
                    (id_libro, usuario["id"], datetime.now(), 0),
                )
                execute_db(
                    "UPDATE libros SET available = available - 1 WHERE id = ?",
                    (id_libro,),
                )
                flash("Préstamo registrado correctamente.", "success")
            else:
                flash("No hay ejemplares disponibles para préstamo.", "danger")
        elif accion == "return":
            id_prestamo = int(request.form["loan_id"])
            prestamo = query_db("SELECT * FROM prestamos WHERE id = ?", (id_prestamo,), one=True)
            if prestamo and not prestamo["returned"]:
                execute_db(
                    "UPDATE prestamos SET returned = 1, return_date = ? WHERE id = ?",
                    (datetime.now(), id_prestamo),
                )
                execute_db(
                    "UPDATE libros SET available = available + 1 WHERE id = ?",
                    (prestamo["book_id"],),
                )
                flash("Devolución registrada correctamente.", "success")
        return redirect(url_for("manage_loans"))

    if usuario["role"] == "admin":
        prestamos_visibles = query_db("SELECT * FROM prestamos ORDER BY start_date DESC")
    else:
        prestamos_visibles = query_db(
            "SELECT * FROM prestamos WHERE user_id = ? ORDER BY start_date DESC",
            (usuario["id"],),
        )
    return render_template(
        "prestamos.html",
        loans=prestamos_visibles,
        books=query_db("SELECT * FROM libros ORDER BY title"),
        users=query_db("SELECT * FROM usuarios ORDER BY name"),
        user=usuario,
    )


@app.route("/reports")
def reports():
    if redirect_result := require_login():
        return redirect_result
    if redirect_result := require_admin():
        return redirect_result
    usuarios_principales = query_db(
        "SELECT TOP 5 u.id, u.name, u.role, COUNT(p.id) AS loan_count "
        "FROM usuarios u "
        "LEFT JOIN prestamos p ON p.user_id = u.id "
        "GROUP BY u.id, u.name, u.role "
        "ORDER BY loan_count DESC"
    )
    libros_principales = query_db(
        "SELECT TOP 5 l.id, l.title, l.author, l.category_id, l.available, l.total, COUNT(p.id) AS loan_count "
        "FROM libros l "
        "LEFT JOIN prestamos p ON p.book_id = l.id "
        "GROUP BY l.id, l.title, l.author, l.category_id, l.available, l.total "
        "ORDER BY loan_count DESC"
    )
    resumen_fechas = loans_by_date()
    return render_template(
        "reportes.html",
        top_users=usuarios_principales,
        top_books=libros_principales,
        date_summary=resumen_fechas,
    )


@app.context_processor
def inject_user():
    usuario = current_user()
    return {
        "current_user": usuario,
        "is_admin": usuario["role"] == "admin" if usuario else False,
        "categories": query_db("SELECT * FROM categorias ORDER BY name"),
        "get_category": get_category,
        "user_loans_count": user_loans_count,
        "book_loans_count": book_loans_count,
    }


@app.errorhandler(Exception)
def handle_exception(exc):
    logging.exception("Unhandled exception")
    return f"<h1>Internal Server Error</h1><pre>{str(exc)}</pre>", 500


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=False,
    )
