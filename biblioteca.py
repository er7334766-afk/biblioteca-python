from datetime import datetime
import logging
import os

import pyodbc
from flask import Flask, flash, redirect, render_template, request, session, url_for

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


def get_sql_server_driver():
    candidate_names = [
        "ODBC Driver 18 for SQL Server",
        "ODBC Driver 17 for SQL Server",
        "ODBC Driver 13 for SQL Server",
        "SQL Server",
        "FreeTDS",
    ]
    installed = [d for d in pyodbc.drivers()]
    for want in candidate_names:
        match = next((d for d in installed if d.lower() == want.lower()), None)
        if match:
            return match
    return None


def normalize_connection_string(connection_string: str) -> str:
    cs = connection_string.strip()
    if "User ID=" in cs and "UID=" not in cs:
        cs = cs.replace("User ID=", "UID=")
    if "Password=" in cs and "PWD=" not in cs:
        cs = cs.replace("Password=", "PWD=")
    if "Trusted_Connection" not in cs:
        if not cs.endswith(";"):
            cs += ";"
        cs += "Trusted_Connection=no;"
    return cs


def replace_driver_name(connection_string: str, driver_name: str) -> str:
    import re

    if re.search(r"(?i)DRIVER=\{[^}]+\}", connection_string):
        return re.sub(r"(?i)DRIVER=\{[^}]+\}", f"DRIVER={{{driver_name}}}", connection_string)
    if re.search(r"(?i)Driver=[^;]+", connection_string):
        return re.sub(r"(?i)Driver=[^;]+", f"Driver={driver_name}", connection_string)
    if not connection_string.endswith(";"):
        connection_string += ";"
    return f"DRIVER={{{driver_name}}};{connection_string}"


def get_db_connection():
    if not AZURE_SQL_CONNECTION_STRING:
        raise RuntimeError(
            "Configure AZURE_SQL_CONNECTION_STRING with the correct Azure SQL credentials."
        )

    connection_string = normalize_connection_string(AZURE_SQL_CONNECTION_STRING)
    driver_name = get_sql_server_driver()
    if driver_name:
        connection_string = replace_driver_name(connection_string, driver_name)
    else:
        installed = [d for d in pyodbc.drivers()]
        raise RuntimeError(
            "No se encontró un driver ODBC compatible para Azure SQL en el entorno. "
            f"Drivers instalados: {installed}. "
            "Instala 'ODBC Driver 18 for SQL Server' o 'ODBC Driver 17 for SQL Server', "
            "o despliega la app en un contenedor con el driver instalado."
        )

    try:
        return pyodbc.connect(connection_string, autocommit=False)
    except pyodbc.Error as exc:
        installed = [d for d in pyodbc.drivers()]
        raise RuntimeError(
            "Error al conectar con Azure SQL. "
            f"Driver usado: {driver_name}. "
            f"Drivers instalados: {installed}. "
            f"Detalle: {exc}"
        ) from exc


def query_db(sql, params=None, one=False):
    connection = get_db_connection()
    cursor = connection.cursor()
    cursor.execute(sql, params or ())
    columns = [column[0] for column in cursor.description] if cursor.description else []
    rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
    cursor.close()
    connection.close()
    return rows[0] if one and rows else rows


def execute_db(sql, params=None):
    connection = get_db_connection()
    cursor = connection.cursor()
    cursor.execute(sql, params or ())
    connection.commit()
    last_id = None
    try:
        cursor.execute("SELECT SCOPE_IDENTITY()")
        row = cursor.fetchone()
        if row:
            last_id = row[0]
    except Exception:
        last_id = None
    cursor.close()
    connection.close()
    return last_id


def current_user():
    user_id = session.get("user_id")
    return get_user_by_id(user_id) if user_id else None


def require_login():
    if not session.get("user_id"):
        return redirect(url_for("login"))
    return None


def require_admin():
    user = current_user()
    if not user or user.get("role") != "admin":
        flash("Acceso denegado. Solo administradores.", "warning")
        return redirect(url_for("dashboard"))
    return None


def get_user_by_username(username):
    return query_db("SELECT * FROM usuarios WHERE username = ?", (username,), one=True)


def get_user_by_id(user_id):
    return query_db("SELECT * FROM usuarios WHERE id = ?", (user_id,), one=True)


def get_book(book_id):
    return query_db("SELECT * FROM libros WHERE id = ?", (book_id,), one=True)


def get_category(category_id):
    return query_db("SELECT * FROM categorias WHERE id = ?", (category_id,), one=True)


