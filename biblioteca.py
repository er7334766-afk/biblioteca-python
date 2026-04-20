from datetime import datetime
import logging
import os

import pyodbc
from flask import Flask, flash, redirect, render_template, request, session, url_for

app = Flask(__name__)
app.secret_key = "clave_de_prueba_cambiar"

CADENA_CONEXION_AZURE_SQL_POR_DEFECTO = (
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
    CADENA_CONEXION_AZURE_SQL_POR_DEFECTO,
)


def obtener_controlador_sql_server():
    nombres_candidatos = [
        "ODBC Driver 18 for SQL Server",
        "ODBC Driver 17 for SQL Server",
        "ODBC Driver 13 for SQL Server",
        "SQL Server",
        "FreeTDS",
    ]
    installed = [d for d in pyodbc.drivers()]
    for want in nombres_candidatos:
        match = next((d for d in installed if d.lower() == want.lower()), None)
        if match:
            return match
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


def reemplazar_nombre_controlador(cadena_conexion: str, nombre_controlador: str) -> str:
    import re

    if re.search(r"(?i)DRIVER=\{[^}]+\}", cadena_conexion):
        return re.sub(r"(?i)DRIVER=\{[^}]+\}", f"DRIVER={{{nombre_controlador}}}", cadena_conexion)
    if re.search(r"(?i)Driver=[^;]+", cadena_conexion):
        return re.sub(r"(?i)Driver=[^;]+", f"Driver={nombre_controlador}", cadena_conexion)
    if not cadena_conexion.endswith(";"):
        cadena_conexion += ";"
    return f"DRIVER={{{nombre_controlador}}};{cadena_conexion}"


def obtener_conexion_bd():
    if not CADENA_CONEXION_AZURE_SQL:
        raise RuntimeError(
            "Configure AZURE_SQL_CONNECTION_STRING with the correct Azure SQL credentials."
        )

    cadena_conexion = normalizar_cadena_conexion(CADENA_CONEXION_AZURE_SQL)
    nombre_controlador = obtener_controlador_sql_server()
    if nombre_controlador:
        cadena_conexion = reemplazar_nombre_controlador(cadena_conexion, nombre_controlador)
    else:
        installed = [d for d in pyodbc.drivers()]
        raise RuntimeError(
            "No se encontró un driver ODBC compatible para Azure SQL en el entorno. "
            f"Drivers instalados: {installed}. "
            "Instala 'ODBC Driver 18 for SQL Server' o 'ODBC Driver 17 for SQL Server', "
            "o despliega la app en un contenedor con el driver instalado."
        )

    try:
        return pyodbc.connect(cadena_conexion, autocommit=False)
    except pyodbc.Error as exc:
        installed = [d for d in pyodbc.drivers()]
        raise RuntimeError(
            "Error al conectar con Azure SQL. "
            f"Driver usado: {nombre_controlador}. "
            f"Drivers instalados: {installed}. "
            f"Detalle: {exc}"
        ) from exc


def consultar_bd(consulta_sql, parametros=None, una_sola_fila=False):
    conexion = obtener_conexion_bd()
    cursor = conexion.cursor()
    cursor.execute(consulta_sql, parametros or ())
    columnas = [columna[0] for columna in cursor.description] if cursor.description else []
    filas = [dict(zip(columnas, fila)) for fila in cursor.fetchall()]
    cursor.close()
    conexion.close()
    return filas[0] if una_sola_fila and filas else filas


def ejecutar_bd(consulta_sql, parametros=None):
    conexion = obtener_conexion_bd()
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


def usuario_actual():
    id_usuario = session.get("id_usuario")
    return obtener_usuario_por_id(id_usuario) if id_usuario else None


def requerir_inicio_sesion():
    if not session.get("id_usuario"):
        return redirect(url_for("iniciar_sesion"))
    return None


def requerir_administrador():
    usuario = usuario_actual()
    if not usuario or usuario.get("role") != "admin":
        flash("Acceso denegado. Solo administradores.", "warning")
        return redirect(url_for("panel"))
    return None


