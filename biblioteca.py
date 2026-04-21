from datetime import datetime
import logging
import os

import pyodbc
from flask import Flask, flash, redirect, render_template, request, session, url_for
from werkzeug.exceptions import HTTPException

app = Flask(__name__)
app.secret_key = "clave_de_prueba_cambiar"

DEFAULT_AZURE_SQL_CONNECTION_STRING = (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    "Server=tcp:ed.database.windows.net,1433;"
    "Database=si;"
    "UID=ed;"
    "PWD=Honduras123/;"
    "Encrypt=yes;"
    "TrustServerCertificate=no;"
    "Connection Timeout=30;"
)

AZURE_SQL_CONNECTION_STRING = os.environ.get(
    "AZURE_SQL_CONNECTION_STRING",
    DEFAULT_AZURE_SQL_CONNECTION_STRING,
)


def obtener_driver_sql_server():
    nombres_candidatos = [
        "ODBC Driver 18 for SQL Server",
        "ODBC Driver 17 for SQL Server",
        "ODBC Driver 13 for SQL Server",
        "SQL Server",
        "FreeTDS",
    ]
    drivers_instalados = [d for d in pyodbc.drivers()]
    for driver_buscado in nombres_candidatos:
        driver_coincidente = next((d for d in drivers_instalados if d.lower() == driver_buscado.lower()), None)
        if driver_coincidente:
            return driver_coincidente
    return None


def normalizar_cadena_conexion(cadena_conexion: str) -> str:
    cs = cadena_conexion.strip()
    if "User ID=" in cs and "UID=" not in cs:
        cs = cs.replace("User ID=", "UID=")
    if "Password=" in cs and "PWD=" not in cs:
        cs = cs.replace("Password=", "PWD=")
    if "Trusted_Connection" not in cs:
        if not cs.endswith(";"):
            cs += ";"
        cs += "Trusted_Connection=no;"
    return cs


def reemplazar_nombre_driver(cadena_conexion: str, nombre_driver: str) -> str:
    import re

    if re.search(r"(?i)DRIVER=\{[^}]+\}", cadena_conexion):
        return re.sub(r"(?i)DRIVER=\{[^}]+\}", f"DRIVER={{{nombre_driver}}}", cadena_conexion)
    if re.search(r"(?i)Driver=[^;]+", cadena_conexion):
        return re.sub(r"(?i)Driver=[^;]+", f"Driver={nombre_driver}", cadena_conexion)
    if not cadena_conexion.endswith(";"):
        cadena_conexion += ";"
    return f"DRIVER={{{nombre_driver}}};{cadena_conexion}"


def obtener_conexion_bd():
    if not AZURE_SQL_CONNECTION_STRING:
        raise RuntimeError(
            "Configure AZURE_SQL_CONNECTION_STRING with the correct Azure SQL credentials."
        )

    cadena_conexion = normalizar_cadena_conexion(AZURE_SQL_CONNECTION_STRING)
    nombre_driver = obtener_driver_sql_server()
    if nombre_driver:
        cadena_conexion = reemplazar_nombre_driver(cadena_conexion, nombre_driver)
    else:
        drivers_instalados = [d for d in pyodbc.drivers()]
        raise RuntimeError(
            "No se encontró un driver ODBC compatible para Azure SQL en el entorno. "
            f"Drivers instalados: {drivers_instalados}. "
            "Instala 'ODBC Driver 18 for SQL Server' o 'ODBC Driver 17 for SQL Server', "
            "o despliega la app en un contenedor con el driver instalado."
        )

    try:
        return pyodbc.connect(cadena_conexion, autocommit=False)
    except pyodbc.Error as excepcion:
        drivers_instalados = [d for d in pyodbc.drivers()]
        raise RuntimeError(
            "Error al conectar con Azure SQL. "
            f"Driver usado: {nombre_driver}. "
            f"Drivers instalados: {drivers_instalados}. "
            f"Detalle: {excepcion}"
        ) from excepcion


def consultar_bd(sql, params=None, one=False):
    conexion = obtener_conexion_bd()
    cursor = conexion.cursor()
    cursor.execute(sql, params or ())
    columnas = [column[0] for column in cursor.description] if cursor.description else []
    filas = [dict(zip(columnas, row)) for row in cursor.fetchall()]
    cursor.close()
    conexion.close()
    return filas[0] if one and filas else filas


