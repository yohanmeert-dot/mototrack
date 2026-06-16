async function syncYampiOrders(event) {
    const button = event ? event.target : null;

    if (button) {
        button.innerText = "Sincronizando...";
    }

    try {
        const response = await fetch("/api/yampi/sync");
        const data = await response.json();

        if (data.ok) {
            alert(
                "Pedidos sincronizados!\n\nRecebidos: " +
                data.total_received +
                "\nNovos salvos: " +
                data.saved
            );

            location.reload();
        } else {
            alert("Erro ao sincronizar.");
            console.log(data);
        }
    } catch (err) {
        console.error(err);
        alert("Erro inesperado.");
    }

    if (button) {
        button.innerText = "Sincronizar pedidos";
    }
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

    location.reload();
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

    location.reload();
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
    location.reload();
}


function playBellSound() {
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


let syncingNow = false;

async function autoSyncYampiOrders() {
    if (syncingNow) {
        return;
    }

    syncingNow = true;

    try {
        const response = await fetch("/api/yampi/sync");
        const data = await response.json();

        if (data.ok && data.saved > 0) {
            playBellSound();

            setTimeout(() => {
                location.reload();
            }, 1200);
        }
    } catch (err) {
        console.error("Erro auto sync:", err);
    }

    syncingNow = false;
}

setInterval(autoSyncYampiOrders, 5000);