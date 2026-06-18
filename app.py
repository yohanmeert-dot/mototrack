from flask import Flask, render_template, request, redirect, session, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import secrets
import os
import qrcode
import requests


app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "mototrack_secret_key")

database_url = os.environ.get("DATABASE_URL", "sqlite:///database.db")

if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


# =========================
# MODELOS DO BANCO
# =========================

class Driver(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    telefone = db.Column(db.String(30), nullable=False)
    senha = db.Column(db.String(255), nullable=False)
    ativo = db.Column(db.Boolean, default=True)
    criado_em = db.Column(db.DateTime, default=datetime.now)


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    numero_pedido = db.Column(db.String(50), nullable=False)
    cliente_nome = db.Column(db.String(120), nullable=False)
    cliente_email = db.Column(db.String(120))
    telefone = db.Column(db.String(30))
    endereco = db.Column(db.String(255), nullable=False)
    taxa_entrega = db.Column(db.Float, default=0)
    status = db.Column(db.String(30), default="PRONTO")
    qr_token = db.Column(db.String(120), unique=True, nullable=False)
    tracking_token = db.Column(db.String(120), unique=True, nullable=False)
    criado_em = db.Column(db.DateTime, default=datetime.now)


class Delivery(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("order.id"), nullable=False)
    driver_id = db.Column(db.Integer, db.ForeignKey("driver.id"), nullable=False)
    horario_saida = db.Column(db.DateTime, default=datetime.now)
    horario_entrega = db.Column(db.DateTime)
    status = db.Column(db.String(30), default="EM_ROTA")

    order = db.relationship("Order", backref="deliveries")
    driver = db.relationship("Driver", backref="deliveries")


class DeliveryRouteItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    delivery_id = db.Column(db.Integer, db.ForeignKey("delivery.id"), nullable=False)
    driver_id = db.Column(db.Integer, db.ForeignKey("driver.id"), nullable=False)
    order_id = db.Column(db.Integer, db.ForeignKey("order.id"), nullable=False)
    route_order = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(30), default="PENDENTE")
    criado_em = db.Column(db.DateTime, default=datetime.now)

    delivery = db.relationship("Delivery", backref="route_items")
    driver = db.relationship("Driver", backref="route_items")
    order = db.relationship("Order", backref="route_items")


class DriverLocation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    driver_id = db.Column(db.Integer, db.ForeignKey("driver.id"), nullable=False)
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    criado_em = db.Column(db.DateTime, default=datetime.now)

    driver = db.relationship("Driver", backref="locations")


class YampiOrder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    yampi_id = db.Column(db.String(100), unique=True, nullable=False)

    mototrack_order_id = db.Column(db.Integer, db.ForeignKey("order.id"))

    customer_name = db.Column(db.String(255))
    customer_phone = db.Column(db.String(100))
    customer_email = db.Column(db.String(255))
    customer_document = db.Column(db.String(100))
    customer_address = db.Column(db.Text)

    items_json = db.Column(db.JSON)

    total = db.Column(db.Float, default=0)
    delivery_fee = db.Column(db.Float, default=0)

    payment_status = db.Column(db.String(100))
    payment_method = db.Column(db.String(100))
    local_payment_method = db.Column(db.String(100))

    order_status = db.Column(db.String(100), default="novo")
    notes = db.Column(db.Text)

    raw_json = db.Column(db.JSON)

    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now)

    mototrack_order = db.relationship("Order", backref="yampi_order")


# =========================
# FUNÇÕES AUXILIARES
# =========================

def gerar_qrcode(order):
    pasta = "qr_codes"
    os.makedirs(pasta, exist_ok=True)

    base_url = os.environ.get("BASE_URL", "http://127.0.0.1:6061").rstrip("/")
    link = f"{base_url}/motoboy/scan/{order.qr_token}"

    img = qrcode.make(link)
    caminho = os.path.join(pasta, f"pedido_{order.id}.png")
    img.save(caminho)