def obtener_usuario_por_nombre_usuario(nombre_usuario):
    return consultar_bd(
        "SELECT * FROM usuarios WHERE username = ?",
        (nombre_usuario,),
        una_sola_fila=True,
    )


def obtener_usuario_por_id(id_usuario):
    return consultar_bd("SELECT * FROM usuarios WHERE id = ?", (id_usuario,), una_sola_fila=True)


def obtener_libro(id_libro):
    return consultar_bd("SELECT * FROM libros WHERE id = ?", (id_libro,), una_sola_fila=True)


def obtener_categoria(id_categoria):
    return consultar_bd("SELECT * FROM categorias WHERE id = ?", (id_categoria,), una_sola_fila=True)


def buscar_libros(texto_consulta, id_categoria):
    consulta_sql = "SELECT * FROM libros"
    filtros = []
    parametros = []
    texto_busqueda = (texto_consulta or "").strip().lower()

    if texto_busqueda:
        filtros.append("(LOWER(title) LIKE ? OR LOWER(author) LIKE ?)")
        valor_like = f"%{texto_busqueda}%"
        parametros.extend([valor_like, valor_like])

    if id_categoria:
        filtros.append("category_id = ?")
        parametros.append(id_categoria)

    if filtros:
        consulta_sql += " WHERE " + " AND ".join(filtros)

    consulta_sql += " ORDER BY title"
    return consultar_bd(consulta_sql, parametros)


def contar_prestamos_libro(id_libro):
    resultado = consultar_bd(
        "SELECT COUNT(*) AS total FROM prestamos WHERE book_id = ?",
        (id_libro,),
        una_sola_fila=True,
    )
    return resultado["total"] if resultado else 0


def contar_prestamos_usuario(id_usuario):
    resultado = consultar_bd(
        "SELECT COUNT(*) AS total FROM prestamos WHERE user_id = ?",
        (id_usuario,),
        una_sola_fila=True,
    )
    return resultado["total"] if resultado else 0


def prestamos_por_fecha():
    filas = consultar_bd(
        "SELECT CONVERT(date, start_date) AS fecha, COUNT(*) AS total FROM prestamos GROUP BY CONVERT(date, start_date) ORDER BY fecha DESC"
    )
    resumen = []
    for fila in filas:
        fecha = fila["fecha"]
        if hasattr(fecha, "strftime"):
            fecha_str = fecha.strftime("%Y-%m-%d")
        else:
            fecha_str = str(fecha)
        resumen.append((fecha_str, fila["total"]))
    return resumen


@app.route("/")
def inicio():
    if session.get("id_usuario"):
        return redirect(url_for("panel"))
    return redirect(url_for("iniciar_sesion"))


@app.route("/login", methods=["GET", "POST"])
def iniciar_sesion():
    if request.method == "POST":
        nombre_usuario = request.form.get("username", "").strip()
        contrasena = request.form.get("password", "").strip()
        usuario = obtener_usuario_por_nombre_usuario(nombre_usuario)
        if usuario and usuario["password"] == contrasena:
            session["id_usuario"] = usuario["id"]
            flash(f"Bienvenido {usuario['name']}", "success")
            return redirect(url_for("panel"))
        flash("Usuario o contraseña inválidos.", "danger")
    return render_template("inicio_sesion.html")


@app.route("/logout")
def cerrar_sesion():
    session.clear()
    flash("Has cerrado sesión correctamente.", "info")
    return redirect(url_for("iniciar_sesion"))