def search_books(query, category_id):
    sql = "SELECT * FROM libros"
    filters = []
    params = []
    query_text = (query or "").strip().lower()

    if query_text:
        filters.append("(LOWER(title) LIKE ? OR LOWER(author) LIKE ?)")
        like_value = f"%{query_text}%"
        params.extend([like_value, like_value])

    if category_id:
        filters.append("category_id = ?")
        params.append(category_id)

    if filters:
        sql += " WHERE " + " AND ".join(filters)

    sql += " ORDER BY title"
    return query_db(sql, params)


def book_loans_count(book_id):
    result = query_db(
        "SELECT COUNT(*) AS total FROM prestamos WHERE book_id = ?", (book_id,), one=True
    )
    return result["total"] if result else 0


def user_loans_count(user_id):
    result = query_db(
        "SELECT COUNT(*) AS total FROM prestamos WHERE user_id = ?", (user_id,), one=True
    )
    return result["total"] if result else 0


def loans_by_date():
    rows = query_db(
        "SELECT CONVERT(date, start_date) AS fecha, COUNT(*) AS total FROM prestamos GROUP BY CONVERT(date, start_date) ORDER BY fecha DESC"
    )
    summary = []
    for row in rows:
        fecha = row["fecha"]
        if hasattr(fecha, "strftime"):
            fecha_str = fecha.strftime("%Y-%m-%d")
        else:
            fecha_str = str(fecha)
        summary.append((fecha_str, row["total"]))
    return summary


@app.route("/")
def index():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        user = get_user_by_username(username)
        if user and user["password"] == password:
            session["user_id"] = user["id"]
            flash(f"Bienvenido {user['name']}", "success")
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
    user = current_user()
    total_books = query_db("SELECT COUNT(*) AS total FROM libros", one=True)["total"]
    total_users = query_db("SELECT COUNT(*) AS total FROM usuarios", one=True)["total"]
    total_loans = query_db("SELECT COUNT(*) AS total FROM prestamos WHERE returned = 0", one=True)["total"]
    recent_loans = query_db("SELECT TOP 5 * FROM prestamos ORDER BY start_date DESC")
    top_users = query_db(
        "SELECT TOP 5 u.id, u.name, u.role, COUNT(p.id) AS loan_count "
        "FROM usuarios u "
        "LEFT JOIN prestamos p ON p.user_id = u.id "
        "GROUP BY u.id, u.name, u.role "
        "ORDER BY loan_count DESC"
    )
    top_books = query_db(
        "SELECT TOP 5 l.id, l.title, l.author, l.category_id, l.available, l.total, COUNT(p.id) AS loan_count "
        "FROM libros l "
        "LEFT JOIN prestamos p ON p.book_id = l.id "
        "GROUP BY l.id, l.title, l.author, l.category_id, l.available, l.total "
        "ORDER BY loan_count DESC"
    )
    return render_template(
        "panel.html",
        user=user,
        total_books=total_books,
        total_users=total_users,
        total_loans=total_loans,
        recent_loans=recent_loans,
        top_users=top_users,
        top_books=top_books,
    )