def criar_item_rota(driver, order, entrega):
    ultima_rota = DeliveryRouteItem.query.filter_by(
        driver_id=driver.id,
        status="PENDENTE"
    ).order_by(DeliveryRouteItem.route_order.desc()).first()

    proxima_ordem = 1

    if ultima_rota:
        proxima_ordem = ultima_rota.route_order + 1

    rota_item = DeliveryRouteItem(
        delivery_id=entrega.id,
        driver_id=driver.id,
        order_id=order.id,
        route_order=proxima_ordem,
        status="PENDENTE"
    )

    db.session.add(rota_item)


def yampi_headers():
    return {
        "User-Token": os.environ.get("YAMPI_USER_TOKEN", ""),
        "User-Secret-Key": os.environ.get("YAMPI_SECRET_KEY", ""),
        "Content-Type": "application/json",
    }


def get_yampi_base_url():
    alias = os.environ.get("YAMPI_ALIAS", "").strip()
    return f"https://api.dooki.com.br/v2/{alias}"


def extract_text(value):
    if value is None:
        return ""

    if isinstance(value, str):
        return value

    if isinstance(value, (int, float)):
        return str(value)

    if isinstance(value, dict):
        return (
            value.get("formated_number")
            or value.get("formatted_number")
            or value.get("full_number")
            or value.get("number")
            or value.get("alias")
            or value.get("name")
            or value.get("status")
            or ""
        )

    return str(value)


def get_nested_data(value):
    if isinstance(value, dict):
        if isinstance(value.get("data"), dict):
            return value.get("data") or {}
        return value
    return {}


def get_float(value, default=0):
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def get_order_items_from_yampi(yampi_id):
    items = []

    try:
        items_url = f"{get_yampi_base_url()}/orders/{yampi_id}/items"
        items_response = requests.get(
            items_url,
            headers=yampi_headers(),
            timeout=20
        )

        if not items_response.ok:
            return items

        items_json = items_response.json()
        products_data = items_json.get("data", [])

        for product in products_data:
            quantity = product.get("quantity", 1)

            sku_data = get_nested_data(product.get("sku"))

            product_name = (
                sku_data.get("title")
                or sku_data.get("name")
                or product.get("name")
                or product.get("title")
                or "Produto"
            )

            price = get_float(product.get("price") or sku_data.get("price_sale") or 0)

            customizations = []
            customizations_data = product.get("customizations", [])

            if isinstance(customizations_data, dict):
                customizations_data = customizations_data.get("data", []) or []

            if not isinstance(customizations_data, list):
                customizations_data = []

            for customization in customizations_data:
                value = (
                    customization.get("value")
                    or customization.get("name")
                    or customization.get("title")
                    or customization.get("description")
                )

                if value:
                    customizations.append(str(value))

            items.append({
                "name": product_name,
                "quantity": quantity,
                "price": price,
                "customizations": customizations
            })

    except Exception as e:
        print("ERRO AO BUSCAR ITENS:", e)

    return items


# =========================
# ROTAS PRINCIPAIS
# =========================

@app.route("/")
def home():
    return redirect("/login")


@app.route("/__routes")
def debug_routes():
    """Rota de diagnóstico para conferir se o Render carregou a versão certa."""
    rotas = []

    for rule in app.url_map.iter_rules():
        rotas.append({
            "endpoint": rule.endpoint,
            "methods": sorted(list(rule.methods)),
            "rule": str(rule)
        })

    return jsonify(sorted(rotas, key=lambda item: item["rule"]))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        senha = request.form.get("senha")

        if email == "admin@mototrack.com" and senha == "123456":
            session["admin"] = True
            return redirect("/admin")

        return render_template("login.html", erro="E-mail ou senha inválidos")

    return render_template("login.html")

# =========================
# APIs DE ROTA DO APP
# =========================

def get_order_items_for_app(order_id):
    yampi_order = YampiOrder.query.filter_by(mototrack_order_id=order_id).first()

    if not yampi_order:
        return []

    return yampi_order.items_json or []


