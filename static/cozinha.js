let syncingNow = false;
let soundEnabled = true;
let knownOrderIds = new Set();

function updateLastUpdate() {
    const now = new Date();
    document.getElementById("lastUpdate").innerText = now.toLocaleTimeString("pt-BR");
}

function toggleSound() {
    soundEnabled = !soundEnabled;

    const button = document.getElementById("soundButton");

    if (soundEnabled) {
        button.innerText = "Som: ativado";
    } else {
        button.innerText = "Som: desativado";
    }
}

function playBellSound() {
    if (!soundEnabled) {
        return;
    }

    const AudioContext = window.AudioContext || window.webkitAudioContext;

    if (!AudioContext) {
        return;
    }

    const audioCtx = new AudioContext();

    function bell(freq, start, duration) {
        const osc = audioCtx.createOscillator();
        const gain = audioCtx.createGain();

        osc.type = "sine";
        osc.frequency.value = freq;

        gain.gain.setValueAtTime(0.0001, start);
        gain.gain.exponentialRampToValueAtTime(0.5, start + 0.01);
        gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);

        osc.connect(gain);
        gain.connect(audioCtx.destination);

        osc.start(start);
        osc.stop(start + duration);
    }

    const now = audioCtx.currentTime;

    bell(1200, now, 0.5);
    bell(900, now + 0.22, 0.6);
}

function statusBadge(status) {
    const safeStatus = status || "novo";

    if (safeStatus === "novo") {
        return `<span class="badge badge-new">Novo</span>`;
    }

    if (safeStatus === "em preparo") {
        return `<span class="badge badge-preparing">Em preparo</span>`;
    }

    if (safeStatus === "finalizado") {
        return `<span class="badge badge-finished">Finalizado</span>`;
    }

    return `<span class="badge">${safeStatus}</span>`;
}

function renderOrders(orders, newIds = []) {
    const container = document.getElementById("ordersContainer");

    if (!orders || orders.length === 0) {
        container.innerHTML = "<p>Nenhum pedido encontrado.</p>";
        return;
    }

    let html = `
        <table>
            <thead>
                <tr>
                    <th>Pedido</th>
                    <th>Cliente</th>
                    <th>Telefone</th>
                    <th>Total</th>
                    <th>Pagamento</th>
                    <th>Status</th>
                    <th>Editar</th>
                    <th>Ações</th>
                </tr>
            </thead>
            <tbody>
    `;

    orders.forEach(order => {
        const isNew = newIds.includes(order.id);
        const rowClass = isNew ? "pedido-novo" : "";

        html += `
            <tr class="${rowClass}">
                <td>#${order.yampi_id}</td>
                <td>${order.customer_name || "-"}</td>
                <td>${order.customer_phone || "-"}</td>
                <td>R$ ${Number(order.total || 0).toFixed(2)}</td>
                <td>
                    ${order.payment_method || "-"}
                    <br>
                    <small>${order.payment_status || ""}</small>
                    <br>
                    <strong>${order.local_payment_method || ""}</strong>
                </td>
                <td>${statusBadge(order.order_status)}</td>
                <td>
                    <select id="payment-${order.id}">
                        <option value="">Pagamento local</option>
                        <option value="PIX" ${order.local_payment_method === "PIX" ? "selected" : ""}>PIX</option>
                        <option value="DINHEIRO" ${order.local_payment_method === "DINHEIRO" ? "selected" : ""}>DINHEIRO</option>
                        <option value="CARTAO" ${order.local_payment_method === "CARTAO" ? "selected" : ""}>CARTÃO</option>
                        <option value="VR" ${order.local_payment_method === "VR" ? "selected" : ""}>VR</option>
                        <option value="IFOOD" ${order.local_payment_method === "IFOOD" ? "selected" : ""}>IFOOD</option>
                    </select>

                    <textarea id="notes-${order.id}" placeholder="Observações">${order.notes || ""}</textarea>

                    <button onclick="saveKitchenOrderInfo(${order.id})">
                        Salvar
                    </button>
                </td>
                <td>
                    <button onclick="printKitchenOrder(${order.id})">
                        Imprimir 58mm
                    </button>

                    <button onclick="markKitchenPreparing(${order.id})">
                        Em preparo
                    </button>

                    <button onclick="markKitchenFinished(${order.id})">
                        Finalizado
                    </button>
                </td>
            </tr>
        `;
    });

    html += `
            </tbody>
        </table>
    `;

    container.innerHTML = html;
}