@app.route("/dashboard")
def panel():
    if resultado_redireccion := requerir_inicio_sesion():
        return resultado_redireccion
    usuario = usuario_actual()
    total_libros = consultar_bd("SELECT COUNT(*) AS total FROM libros", una_sola_fila=True)["total"]
    total_usuarios = consultar_bd("SELECT COUNT(*) AS total FROM usuarios", una_sola_fila=True)["total"]
    total_prestamos = consultar_bd(
        "SELECT COUNT(*) AS total FROM prestamos WHERE returned = 0",
        una_sola_fila=True,
    )["total"]
    prestamos_recientes = consultar_bd("SELECT TOP 5 * FROM prestamos ORDER BY start_date DESC")
    usuarios_top = consultar_bd(
        "SELECT TOP 5 u.id, u.name, u.role, COUNT(p.id) AS loan_count "
        "FROM usuarios u "
        "LEFT JOIN prestamos p ON p.user_id = u.id "
        "GROUP BY u.id, u.name, u.role "
        "ORDER BY loan_count DESC"
    )
    libros_top = consultar_bd(
        "SELECT TOP 5 l.id, l.title, l.author, l.category_id, l.available, l.total, COUNT(p.id) AS loan_count "
        "FROM libros l "
        "LEFT JOIN prestamos p ON p.book_id = l.id "
        "GROUP BY l.id, l.title, l.author, l.category_id, l.available, l.total "
        "ORDER BY loan_count DESC"
    )
    return render_template(
        "panel.html",
        usuario=usuario,
        total_libros=total_libros,
        total_usuarios=total_usuarios,
        total_prestamos=total_prestamos,
        prestamos_recientes=prestamos_recientes,
        usuarios_top=usuarios_top,
        libros_top=libros_top,
    )


@app.route("/users")
def listar_usuarios():
    if resultado_redireccion := requerir_inicio_sesion():
        return resultado_redireccion
    if resultado_redireccion := requerir_administrador():
        return resultado_redireccion
    lista_usuarios = consultar_bd("SELECT * FROM usuarios ORDER BY name")
    return render_template("usuarios.html", usuarios=lista_usuarios)


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
    return render_template("usuario_form.html", action="Crear", usuario=None)


@app.route("/users/edit/<int:id_usuario>", methods=["GET", "POST"])
def editar_usuario(id_usuario):
    if resultado_redireccion := requerir_inicio_sesion():
        return resultado_redireccion
    if resultado_redireccion := requerir_administrador():
        return resultado_redireccion
    usuario_item = obtener_usuario_por_id(id_usuario)
    if not usuario_item:
        flash("Usuario no encontrado.", "warning")
        return redirect(url_for("listar_usuarios"))
    if request.method == "POST":
        contrasena = request.form.get("password", "").strip()
        if contrasena:
            ejecutar_bd(
                "UPDATE usuarios SET username = ?, password = ?, role = ?, name = ? WHERE id = ?",
                (
                    request.form["username"].strip(),
                    contrasena,
                    request.form["role"],
                    request.form["name"].strip(),
                    id_usuario,
                ),
            )
        else:
            ejecutar_bd(
                "UPDATE usuarios SET username = ?, role = ?, name = ? WHERE id = ?",
                (
                    request.form["username"].strip(),
                    request.form["role"],
                    request.form["name"].strip(),
                    id_usuario,
                ),
            )
        flash("Usuario actualizado correctamente.", "success")
        return redirect(url_for("listar_usuarios"))
    return render_template("usuario_form.html", action="Editar", usuario=usuario_item)


@app.route("/users/delete/<int:id_usuario>")
def eliminar_usuario(id_usuario):
    if resultado_redireccion := requerir_inicio_sesion():
        return resultado_redireccion
    if resultado_redireccion := requerir_administrador():
        return resultado_redireccion
    ejecutar_bd("DELETE FROM usuarios WHERE id = ?", (id_usuario,))
    flash("Usuario eliminado.", "info")
    return redirect(url_for("listar_usuarios"))


@app.route("/categories")
def listar_categorias():
    if resultado_redireccion := requerir_inicio_sesion():
        return resultado_redireccion
    lista_categorias = consultar_bd("SELECT * FROM categorias ORDER BY name")
    return render_template("categorias.html", categorias=lista_categorias)


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
    return render_template("categoria_form.html", action="Crear", categoria=None)