def get_yampi_info_for_app(order_id):
    yampi_order = YampiOrder.query.filter_by(mototrack_order_id=order_id).first()

    if not yampi_order:
        return None

    return {
        "yampi_id": yampi_order.yampi_id,
        "customer_document": yampi_order.customer_document,
        "payment_method": yampi_order.local_payment_method or yampi_order.payment_method,
        "payment_status": yampi_order.payment_status,
        "total": yampi_order.total,
        "delivery_fee": yampi_order.delivery_fee,
        "notes": yampi_order.notes,
        "items": yampi_order.items_json or []
    }


@app.route("/api/driver/route/<int:driver_id>", methods=["GET"])
def api_driver_route(driver_id):
    driver = Driver.query.filter_by(id=driver_id, ativo=True).first()

    if not driver:
        return jsonify({
            "success": False,
            "message": "Motoboy não encontrado ou inativo."
        }), 404

    route_items = DeliveryRouteItem.query.filter_by(
        driver_id=driver.id,
        status="PENDENTE"
    ).order_by(DeliveryRouteItem.route_order.asc()).all()

    route = []

    for item in route_items:
        order = item.order
        yampi_info = get_yampi_info_for_app(order.id)

        route.append({
            "route_item_id": item.id,
            "delivery_id": item.delivery_id,
            "order_id": order.id,
            "numero_pedido": order.numero_pedido,
            "route_order": item.route_order,
            "cliente_nome": order.cliente_nome,
            "cliente_email": order.cliente_email,
            "telefone": order.telefone,
            "endereco": order.endereco,
            "taxa_entrega": order.taxa_entrega,
            "status": order.status,
            "tracking_token": order.tracking_token,
            "items": yampi_info["items"] if yampi_info else [],
            "payment_method": yampi_info["payment_method"] if yampi_info else None,
            "payment_status": yampi_info["payment_status"] if yampi_info else None,
            "total": yampi_info["total"] if yampi_info else None,
            "notes": yampi_info["notes"] if yampi_info else None
        })

    ultima = DriverLocation.query.filter_by(
        driver_id=driver.id
    ).order_by(DriverLocation.id.desc()).first()

    return jsonify({
        "success": True,
        "driver": {
            "id": driver.id,
            "nome": driver.nome,
            "telefone": driver.telefone
        },
        "current_location": {
            "latitude": ultima.latitude if ultima else None,
            "longitude": ultima.longitude if ultima else None,
            "updated_at": ultima.criado_em.strftime("%H:%M:%S") if ultima else None
        },
        "route": route
    })


@app.route("/api/driver/order/<int:order_id>", methods=["GET"])
def api_driver_order_detail(order_id):
    order = Order.query.get_or_404(order_id)
    yampi_info = get_yampi_info_for_app(order.id)

    entrega = Delivery.query.filter_by(order_id=order.id).order_by(Delivery.id.desc()).first()

    return jsonify({
        "success": True,
        "order": {
            "id": order.id,
            "numero_pedido": order.numero_pedido,
            "cliente_nome": order.cliente_nome,
            "cliente_email": order.cliente_email,
            "telefone": order.telefone,
            "endereco": order.endereco,
            "taxa_entrega": order.taxa_entrega,
            "status": order.status,
            "tracking_token": order.tracking_token,
            "driver_name": entrega.driver.nome if entrega else None,
            "items": yampi_info["items"] if yampi_info else [],
            "payment_method": yampi_info["payment_method"] if yampi_info else None,
            "payment_status": yampi_info["payment_status"] if yampi_info else None,
            "total": yampi_info["total"] if yampi_info else None,
            "notes": yampi_info["notes"] if yampi_info else None
        }
    })

# =========================
# DRIVER WEB APP
# =========================

@app.route("/driver")
def driver_root():
    return redirect("/driver/login")


@app.route("/driver/login", methods=["GET", "POST"])
def driver_login_web():
    if request.method == "POST":
        telefone = request.form.get("telefone")
        senha = request.form.get("senha")

        driver = Driver.query.filter_by(telefone=telefone, ativo=True).first()

        if not driver or not check_password_hash(driver.senha, senha):
            return render_template(
                "driver_login.html",
                erro="Telefone ou senha inválidos."
            )

        session["driver_id"] = driver.id
        session["driver_name"] = driver.nome

        return redirect("/driver/home")

    return render_template("driver_login.html")