async function loadKitchenOrders(playSoundForNew = false) {
    try {
        const response = await fetch("/api/kitchen/orders");
        const orders = await response.json();

        const newIds = [];

        orders.forEach(order => {
            if (!knownOrderIds.has(order.id)) {
                if (knownOrderIds.size > 0) {
                    newIds.push(order.id);
                }
                knownOrderIds.add(order.id);
            }
        });

        if (playSoundForNew && newIds.length > 0) {
            playBellSound();
        }

        renderOrders(orders, newIds);
        updateLastUpdate();

    } catch (err) {
        console.error(err);
        document.getElementById("ordersContainer").innerHTML =
            "<p>Erro ao carregar pedidos.</p>";
    }
}

async function syncYampiOrders(event) {
    const button = event ? event.target : null;

    if (syncingNow) {
        return;
    }

    syncingNow = true;

    if (button) {
        button.innerText = "Sincronizando...";
    }

    document.getElementById("syncStatus").innerText = "Sincronizando com a Yampi...";

    try {
        const response = await fetch("/api/yampi/sync");
        const data = await response.json();

        if (data.ok) {
            document.getElementById("syncStatus").innerText =
                "Sincronizado. Novos pedidos: " + data.saved;

            if (data.saved > 0) {
                playBellSound();
            }

            await loadKitchenOrders(false);
        } else {
            document.getElementById("syncStatus").innerText =
                "Erro ao sincronizar.";
            console.log(data);
        }
    } catch (err) {
        console.error(err);
        document.getElementById("syncStatus").innerText =
            "Erro inesperado na sincronização.";
    }

    if (button) {
        button.innerText = "Sincronizar agora";
    }

    syncingNow = false;
}

function printKitchenOrder(orderId) {
    const iframe = document.createElement("iframe");

    iframe.style.position = "fixed";
    iframe.style.right = "0";
    iframe.style.bottom = "0";
    iframe.style.width = "0";
    iframe.style.height = "0";
    iframe.style.border = "0";
    iframe.style.opacity = "0";

    iframe.src = "/print/cozinha/" + orderId;

    document.body.appendChild(iframe);

    iframe.onload = function () {
        setTimeout(() => {
            iframe.contentWindow.focus();
            iframe.contentWindow.print();
        }, 500);
    };

    setTimeout(() => {
        iframe.remove();
    }, 15000);
}

async function markKitchenPreparing(orderId) {
    await fetch("/api/kitchen/orders/" + orderId + "/status", {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({
            order_status: "em preparo"
        })
    });

    await loadKitchenOrders(false);
}

async function markKitchenFinished(orderId) {
    await fetch("/api/kitchen/orders/" + orderId + "/status", {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({
            order_status: "finalizado"
        })
    });

    await loadKitchenOrders(false);
}

async function saveKitchenOrderInfo(orderId) {
    const payment = document.getElementById("payment-" + orderId).value;
    const notes = document.getElementById("notes-" + orderId).value;

    await fetch("/api/kitchen/orders/" + orderId + "/status", {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({
            local_payment_method: payment,
            notes: notes
        })
    });

    alert("Alterações salvas!");
    await loadKitchenOrders(false);
}

async function autoLoop() {
    await syncYampiOrders(null);
}

loadKitchenOrders(false);
setInterval(autoLoop, 5000);