@app.route("/users")
def list_users():
    if redirect_result := require_login():
        return redirect_result
    if redirect_result := require_admin():
        return redirect_result
    users_list = query_db("SELECT * FROM usuarios ORDER BY name")
    return render_template("usuarios.html", users=users_list)


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
    user_item = get_user_by_id(user_id)
    if not user_item:
        flash("Usuario no encontrado.", "warning")
        return redirect(url_for("list_users"))
    if request.method == "POST":
        password = request.form.get("password", "").strip()
        if password:
            execute_db(
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
    return render_template("usuario_form.html", action="Editar", user=user_item)


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
    categories_list = query_db("SELECT * FROM categorias ORDER BY name")
    return render_template("categorias.html", categories=categories_list)


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
    category = get_category(category_id)
    if not category:
        flash("Categoría no encontrada.", "warning")
        return redirect(url_for("list_categories"))
    if request.method == "POST":
        execute_db(
            "UPDATE categorias SET name = ? WHERE id = ?",
            (request.form["name"].strip(), category_id),
        )
        flash("Categoría actualizada correctamente.", "success")
        return redirect(url_for("list_categories"))
    return render_template("categoria_form.html", action="Editar", category=category)


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
    query = request.args.get("q", "")
    category_id = request.args.get("category_id")
    category_id = int(category_id) if category_id and category_id.isdigit() else None
    filtered_books = search_books(query, category_id)
    categories_list = query_db("SELECT * FROM categorias ORDER BY name")
    return render_template(
        "libros.html",
        books=filtered_books,
        categories=categories_list,
        query=query,
        selected_category=category_id,
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
    categories_list = query_db("SELECT * FROM categorias ORDER BY name")
    return render_template("libro_form.html", action="Crear", book=None, categories=categories_list)


@app.route("/books/edit/<int:book_id>", methods=["GET", "POST"])
def edit_book(book_id):
    if redirect_result := require_login():
        return redirect_result
    if redirect_result := require_admin():
        return redirect_result
    book = get_book(book_id)
    if not book:
        flash("Libro no encontrado.", "warning")
        return redirect(url_for("list_books"))
    if request.method == "POST":
        new_total = int(request.form["total"])
        available = max(book["available"] + (new_total - book["total"]), 0)
        execute_db(
            "UPDATE libros SET title = ?, author = ?, category_id = ?, available = ?, total = ?, description = ? WHERE id = ?",
            (
                request.form["title"].strip(),
                request.form["author"].strip(),
                int(request.form["category_id"]),
                available,
                new_total,
                request.form["description"].strip(),
                book_id,
            ),
        )
        flash("Libro actualizado correctamente.", "success")
        return redirect(url_for("list_books"))
    categories_list = query_db("SELECT * FROM categorias ORDER BY name")
    return render_template("libro_form.html", action="Editar", book=book, categories=categories_list)


@app.route("/books/delete/<int:book_id>")
def delete_book(book_id):
    if redirect_result := require_login():
        return redirect_result
    if redirect_result := require_admin():
        return redirect_result
    active_loans = query_db(
        "SELECT COUNT(*) AS total FROM prestamos WHERE book_id = ? AND returned = 0",
        (book_id,),
        one=True,
    )
    if active_loans and active_loans["total"] > 0:
        flash("No se puede eliminar un libro con préstamos activos.", "warning")
        return redirect(url_for("list_books"))
    execute_db("DELETE FROM libros WHERE id = ?", (book_id,))
    flash("Libro eliminado.", "info")
    return redirect(url_for("list_books"))


@app.route("/loans", methods=["GET", "POST"])
def manage_loans():
    if redirect_result := require_login():
        return redirect_result
    user = current_user()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "borrow":
            book_id = int(request.form["book_id"])
            book = get_book(book_id)
            if book and book["available"] > 0:
                execute_db(
                    "INSERT INTO prestamos (book_id, user_id, start_date, returned) VALUES (?, ?, ?, ?)",
                    (book_id, user["id"], datetime.now(), 0),
                )
                execute_db(
                    "UPDATE libros SET available = available - 1 WHERE id = ?",
                    (book_id,),
                )
                flash("Préstamo registrado correctamente.", "success")
            else:
                flash("No hay ejemplares disponibles para préstamo.", "danger")
        elif action == "return":
            loan_id = int(request.form["loan_id"])
            loan = query_db("SELECT * FROM prestamos WHERE id = ?", (loan_id,), one=True)
            if loan and not loan["returned"]:
                execute_db(
                    "UPDATE prestamos SET returned = 1, return_date = ? WHERE id = ?",
                    (datetime.now(), loan_id),
                )
                execute_db(
                    "UPDATE libros SET available = available + 1 WHERE id = ?",
                    (loan["book_id"],),
                )
                flash("Devolución registrada correctamente.", "success")
        return redirect(url_for("manage_loans"))

    if user["role"] == "admin":
        visible_loans = query_db("SELECT * FROM prestamos ORDER BY start_date DESC")
    else:
        visible_loans = query_db(
            "SELECT * FROM prestamos WHERE user_id = ? ORDER BY start_date DESC",
            (user["id"],),
        )
    return render_template(
        "prestamos.html",
        loans=visible_loans,
        books=query_db("SELECT * FROM libros ORDER BY title"),
        users=query_db("SELECT * FROM usuarios ORDER BY name"),
        user=user,
    )


@app.route("/reports")
def reports():
    if redirect_result := require_login():
        return redirect_result
    if redirect_result := require_admin():
        return redirect_result
    top_users = query_db(
        "SELECT TOP 5 u.id, u.name, u.role, COUNT(p.id) AS loan_count "
        "FROM usuarios u "
        "LEFT JOIN prestamos p ON p.user_id = u.id "
        "GROUP BY u.id, u.name, u.role "
        "ORDER BY loan_count DESC"
    )
    top_books = query_db(
        "SELECT TOP 5 l.id, l.title, l.author, l.category_id, l.available, l.total, COUNT(p.id) AS loan_count "
        "FROM libros l "
        "LEFT JOIN prestamos p ON p.book_id = l.id "
        "GROUP BY l.id, l.title, l.author, l.category_id, l.available, l.total "
        "ORDER BY loan_count DESC"
    )
    date_summary = loans_by_date()
    return render_template(
        "reportes.html",
        top_users=top_users,
        top_books=top_books,
        date_summary=date_summary,
    )


@app.context_processor
def inject_user():
    user = current_user()
    return {
        "current_user": user,
        "is_admin": user["role"] == "admin" if user else False,
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