@app.route("/driver/home")
def driver_home_web():
    driver_id = session.get("driver_id")

    if not driver_id:
        return redirect("/driver/login")

    driver = Driver.query.get_or_404(driver_id)
    google_maps_api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "")

    return render_template(
        "driver_home.html",
        driver=driver,
        google_maps_api_key=google_maps_api_key
    )


@app.route("/driver/logout")
def driver_logout_web():
    session.pop("driver_id", None)
    session.pop("driver_name", None)

    return redirect("/driver/login")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.route("/admin")
def admin():
    if not session.get("admin"):
        return redirect("/login")

    drivers = Driver.query.order_by(Driver.id.desc()).all()
    orders = Order.query.order_by(Order.id.desc()).all()

    return render_template("admin.html", drivers=drivers, orders=orders)


# =========================
# MOTOBOYS
# =========================

@app.route("/motoboys/novo", methods=["POST"])
def novo_motoboy():
    if not session.get("admin"):
        return redirect("/login")

    novo = Driver(
        nome=request.form.get("nome"),
        telefone=request.form.get("telefone"),
        senha=generate_password_hash(request.form.get("senha")),
        ativo=True
    )

    db.session.add(novo)
    db.session.commit()

    return redirect("/admin")


@app.route("/motoboys/desativar/<int:id>")
def desativar_motoboy(id):
    if not session.get("admin"):
        return redirect("/login")

    driver = Driver.query.get_or_404(id)
    driver.ativo = False
    db.session.commit()

    return redirect("/admin")


@app.route("/motoboy/scan/<token>", methods=["GET", "POST"])
def scan_pedido(token):
    order = Order.query.filter_by(qr_token=token).first_or_404()
    drivers = Driver.query.filter_by(ativo=True).all()

    if request.method == "POST":
        driver_id = request.form.get("driver_id")
        driver = Driver.query.get_or_404(driver_id)

        entrega_existente = Delivery.query.filter_by(order_id=order.id).first()

        if entrega_existente:
            return render_template(
                "motoboy_scan.html",
                order=order,
                drivers=drivers,
                erro="Este pedido já saiu para entrega."
            )

        entrega = Delivery(
            order_id=order.id,
            driver_id=driver.id,
            horario_saida=datetime.now(),
            status="EM_ROTA"
        )

        order.status = "EM_ROTA"

        db.session.add(entrega)
        db.session.flush()

        criar_item_rota(driver, order, entrega)

        db.session.commit()

        return render_template(
            "motoboy_scan.html",
            order=order,
            drivers=drivers,
            sucesso=f"Pedido saiu com {driver.nome} às {entrega.horario_saida.strftime('%H:%M')}"
        )

    return render_template("motoboy_scan.html", order=order, drivers=drivers)


@app.route("/motoboy/app/<int:driver_id>")
def motoboy_app_teste(driver_id):
    driver = Driver.query.get_or_404(driver_id)
    return render_template("motoboy_app.html", driver=driver)


# =========================
# PEDIDOS MANUAIS / QR
# =========================

@app.route("/pedidos/novo", methods=["POST"])
def novo_pedido():
    if not session.get("admin"):
        return redirect("/login")

    qr_token = secrets.token_urlsafe(32)
    tracking_token = secrets.token_urlsafe(32)

    novo = Order(
        numero_pedido=request.form.get("numero_pedido"),
        cliente_nome=request.form.get("cliente_nome"),
        cliente_email=request.form.get("cliente_email"),
        telefone=request.form.get("telefone"),
        endereco=request.form.get("endereco"),
        taxa_entrega=get_float(request.form.get("taxa_entrega")),
        qr_token=qr_token,
        tracking_token=tracking_token,
        status="PRONTO"
    )

    db.session.add(novo)
    db.session.commit()

    gerar_qrcode(novo)

    return redirect("/admin")


@app.route("/pedido/<int:id>/qr")
def ver_qr(id):
    if not session.get("admin"):
        return redirect("/login")

    order = Order.query.get_or_404(id)
    qr_path = f"/qr_codes/pedido_{order.id}.png"

    return render_template("qr.html", order=order, qr_path=qr_path)