def ejecutar_bd(sql, params=None):
    conexion = obtener_conexion_bd()
    cursor = conexion.cursor()
    cursor.execute(sql, params or ())
    conexion.commit()
    ultimo_id = None
    try:
        cursor.execute("SELECT SCOPE_IDENTITY()")
        row = cursor.fetchone()
        if row:
            ultimo_id = row[0]
    except Exception:
        ultimo_id = None
    cursor.close()
    conexion.close()
    return ultimo_id


def usuario_actual():
    user_id = session.get("user_id")
    return obtener_usuario_por_id(user_id) if user_id else None


def requerir_inicio_sesion():
    if not session.get("user_id"):
        return redirect(url_for("iniciar_sesion"))
    return None


def requerir_administrador():
    user = usuario_actual()
    if not user or user.get("role") != "admin":
        flash("Acceso denegado. Solo administradores.", "warning")
        return redirect(url_for("panel"))
    return None


def obtener_usuario_por_username(username):
    return consultar_bd("SELECT * FROM usuarios WHERE username = ?", (username,), one=True)


def obtener_usuario_por_id(user_id):
    return consultar_bd("SELECT * FROM usuarios WHERE id = ?", (user_id,), one=True)


def obtener_libro(book_id):
    return consultar_bd("SELECT * FROM libros WHERE id = ?", (book_id,), one=True)


def obtener_categoria(category_id):
    return consultar_bd("SELECT * FROM categorias WHERE id = ?", (category_id,), one=True)


def buscar_libros(query, category_id):
    sql = (
        "SELECT l.*, c.name AS category_name "
        "FROM libros l "
        "LEFT JOIN categorias c ON c.id = l.category_id"
    )
    filtros = []
    params = []
    texto_busqueda = (query or "").strip().lower()

    if texto_busqueda:
        filtros.append(
            "(LOWER(l.title) LIKE ? OR LOWER(l.author) LIKE ? OR LOWER(c.name) LIKE ?)"
        )
        valor_like = f"%{texto_busqueda}%"
        params.extend([valor_like, valor_like, valor_like])

    if category_id:
        filtros.append("l.category_id = ?")
        params.append(category_id)

    if filtros:
        sql += " WHERE " + " AND ".join(filtros)

    sql += " ORDER BY l.title"
    return consultar_bd(sql, params)


def contar_prestamos_libro(book_id):
    resultado = consultar_bd(
        "SELECT COUNT(*) AS total FROM prestamos WHERE book_id = ?", (book_id,), one=True
    )
    return resultado["total"] if resultado else 0


def contar_prestamos_usuario(user_id):
    resultado = consultar_bd(
        "SELECT COUNT(*) AS total FROM prestamos WHERE user_id = ?", (user_id,), one=True
    )
    return resultado["total"] if resultado else 0


def prestamos_por_fecha():
    filas = consultar_bd(
        "SELECT CONVERT(date, start_date) AS fecha, COUNT(*) AS total FROM prestamos GROUP BY CONVERT(date, start_date) ORDER BY fecha DESC"
    )
    resumen = []
    for row in filas:
        fecha = row["fecha"]
        if hasattr(fecha, "strftime"):
            fecha_texto = fecha.strftime("%Y-%m-%d")
        else:
            fecha_texto = str(fecha)
        resumen.append((fecha_texto, row["total"]))
    return resumen


@app.route("/")
def inicio():
    if session.get("user_id"):
        return redirect(url_for("panel"))
    return redirect(url_for("iniciar_sesion"))


@app.route("/iniciar_sesion", methods=["GET", "POST"])
def iniciar_sesion():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        user = obtener_usuario_por_username(username)
        if user and user["password"] == password:
            session["user_id"] = user["id"]
            flash(f"Bienvenido {user['name']}", "success")
            return redirect(url_for("panel"))
        flash("Usuario o contraseña inválidos.", "danger")
    return render_template("inicio_sesion.html")


@app.route("/cerrar_sesion")
def cerrar_sesion():
    session.clear()
    flash("Has cerrado sesión correctamente.", "info")
    return redirect(url_for("iniciar_sesion"))


