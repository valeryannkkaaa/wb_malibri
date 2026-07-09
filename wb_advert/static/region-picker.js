(function () {
  const select = document.getElementById("parser-region-select");
  const status = document.getElementById("parser-region-status");
  if (!select) return;

  select.addEventListener("change", async () => {
    const region = select.value;
    if (status) {
      status.textContent = "Сохранение…";
      status.className = "region-status";
    }
    select.disabled = true;
    try {
      const resp = await fetch("/api/advert/settings/parser-region", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ region }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        throw new Error(data.detail || resp.statusText);
      }
      if (status) {
        status.textContent = `${data.region} (${data.dest}) — сохранено, обновляем…`;
        status.className = "region-status ok";
      }
      const destBadge = document.getElementById("parser-dest-badge");
      if (destBadge) destBadge.textContent = data.dest;
      window.setTimeout(() => window.location.reload(), 400);
    } catch (err) {
      if (status) {
        status.textContent = "Ошибка: " + err.message;
        status.className = "region-status err";
      }
    } finally {
      select.disabled = false;
    }
  });
})();