@app.route("/qr_codes/<filename>")
def servir_qrcode(filename):
    return send_from_directory("qr_codes", filename)


# =========================
# APIs DO APP DO MOTOBOY
# =========================

@app.route("/api/driver/login", methods=["POST"])
def api_driver_login():
    data = request.get_json(silent=True) or {}

    telefone = data.get("telefone")
    senha = data.get("senha")

    driver = Driver.query.filter_by(telefone=telefone, ativo=True).first()

    if not driver:
        return jsonify({
            "success": False,
            "message": "Motoboy não encontrado ou inativo."
        }), 401

    if not check_password_hash(driver.senha, senha):
        return jsonify({
            "success": False,
            "message": "Senha incorreta."
        }), 401

    return jsonify({
        "success": True,
        "driver_id": driver.id,
        "driver_name": driver.nome
    })


@app.route("/api/driver/scan", methods=["POST"])
def api_driver_scan():
    data = request.get_json(silent=True) or {}

    driver_id = data.get("driver_id")
    qr_token = data.get("qr_token")

    driver = Driver.query.filter_by(id=driver_id, ativo=True).first()
    order = Order.query.filter_by(qr_token=qr_token).first()

    if not driver:
        return jsonify({
            "success": False,
            "message": "Motoboy inválido."
        }), 400

    if not order:
        return jsonify({
            "success": False,
            "message": "Pedido não encontrado."
        }), 404

    entrega_existente = Delivery.query.filter_by(order_id=order.id).first()

    if entrega_existente:
        return jsonify({
            "success": False,
            "message": "Este pedido já saiu para entrega."
        }), 409

    entrega = Delivery(
        order_id=order.id,
        driver_id=driver.id,
        horario_saida=datetime.now(),
        status="EM_ROTA"
    )

    order.status = "EM_ROTA"

    db.session.add(entrega)
    db.session.flush()

    rota_item = criar_item_rota(driver, order, entrega)

    db.session.commit()

    return jsonify({
        "success": True,
        "message": "Pedido saiu para entrega.",
        "delivery_id": entrega.id,
        "order": {
            "id": order.id,
            "numero_pedido": order.numero_pedido,
            "cliente_nome": order.cliente_nome,
            "cliente_email": order.cliente_email,
            "telefone": order.telefone,
            "endereco": order.endereco,
            "taxa_entrega": order.taxa_entrega,
            "status": order.status,
            "tracking_token": order.tracking_token,
            "route_order": rota_item.route_order if rota_item else None,
            "items": get_order_items_for_app(order.id),
            "yampi_info": get_yampi_info_for_app(order.id)
        }
    })

@app.route("/api/driver/location", methods=["POST"])
def api_driver_location():
    data = request.get_json(silent=True) or {}

    driver_id = data.get("driver_id")
    latitude = data.get("latitude")
    longitude = data.get("longitude")

    driver = Driver.query.filter_by(id=driver_id, ativo=True).first()

    if not driver:
        return jsonify({
            "success": False,
            "message": "Motoboy inválido."
        }), 400

    if latitude is None or longitude is None:
        return jsonify({
            "success": False,
            "message": "Latitude e longitude são obrigatórias."
        }), 400

    location = DriverLocation(
        driver_id=driver.id,
        latitude=float(latitude),
        longitude=float(longitude),
        criado_em=datetime.now()
    )

    db.session.add(location)
    db.session.commit()

    return jsonify({
        "success": True,
        "message": "Localização registrada."
    })


@app.route("/api/driver/deliveries/<int:driver_id>", methods=["GET"])
def api_driver_deliveries(driver_id):
    entregas = Delivery.query.filter_by(
        driver_id=driver_id,
        status="EM_ROTA"
    ).order_by(Delivery.horario_saida.desc()).all()

    return jsonify({
        "success": True,
        "deliveries": [
            {
                "delivery_id": entrega.id,
                "order_id": entrega.order.id,
                "numero_pedido": entrega.order.numero_pedido,
                "cliente_nome": entrega.order.cliente_nome,
                "endereco": entrega.order.endereco,
                "taxa_entrega": entrega.order.taxa_entrega,
                "horario_saida": entrega.horario_saida.strftime("%H:%M"),
                "status": entrega.status
            }
            for entrega in entregas
        ]
    })


