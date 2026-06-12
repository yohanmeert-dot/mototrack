from flask import Flask, render_template, request, redirect, session, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import secrets
import os
import qrcode

app = Flask(__name__)
app.secret_key = "mototrack_secret_key"

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///database.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


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


class DriverLocation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    driver_id = db.Column(db.Integer, db.ForeignKey("driver.id"), nullable=False)
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    criado_em = db.Column(db.DateTime, default=datetime.now)

    driver = db.relationship("Driver", backref="locations")


@app.route("/")
def home():
    return redirect("/login")


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


@app.route("/admin")
def admin():
    if not session.get("admin"):
        return redirect("/login")

    drivers = Driver.query.order_by(Driver.id.desc()).all()
    orders = Order.query.order_by(Order.id.desc()).all()

    return render_template("admin.html", drivers=drivers, orders=orders)


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
        taxa_entrega=float(request.form.get("taxa_entrega") or 0),
        qr_token=qr_token,
        tracking_token=tracking_token,
        status="PRONTO"
    )

    db.session.add(novo)
    db.session.commit()

    gerar_qrcode(novo)

    return redirect("/admin")


def gerar_qrcode(order):
    pasta = "qr_codes"
    os.makedirs(pasta, exist_ok=True)

    link = f"http://127.0.0.1:6061/motoboy/scan/{order.qr_token}"

    img = qrcode.make(link)
    caminho = os.path.join(pasta, f"pedido_{order.id}.png")
    img.save(caminho)


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
        db.session.commit()

        return render_template(
            "motoboy_scan.html",
            order=order,
            drivers=drivers,
            sucesso=f"Pedido saiu com {driver.nome} às {entrega.horario_saida.strftime('%H:%M')}"
        )

    return render_template("motoboy_scan.html", order=order, drivers=drivers)


# =========================
# APIs DO APP DO MOTOBOY
# =========================

@app.route("/api/driver/login", methods=["POST"])
def api_driver_login():
    data = request.get_json()

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
    data = request.get_json()

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
    db.session.commit()

    return jsonify({
        "success": True,
        "message": "Pedido saiu para entrega.",
        "delivery_id": entrega.id,
        "order": {
            "id": order.id,
            "numero_pedido": order.numero_pedido,
            "cliente_nome": order.cliente_nome,
            "endereco": order.endereco,
            "taxa_entrega": order.taxa_entrega,
            "status": order.status
        }
    })


@app.route("/api/driver/location", methods=["POST"])
def api_driver_location():
    data = request.get_json()

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
    data = request.get_json()

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

    db.session.commit()

    return jsonify({
        "success": True,
        "message": "Entrega finalizada."
    })

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
@app.route("/motoboy/app/<int:driver_id>")
def motoboy_app_teste(driver_id):
    driver = Driver.query.get_or_404(driver_id)
    return render_template("motoboy_app.html", driver=driver)

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


with app.app_context():
    db.create_all()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=6061, debug=True)