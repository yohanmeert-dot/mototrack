let syncingNow = false;
let soundEnabled = true;
let knownOrderIds = new Set();

function updateLastUpdate() {
    document.getElementById("lastUpdate").innerText =
        new Date().toLocaleTimeString("pt-BR");
}

function toggleSound() {
    soundEnabled = !soundEnabled;
    document.getElementById("soundButton").innerText =
        soundEnabled ? "🔔 Som ativado" : "🔕 Som desativado";
}

function playBellSound() {
    if (!soundEnabled) return;

    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (!AudioContext) return;

    const ctx = new AudioContext();

    function beep(freq, delay) {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();

        osc.frequency.value = freq;
        osc.type = "sine";

        gain.gain.setValueAtTime(0.001, ctx.currentTime + delay);
        gain.gain.exponentialRampToValueAtTime(0.5, ctx.currentTime + delay + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + delay + 0.5);

        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.start(ctx.currentTime + delay);
        osc.stop(ctx.currentTime + delay + 0.55);
    }

    beep(1200, 0);
    beep(850, 0.25);
}

function statusBadge(status) {
    if (status === "em preparo") return `<span class="status preparo">Em preparo</span>`;
    if (status === "finalizado") return `<span class="status finalizado">Finalizado</span>`;
    return `<span class="status novo">Novo pedido</span>`;
}

function renderOrders(orders, newIds = []) {
    const container = document.getElementById("ordersContainer");

    if (!orders || orders.length === 0) {
        container.innerHTML = `<div class="empty-state">Nenhum pedido encontrado.</div>`;
        return;
    }

    let html = `<div class="kitchen-grid">`;

    orders.forEach(order => {
        const isNew = newIds.includes(order.id);

        html += `
        <div class="order-card ${isNew ? "new-highlight" : ""}">
            <div class="order-top">
                <div>
                    <div class="order-number">#${order.yampi_id}</div>
                    <div class="order-client">${order.customer_name || "-"}</div>
                </div>
                ${statusBadge(order.order_status)}
            </div>

            <div class="order-info">
                <div><strong>📞 Telefone:</strong> ${order.customer_phone || "-"}</div>
                <div><strong>💰 Total:</strong> R$ ${Number(order.total || 0).toFixed(2)}</div>
                <div><strong>💳 Pagamento:</strong> ${order.local_payment_method || order.payment_method || "-"}</div>
                <div><strong>🕒 Entrada:</strong> ${order.created_at || "-"}</div>
            </div>

            <div class="edit-box">
                <label>Pagamento local</label>
                <select id="payment-${order.id}">
                    <option value="">Selecionar</option>
                    <option value="PIX" ${order.local_payment_method === "PIX" ? "selected" : ""}>PIX</option>
                    <option value="DINHEIRO" ${order.local_payment_method === "DINHEIRO" ? "selected" : ""}>DINHEIRO</option>
                    <option value="CARTAO" ${order.local_payment_method === "CARTAO" ? "selected" : ""}>CARTÃO</option>
                    <option value="VR" ${order.local_payment_method === "VR" ? "selected" : ""}>VR</option>
                    <option value="IFOOD" ${order.local_payment_method === "IFOOD" ? "selected" : ""}>IFOOD</option>
                </select>

                <label>Observações</label>
                <textarea id="notes-${order.id}" placeholder="Observações da cozinha">${order.notes || ""}</textarea>

                <button class="btn secondary" onclick="saveKitchenOrderInfo(${order.id})">Salvar alterações</button>
            </div>

            <div class="actions">
                <button class="btn print" onclick="printKitchenOrder(${order.id})">🖨️ Imprimir 58mm</button>
                <button class="btn prep" onclick="markKitchenPreparing(${order.id})">🔥 Em preparo</button>
                <button class="btn done" onclick="markKitchenFinished(${order.id})">✅ Finalizado</button>
            </div>
        </div>`;
    });

    html += `</div>`;
    container.innerHTML = html;
}

async function loadKitchenOrders(playSoundForNew = false) {
    const response = await fetch("/api/kitchen/orders");
    const orders = await response.json();

    const newIds = [];

    orders.forEach(order => {
        if (!knownOrderIds.has(order.id)) {
            if (knownOrderIds.size > 0) newIds.push(order.id);
            knownOrderIds.add(order.id);
        }
    });

    if (playSoundForNew && newIds.length > 0) playBellSound();

    renderOrders(orders, newIds);
    updateLastUpdate();
}

async function syncYampiOrders(event) {
    if (syncingNow) return;

    syncingNow = true;
    const button = event ? event.target : null;

    if (button) button.innerText = "Sincronizando...";
    document.getElementById("syncStatus").innerText = "Buscando pedidos na Yampi...";

    try {
        const response = await fetch("/api/yampi/sync");
        const data = await response.json();

        if (data.ok) {
            document.getElementById("syncStatus").innerText =
                `Sincronizado | novos pedidos: ${data.saved}`;

            if (data.saved > 0) playBellSound();

            await loadKitchenOrders(false);
        } else {
            document.getElementById("syncStatus").innerText = "Erro ao sincronizar.";
        }
    } catch (e) {
        document.getElementById("syncStatus").innerText = "Erro inesperado.";
    }

    if (button) button.innerText = "Sincronizar agora";
    syncingNow = false;
}

function printKitchenOrder(orderId) {
    const iframe = document.createElement("iframe");
    iframe.style.display = "none";
    iframe.src = "/print/cozinha/" + orderId;
    document.body.appendChild(iframe);

    iframe.onload = function () {
        iframe.contentWindow.focus();
        iframe.contentWindow.print();
    };

    setTimeout(() => iframe.remove(), 15000);
}

async function markKitchenPreparing(orderId) {
    await updateOrder(orderId, { order_status: "em preparo" });
}

async function markKitchenFinished(orderId) {
    await updateOrder(orderId, { order_status: "finalizado" });
}

async function saveKitchenOrderInfo(orderId) {
    await updateOrder(orderId, {
        local_payment_method: document.getElementById("payment-" + orderId).value,
        notes: document.getElementById("notes-" + orderId).value
    });

    alert("Alterações salvas!");
}

async function updateOrder(orderId, payload) {
    await fetch("/api/kitchen/orders/" + orderId + "/status", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
    });

    await loadKitchenOrders(false);
}

loadKitchenOrders(false);
setInterval(() => syncYampiOrders(null), 5000);