@app.route("/api/driver/finish", methods=["POST"])
def api_driver_finish():
    data = request.get_json(silent=True) or {}

    delivery_id = data.get("delivery_id")
    driver_id = data.get("driver_id")

    entrega = Delivery.query.filter_by(
        id=delivery_id,
        driver_id=driver_id,
        status="EM_ROTA"
    ).first()

    if not entrega:
        return jsonify({
            "success": False,
            "message": "Entrega não encontrada."
        }), 404

    entrega.status = "ENTREGUE"
    entrega.horario_entrega = datetime.now()
    entrega.order.status = "ENTREGUE"

    for item in entrega.route_items:
        item.status = "ENTREGUE"

    db.session.commit()

    return jsonify({
        "success": True,
        "message": "Entrega finalizada."
    })


# =========================
# ADMIN: MAPA, ENTREGAS, RELATÓRIOS, ROTAS
# =========================

@app.route("/admin/mapa")
def admin_mapa():
    if not session.get("admin"):
        return redirect("/login")

    return render_template("admin_mapa.html")


@app.route("/api/admin/locations", methods=["GET"])
def api_admin_locations():
    if not session.get("admin"):
        return jsonify({
            "success": False,
            "message": "Não autorizado."
        }), 401

    drivers = Driver.query.filter_by(ativo=True).all()
    resultado = []

    for driver in drivers:
        ultima = DriverLocation.query.filter_by(
            driver_id=driver.id
        ).order_by(DriverLocation.id.desc()).first()

        if ultima:
            resultado.append({
                "driver_id": driver.id,
                "driver_name": driver.nome,
                "latitude": ultima.latitude,
                "longitude": ultima.longitude,
                "horario": ultima.criado_em.strftime("%H:%M:%S")
            })

    return jsonify({
        "success": True,
        "drivers": resultado
    })


@app.route("/admin/entregas")
def admin_entregas():
    if not session.get("admin"):
        return redirect("/login")

    entregas = Delivery.query.order_by(Delivery.id.desc()).all()
    return render_template("admin_entregas.html", entregas=entregas)


@app.route("/admin/relatorio")
def admin_relatorio():
    if not session.get("admin"):
        return redirect("/login")

    drivers = Driver.query.filter_by(ativo=True).all()
    relatorio = []

    for driver in drivers:
        entregas = Delivery.query.filter_by(driver_id=driver.id).all()
        total_taxas = sum(entrega.order.taxa_entrega for entrega in entregas)

        relatorio.append({
            "driver": driver,
            "entregas": entregas,
            "total_entregas": len(entregas),
            "total_taxas": total_taxas
        })

    return render_template("admin_relatorio.html", relatorio=relatorio)


@app.route("/admin/rotas")
def admin_rotas():
    if not session.get("admin"):
        return redirect("/login")

    drivers = Driver.query.filter_by(ativo=True).all()
    rotas = []

    for driver in drivers:
        itens = DeliveryRouteItem.query.filter_by(
            driver_id=driver.id,
            status="PENDENTE"
        ).order_by(DeliveryRouteItem.route_order.asc()).all()

        rotas.append({
            "driver": driver,
            "itens": itens
        })

    return render_template("admin_rotas.html", rotas=rotas)


# =========================
# IMPRESSÃO 58MM
# =========================

@app.route("/print/qr/<int:id>")
def print_qr_58mm(id):
    if not session.get("admin"):
        return redirect("/login")

    order = Order.query.get_or_404(id)
    qr_path = f"/qr_codes/pedido_{order.id}.png"

    return render_template("print/qr_58mm.html", order=order, qr_path=qr_path)


@app.route("/print/relatorio/<int:driver_id>")
def print_relatorio_58mm(driver_id):
    if not session.get("admin"):
        return redirect("/login")

    driver = Driver.query.get_or_404(driver_id)
    entregas = Delivery.query.filter_by(driver_id=driver.id).all()
    total_taxas = sum(entrega.order.taxa_entrega for entrega in entregas)

    return render_template(
        "print/relatorio_58mm.html",
        driver=driver,
        entregas=entregas,
        total_taxas=total_taxas
    )