@app.route("/panel")
def panel():
    if resultado_redireccion := requerir_inicio_sesion():
        return resultado_redireccion
    user = usuario_actual()
    total_libros = consultar_bd("SELECT COUNT(*) AS total FROM libros", one=True)["total"]
    total_usuarios = consultar_bd("SELECT COUNT(*) AS total FROM usuarios", one=True)["total"]
    total_prestamos = consultar_bd("SELECT COUNT(*) AS total FROM prestamos WHERE returned = 0", one=True)["total"]
    prestamos_recientes = consultar_bd("SELECT TOP 5 * FROM prestamos ORDER BY start_date DESC")
    top_usuarios = consultar_bd(
        "SELECT TOP 5 u.id, u.name, u.role, COUNT(p.id) AS loan_count "
        "FROM usuarios u "
        "LEFT JOIN prestamos p ON p.user_id = u.id "
        "GROUP BY u.id, u.name, u.role "
        "ORDER BY loan_count DESC"
    )
    top_libros = consultar_bd(
        "SELECT TOP 5 l.id, l.title, l.author, l.category_id, l.available, l.total, COUNT(p.id) AS loan_count "
        "FROM libros l "
        "LEFT JOIN prestamos p ON p.book_id = l.id "
        "GROUP BY l.id, l.title, l.author, l.category_id, l.available, l.total "
        "ORDER BY loan_count DESC"
    )
    return render_template(
        "panel.html",
        user=user,
        total_libros=total_libros,
        total_usuarios=total_usuarios,
        total_prestamos=total_prestamos,
        prestamos_recientes=prestamos_recientes,
        top_usuarios=top_usuarios,
        top_libros=top_libros,
    )


@app.route("/users")
def listar_usuarios():
    if resultado_redireccion := requerir_inicio_sesion():
        return resultado_redireccion
    if resultado_redireccion := requerir_administrador():
        return resultado_redireccion
    lista_usuarios = consultar_bd("SELECT * FROM usuarios ORDER BY name")
    return render_template("usuarios.html", users=lista_usuarios)


@app.route("/users/new", methods=["GET", "POST"])
def agregar_usuario():
    if resultado_redireccion := requerir_inicio_sesion():
        return resultado_redireccion
    if resultado_redireccion := requerir_administrador():
        return resultado_redireccion
    if request.method == "POST":
        ejecutar_bd(
            "INSERT INTO usuarios (username, password, role, name) VALUES (?, ?, ?, ?)",
            (
                request.form["username"].strip(),
                request.form["password"].strip(),
                request.form["role"],
                request.form["name"].strip(),
            ),
        )
        flash("Usuario agregado correctamente.", "success")
        return redirect(url_for("listar_usuarios"))
    return render_template("usuario_form.html", action="Crear", user=None)


@app.route("/users/edit/<int:user_id>", methods=["GET", "POST"])
def editar_usuario(user_id):
    if resultado_redireccion := requerir_inicio_sesion():
        return resultado_redireccion
    if resultado_redireccion := requerir_administrador():
        return resultado_redireccion
    usuario_item = obtener_usuario_por_id(user_id)
    if not usuario_item:
        flash("Usuario no encontrado.", "warning")
        return redirect(url_for("listar_usuarios"))
    if request.method == "POST":
        password = request.form.get("password", "").strip()
        if password:
            ejecutar_bd(
                "UPDATE usuarios SET username = ?, password = ?, role = ?, name = ? WHERE id = ?",
                (
                    request.form["username"].strip(),
                    password,
                    request.form["role"],
                    request.form["name"].strip(),
                    user_id,
                ),
            )
        else:
            ejecutar_bd(
                "UPDATE usuarios SET username = ?, role = ?, name = ? WHERE id = ?",
                (
                    request.form["username"].strip(),
                    request.form["role"],
                    request.form["name"].strip(),
                    user_id,
                ),
            )
        flash("Usuario actualizado correctamente.", "success")
        return redirect(url_for("listar_usuarios"))
    return render_template("usuario_form.html", action="Editar", user=usuario_item)


@app.route("/users/delete/<int:user_id>")
def eliminar_usuario(user_id):
    if resultado_redireccion := requerir_inicio_sesion():
        return resultado_redireccion
    if resultado_redireccion := requerir_administrador():
        return resultado_redireccion
    ejecutar_bd("DELETE FROM usuarios WHERE id = ?", (user_id,))
    flash("Usuario eliminado.", "info")
    return redirect(url_for("listar_usuarios"))


@app.route("/categories")
def listar_categorias():
    if resultado_redireccion := requerir_inicio_sesion():
        return resultado_redireccion
    lista_categorias = consultar_bd("SELECT * FROM categorias ORDER BY name")
    return render_template("categorias.html", categories=lista_categorias)