@app.route("/categories/edit/<int:id_categoria>", methods=["GET", "POST"])
def editar_categoria(id_categoria):
    if resultado_redireccion := requerir_inicio_sesion():
        return resultado_redireccion
    if resultado_redireccion := requerir_administrador():
        return resultado_redireccion
    categoria = obtener_categoria(id_categoria)
    if not categoria:
        flash("Categoría no encontrada.", "warning")
        return redirect(url_for("listar_categorias"))
    if request.method == "POST":
        ejecutar_bd(
            "UPDATE categorias SET name = ? WHERE id = ?",
            (request.form["name"].strip(), id_categoria),
        )
        flash("Categoría actualizada correctamente.", "success")
        return redirect(url_for("listar_categorias"))
    return render_template("categoria_form.html", action="Editar", categoria=categoria)


@app.route("/categories/delete/<int:id_categoria>")
def eliminar_categoria(id_categoria):
    if resultado_redireccion := requerir_inicio_sesion():
        return resultado_redireccion
    if resultado_redireccion := requerir_administrador():
        return resultado_redireccion
    asociado = consultar_bd(
        "SELECT COUNT(*) AS total FROM libros WHERE category_id = ?",
        (id_categoria,),
        una_sola_fila=True,
    )
    if asociado and asociado["total"] > 0:
        flash("No se puede eliminar una categoría con libros asignados.", "warning")
        return redirect(url_for("listar_categorias"))
    ejecutar_bd("DELETE FROM categorias WHERE id = ?", (id_categoria,))
    flash("Categoría eliminada.", "info")
    return redirect(url_for("listar_categorias"))