@app.route("/print/cozinha/<int:order_id>")
def print_cozinha_58mm(order_id):
    if not session.get("admin"):
        return redirect("/login")

    order = YampiOrder.query.get_or_404(order_id)

    return render_template("print/cozinha_58mm.html", order=order)


# =========================
# RASTREIO DO CLIENTE
# =========================

@app.route("/rastreio/<token>")
def rastreio_cliente(token):
    order = Order.query.filter_by(tracking_token=token).first_or_404()
    entrega = Delivery.query.filter_by(order_id=order.id).order_by(Delivery.id.desc()).first()

    return render_template(
        "rastreio.html",
        order=order,
        entrega=entrega
    )


@app.route("/api/rastreio/<token>")
def api_rastreio_cliente(token):
    order = Order.query.filter_by(tracking_token=token).first_or_404()
    entrega = Delivery.query.filter_by(order_id=order.id).order_by(Delivery.id.desc()).first()

    if not entrega:
        return jsonify({
            "success": True,
            "status": order.status,
            "message": "Pedido ainda não saiu para entrega.",
            "delivery": None
        })

    ultima = DriverLocation.query.filter_by(
        driver_id=entrega.driver_id
    ).order_by(DriverLocation.id.desc()).first()

    return jsonify({
        "success": True,
        "status": order.status,
        "pedido": order.numero_pedido,
        "cliente": order.cliente_nome,
        "driver_name": entrega.driver.nome,
        "horario_saida": entrega.horario_saida.strftime("%H:%M"),
        "latitude": ultima.latitude if ultima else None,
        "longitude": ultima.longitude if ultima else None,
        "ultima_atualizacao": ultima.criado_em.strftime("%H:%M:%S") if ultima else None,
        "eta_texto": "Aproximadamente 15 a 25 minutos"
    })


# =========================
# COZINHA / YAMPI
# =========================

@app.route("/admin/cozinha")
def admin_cozinha():
    if not session.get("admin"):
        return redirect("/login")

    orders = YampiOrder.query.order_by(YampiOrder.created_at.desc()).limit(100).all()

    return render_template("admin_cozinha.html", orders=orders)