@app.route("/categories/new", methods=["GET", "POST"])
def agregar_categoria():
    if resultado_redireccion := requerir_inicio_sesion():
        return resultado_redireccion
    if resultado_redireccion := requerir_administrador():
        return resultado_redireccion
    if request.method == "POST":
        ejecutar_bd(
            "INSERT INTO categorias (name) VALUES (?)",
            (request.form["name"].strip(),),
        )
        flash("Categoría agregada correctamente.", "success")
        return redirect(url_for("listar_categorias"))
    return render_template("categoria_form.html", action="Crear", category=None)


@app.route("/categories/edit/<int:category_id>", methods=["GET", "POST"])
def editar_categoria(category_id):
    if resultado_redireccion := requerir_inicio_sesion():
        return resultado_redireccion
    if resultado_redireccion := requerir_administrador():
        return resultado_redireccion
    category = obtener_categoria(category_id)
    if not category:
        flash("Categoría no encontrada.", "warning")
        return redirect(url_for("listar_categorias"))
    if request.method == "POST":
        ejecutar_bd(
            "UPDATE categorias SET name = ? WHERE id = ?",
            (request.form["name"].strip(), category_id),
        )
        flash("Categoría actualizada correctamente.", "success")
        return redirect(url_for("listar_categorias"))
    return render_template("categoria_form.html", action="Editar", category=category)


@app.route("/categories/delete/<int:category_id>")
def eliminar_categoria(category_id):
    if resultado_redireccion := requerir_inicio_sesion():
        return resultado_redireccion
    if resultado_redireccion := requerir_administrador():
        return resultado_redireccion
    associated = consultar_bd(
        "SELECT COUNT(*) AS total FROM libros WHERE category_id = ?",
        (category_id,),
        one=True,
    )
    if associated and associated["total"] > 0:
        flash("No se puede eliminar una categoría con libros asignados.", "warning")
        return redirect(url_for("listar_categorias"))
    ejecutar_bd("DELETE FROM categorias WHERE id = ?", (category_id,))
    flash("Categoría eliminada.", "info")
    return redirect(url_for("listar_categorias"))


@app.route("/books")
def listar_libros():
    if resultado_redireccion := requerir_inicio_sesion():
        return resultado_redireccion
    query = request.args.get("q", "")
    category_id = request.args.get("category_id")
    category_id = int(category_id) if category_id and category_id.isdigit() else None
    libros_filtrados = buscar_libros(query, category_id)
    lista_categorias = consultar_bd("SELECT * FROM categorias ORDER BY name")
    return render_template(
        "libros.html",
        books=libros_filtrados,
        categories=lista_categorias,
        query=query,
        selected_category=category_id,
    )