@app.route("/books")
def listar_libros():
    if resultado_redireccion := requerir_inicio_sesion():
        return resultado_redireccion
    consulta = request.args.get("q", "")
    id_categoria = request.args.get("category_id")
    id_categoria = int(id_categoria) if id_categoria and id_categoria.isdigit() else None
    libros_filtrados = buscar_libros(consulta, id_categoria)
    lista_categorias = consultar_bd("SELECT * FROM categorias ORDER BY name")
    return render_template(
        "libros.html",
        libros=libros_filtrados,
        categorias=lista_categorias,
        consulta=consulta,
        categoria_seleccionada=id_categoria,
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
    return render_template("libro_form.html", action="Crear", libro=None, categorias=lista_categorias)


@app.route("/books/edit/<int:id_libro>", methods=["GET", "POST"])
def editar_libro(id_libro):
    if resultado_redireccion := requerir_inicio_sesion():
        return resultado_redireccion
    if resultado_redireccion := requerir_administrador():
        return resultado_redireccion
    libro = obtener_libro(id_libro)
    if not libro:
        flash("Libro no encontrado.", "warning")
        return redirect(url_for("listar_libros"))
    if request.method == "POST":
        nuevo_total = int(request.form["total"])
        disponibles = max(libro["available"] + (nuevo_total - libro["total"]), 0)
        ejecutar_bd(
            "UPDATE libros SET title = ?, author = ?, category_id = ?, available = ?, total = ?, description = ? WHERE id = ?",
            (
                request.form["title"].strip(),
                request.form["author"].strip(),
                int(request.form["category_id"]),
                disponibles,
                nuevo_total,
                request.form["description"].strip(),
                id_libro,
            ),
        )
        flash("Libro actualizado correctamente.", "success")
        return redirect(url_for("listar_libros"))
    lista_categorias = consultar_bd("SELECT * FROM categorias ORDER BY name")
    return render_template("libro_form.html", action="Editar", libro=libro, categorias=lista_categorias)


@app.route("/books/delete/<int:id_libro>")
def eliminar_libro(id_libro):
    if resultado_redireccion := requerir_inicio_sesion():
        return resultado_redireccion
    if resultado_redireccion := requerir_administrador():
        return resultado_redireccion
    prestamos_activos = consultar_bd(
        "SELECT COUNT(*) AS total FROM prestamos WHERE book_id = ? AND returned = 0",
        (id_libro,),
        una_sola_fila=True,
    )
    if prestamos_activos and prestamos_activos["total"] > 0:
        flash("No se puede eliminar un libro con préstamos activos.", "warning")
        return redirect(url_for("listar_libros"))
    ejecutar_bd("DELETE FROM libros WHERE id = ?", (id_libro,))
    flash("Libro eliminado.", "info")
    return redirect(url_for("listar_libros"))


@app.route("/loans", methods=["GET", "POST"])
def gestionar_prestamos():
    if resultado_redireccion := requerir_inicio_sesion():
        return resultado_redireccion
    usuario = usuario_actual()
    if request.method == "POST":
        accion = request.form.get("action")
        if accion == "borrow":
            id_libro = int(request.form["book_id"])
            libro = obtener_libro(id_libro)
            if libro and libro["available"] > 0:
                ejecutar_bd(
                    "INSERT INTO prestamos (book_id, user_id, start_date, returned) VALUES (?, ?, ?, ?)",
                    (id_libro, usuario["id"], datetime.now(), 0),
                )
                ejecutar_bd(
                    "UPDATE libros SET available = available - 1 WHERE id = ?",
                    (id_libro,),
                )
                flash("Préstamo registrado correctamente.", "success")
            else:
                flash("No hay ejemplares disponibles para préstamo.", "danger")
        elif accion == "return":
            id_prestamo = int(request.form["loan_id"])
            prestamo = consultar_bd(
                "SELECT * FROM prestamos WHERE id = ?",
                (id_prestamo,),
                una_sola_fila=True,
            )
            if prestamo and not prestamo["returned"]:
                ejecutar_bd(
                    "UPDATE prestamos SET returned = 1, return_date = ? WHERE id = ?",
                    (datetime.now(), id_prestamo),
                )
                ejecutar_bd(
                    "UPDATE libros SET available = available + 1 WHERE id = ?",
                    (prestamo["book_id"],),
                )
                flash("Devolución registrada correctamente.", "success")
        return redirect(url_for("gestionar_prestamos"))

    if usuario["role"] == "admin":
        prestamos_visibles = consultar_bd("SELECT * FROM prestamos ORDER BY start_date DESC")
    else:
        prestamos_visibles = consultar_bd(
            "SELECT * FROM prestamos WHERE user_id = ? ORDER BY start_date DESC",
            (usuario["id"],),
        )
    return render_template(
        "prestamos.html",
        prestamos=prestamos_visibles,
        libros=consultar_bd("SELECT * FROM libros ORDER BY title"),
        usuarios=consultar_bd("SELECT * FROM usuarios ORDER BY name"),
        usuario=usuario,
    )


@app.route("/reports")
def reportes():
    if resultado_redireccion := requerir_inicio_sesion():
        return resultado_redireccion
    if resultado_redireccion := requerir_administrador():
        return resultado_redireccion
    usuarios_top = consultar_bd(
        "SELECT TOP 5 u.id, u.name, u.role, COUNT(p.id) AS loan_count "
        "FROM usuarios u "
        "LEFT JOIN prestamos p ON p.user_id = u.id "
        "GROUP BY u.id, u.name, u.role "
        "ORDER BY loan_count DESC"
    )
    libros_top = consultar_bd(
        "SELECT TOP 5 l.id, l.title, l.author, l.category_id, l.available, l.total, COUNT(p.id) AS loan_count "
        "FROM libros l "
        "LEFT JOIN prestamos p ON p.book_id = l.id "
        "GROUP BY l.id, l.title, l.author, l.category_id, l.available, l.total "
        "ORDER BY loan_count DESC"
    )
    resumen_fechas = prestamos_por_fecha()
    return render_template(
        "reportes.html",
        usuarios_top=usuarios_top,
        libros_top=libros_top,
        resumen_fechas=resumen_fechas,
    )


@app.context_processor
def inyectar_usuario():
    usuario = usuario_actual()
    return {
        "usuario_actual": usuario,
        "es_administrador": usuario["role"] == "admin" if usuario else False,
        "categorias": consultar_bd("SELECT * FROM categorias ORDER BY name"),
        "obtener_categoria": obtener_categoria,
        "contar_prestamos_usuario": contar_prestamos_usuario,
        "contar_prestamos_libro": contar_prestamos_libro,
    }


@app.errorhandler(Exception)
def manejar_excepcion(exc):
    logging.exception("Unhandled exception")
    return f"<h1>Internal Server Error</h1><pre>{str(exc)}</pre>", 500


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=False,
    )