@app.route("/api/yampi/sync")
def sync_yampi_orders():
    if not session.get("admin"):
        return jsonify({"ok": False, "error": "Não autorizado"}), 401

    try:
        url = f"{get_yampi_base_url()}/orders"

        response = requests.get(
            url,
            headers=yampi_headers(),
            timeout=20
        )

        if not response.ok:
            return jsonify({
                "ok": False,
                "status_code": response.status_code,
                "error": response.text
            }), response.status_code

        data = response.json()
        orders = data.get("data", [])

        saved = 0
        saved_ids = []

        for item in orders:
            yampi_id = str(item.get("id") or "")

            if not yampi_id:
                continue

            existing = YampiOrder.query.filter_by(yampi_id=yampi_id).first()

            if existing:
                continue

            detail_item = item

            try:
                detail_url = f"{get_yampi_base_url()}/orders/{yampi_id}"
                detail_response = requests.get(
                    detail_url,
                    headers=yampi_headers(),
                    timeout=20
                )

                if detail_response.ok:
                    detail_json = detail_response.json()
                    detail_item = detail_json.get("data") or item
            except Exception:
                detail_item = item

            customer = get_nested_data(item.get("customer"))
            payment = get_nested_data(item.get("payment"))
            shipping = get_nested_data(item.get("shipping_address"))

            customer_name = (
                customer.get("name")
                or item.get("customer_name")
                or "Cliente não identificado"
            )

            customer_phone = extract_text(
                customer.get("phone")
                or customer.get("whatsapp")
                or item.get("phone")
                or ""
            )

            customer_email = customer.get("email") or ""

            customer_document = extract_text(
                customer.get("document")
                or customer.get("cpf")
                or item.get("document")
                or item.get("customer_document")
                or item.get("cpf")
                or ""
            )

            street = shipping.get("street", "")
            number = shipping.get("number", "")
            neighborhood = shipping.get("neighborhood", "")
            city = shipping.get("city", "")
            state = shipping.get("state", "")
            zipcode = shipping.get("zipcode", "")

            customer_address = (
                f"{street}, {number}\n"
                f"{neighborhood}\n"
                f"{city} - {state}\n"
                f"CEP: {zipcode}"
            ).strip()

            payment_status = extract_text(
                payment.get("status")
                or item.get("payment_status")
                or item.get("status")
                or ""
            )

            payment_method = extract_text(
                item.get("payment_method")
                or payment.get("method")
                or payment.get("name")
                or ""
            )

            total = get_float(
                item.get("total")
                or item.get("value_total")
                or item.get("value_total_paid")
                or item.get("value_products")
                or 0
            )

            delivery_fee = get_float(
                detail_item.get("value_shipment")
                or detail_item.get("shipment_cost")
                or detail_item.get("value_shipping")
                or detail_item.get("shipping_price")
                or 0
            )

            items = get_order_items_from_yampi(yampi_id)

            qr_token = secrets.token_urlsafe(32)
            tracking_token = secrets.token_urlsafe(32)

            mototrack_order = Order(
                numero_pedido=yampi_id,
                cliente_nome=customer_name,
                cliente_email=customer_email,
                telefone=customer_phone,
                endereco=customer_address or "Endereço não informado",
                taxa_entrega=delivery_fee,
                qr_token=qr_token,
                tracking_token=tracking_token,
                status="PRONTO"
            )

            db.session.add(mototrack_order)
            db.session.flush()

            yampi_order = YampiOrder(
                yampi_id=yampi_id,
                mototrack_order_id=mototrack_order.id,
                customer_name=customer_name,
                customer_phone=customer_phone,
                customer_email=customer_email,
                customer_document=customer_document,
                customer_address=customer_address,
                items_json=items,
                total=total,
                delivery_fee=delivery_fee,
                payment_status=payment_status,
                payment_method=payment_method,
                order_status="novo",
                raw_json=detail_item
            )

            db.session.add(yampi_order)
            db.session.commit()

            gerar_qrcode(mototrack_order)

            saved += 1
            saved_ids.append(yampi_order.id)

        return jsonify({
            "ok": True,
            "saved": saved,
            "saved_ids": saved_ids,
            "total_received": len(orders)
        })

    except Exception as e:
        db.session.rollback()

        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500


@app.route("/api/kitchen/orders")
def api_kitchen_orders():
    if not session.get("admin"):
        return jsonify({"ok": False, "error": "Não autorizado"}), 401

    orders = YampiOrder.query.order_by(YampiOrder.created_at.desc()).limit(100).all()

    return jsonify([
        {
            "id": order.id,
            "yampi_id": order.yampi_id,
            "customer_name": order.customer_name,
            "customer_phone": order.customer_phone,
            "total": order.total,
            "delivery_fee": order.delivery_fee,
            "payment_status": order.payment_status,
            "payment_method": order.payment_method,
            "local_payment_method": order.local_payment_method,
            "order_status": order.order_status,
            "notes": order.notes,
            "created_at": order.created_at.strftime("%H:%M:%S") if order.created_at else ""
        }
        for order in orders
    ])


@app.route("/api/kitchen/orders/<int:order_id>/status", methods=["POST"])
def update_kitchen_order_status(order_id):
    if not session.get("admin"):
        return jsonify({"ok": False, "error": "Não autorizado"}), 401

    order = YampiOrder.query.get_or_404(order_id)
    data = request.get_json(silent=True) or {}

    order.order_status = data.get("order_status", order.order_status)
    order.local_payment_method = data.get("local_payment_method", order.local_payment_method)
    order.notes = data.get("notes", order.notes)
    order.updated_at = datetime.now()

    db.session.commit()

    return jsonify({"ok": True})


# =========================
# INICIALIZAÇÃO
# =========================

with app.app_context():
    db.create_all()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=6061, debug=True)