@app.route("/books/new", methods=["GET", "POST"])
def agregar_libro():
    if resultado_redireccion := requerir_inicio_sesion():
        return resultado_redireccion
    if resultado_redireccion := requerir_administrador():
        return resultado_redireccion
    if request.method == "POST":
        total = int(request.form["total"])
        ejecutar_bd(
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
        return redirect(url_for("listar_libros"))
    lista_categorias = consultar_bd("SELECT * FROM categorias ORDER BY name")
    return render_template("libro_form.html", action="Crear", book=None, categories=lista_categorias)


@app.route("/books/edit/<int:book_id>", methods=["GET", "POST"])
def editar_libro(book_id):
    if resultado_redireccion := requerir_inicio_sesion():
        return resultado_redireccion
    if resultado_redireccion := requerir_administrador():
        return resultado_redireccion
    book = obtener_libro(book_id)
    if not book:
        flash("Libro no encontrado.", "warning")
        return redirect(url_for("listar_libros"))
    if request.method == "POST":
        nuevo_total = int(request.form["total"])
        available = max(book["available"] + (nuevo_total - book["total"]), 0)
        ejecutar_bd(
            "UPDATE libros SET title = ?, author = ?, category_id = ?, available = ?, total = ?, description = ? WHERE id = ?",
            (
                request.form["title"].strip(),
                request.form["author"].strip(),
                int(request.form["category_id"]),
                available,
                nuevo_total,
                request.form["description"].strip(),
                book_id,
            ),
        )
        flash("Libro actualizado correctamente.", "success")
        return redirect(url_for("listar_libros"))
    lista_categorias = consultar_bd("SELECT * FROM categorias ORDER BY name")
    return render_template("libro_form.html", action="Editar", book=book, categories=lista_categorias)


@app.route("/books/delete/<int:book_id>")
def eliminar_libro(book_id):
    if resultado_redireccion := requerir_inicio_sesion():
        return resultado_redireccion
    if resultado_redireccion := requerir_administrador():
        return resultado_redireccion
    prestamos_activos = consultar_bd(
        "SELECT COUNT(*) AS total FROM prestamos WHERE book_id = ? AND returned = 0",
        (book_id,),
        one=True,
    )
    if prestamos_activos and prestamos_activos["total"] > 0:
        flash("No se puede eliminar un libro con préstamos activos.", "warning")
        return redirect(url_for("listar_libros"))
    ejecutar_bd("DELETE FROM libros WHERE id = ?", (book_id,))
    flash("Libro eliminado.", "info")
    return redirect(url_for("listar_libros"))


@app.route("/loans", methods=["GET", "POST"])
def gestionar_prestamos():
    if resultado_redireccion := requerir_inicio_sesion():
        return resultado_redireccion
    user = usuario_actual()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "borrow":
            book_id = int(request.form["book_id"])
            book = obtener_libro(book_id)
            if book and book["available"] > 0:
                ejecutar_bd(
                    "INSERT INTO prestamos (book_id, user_id, start_date, returned) VALUES (?, ?, ?, ?)",
                    (book_id, user["id"], datetime.now(), 0),
                )
                ejecutar_bd(
                    "UPDATE libros SET available = available - 1 WHERE id = ?",
                    (book_id,),
                )
                flash("Préstamo registrado correctamente.", "success")
            else:
                flash("No hay ejemplares disponibles para préstamo.", "danger")
        elif action == "return":
            loan_id = int(request.form["loan_id"])
            loan = consultar_bd("SELECT * FROM prestamos WHERE id = ?", (loan_id,), one=True)
            if loan and not loan["returned"]:
                ejecutar_bd(
                    "UPDATE prestamos SET returned = 1, return_date = ? WHERE id = ?",
                    (datetime.now(), loan_id),
                )
                ejecutar_bd(
                    "UPDATE libros SET available = available + 1 WHERE id = ?",
                    (loan["book_id"],),
                )
                flash("Devolución registrada correctamente.", "success")
        return redirect(url_for("gestionar_prestamos"))

    if user["role"] == "admin":
        prestamos_visibles = consultar_bd("SELECT * FROM prestamos ORDER BY start_date DESC")
    else:
        prestamos_visibles = consultar_bd(
            "SELECT * FROM prestamos WHERE user_id = ? ORDER BY start_date DESC",
            (user["id"],),
        )
    return render_template(
        "prestamos.html",
        loans=prestamos_visibles,
        books=consultar_bd("SELECT * FROM libros ORDER BY title"),
        users=consultar_bd("SELECT * FROM usuarios ORDER BY name"),
        user=user,
    )


@app.route("/reportes")
def reportes():
    if resultado_redireccion := requerir_inicio_sesion():
        return resultado_redireccion
    if resultado_redireccion := requerir_administrador():
        return resultado_redireccion
    top_usuarios = consultar_bd(
        "SELECT TOP 5 u.id, u.name, u.role, COUNT(p.id) AS loan_count "
        "FROM usuarios u "
        "LEFT JOIN prestamos p ON p.user_id = u.id "
        "GROUP BY u.id, u.name, u.role "
        "ORDER BY loan_count DESC"
    )
    top_libros = consultar_bd(
        "SELECT TOP 5 l.id, l.title, l.author, l.category_id, l.available, l.total, COUNT(p.id) AS loan_count "
        "FROM libros l "
        "LEFT JOIN prestamos p ON p.book_id = l.id "
        "GROUP BY l.id, l.title, l.author, l.category_id, l.available, l.total "
        "ORDER BY loan_count DESC"
    )
    resumen_fechas = prestamos_por_fecha()
    return render_template(
        "reportes.html",
        top_usuarios=top_usuarios,
        top_libros=top_libros,
        resumen_fechas=resumen_fechas,
    )


@app.context_processor
def inyectar_usuario():
    user = usuario_actual()
    return {
        "usuario_actual": user,
        "es_admin": user["role"] == "admin" if user else False,
        "categorias": consultar_bd("SELECT * FROM categorias ORDER BY name"),
        "obtener_categoria": obtener_categoria,
        "contar_prestamos_usuario": contar_prestamos_usuario,
        "contar_prestamos_libro": contar_prestamos_libro,
    }


@app.errorhandler(Exception)
def manejar_excepcion(excepcion):
    if isinstance(excepcion, HTTPException):
        return excepcion
    logging.exception("Unhandled exception")
    return f"<h1>Internal Server Error</h1><pre>{str(excepcion)}</pre>", 500


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=False,
    )
