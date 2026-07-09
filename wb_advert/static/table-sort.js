/** Click column headers to sort tables (tables need class "sortable"). */
(function () {
  function cellValue(row, colIndex) {
    const cell = row.cells[colIndex];
    if (!cell) return "";
    if (cell.dataset.sortValue !== undefined) return cell.dataset.sortValue;
    return cell.textContent.trim();
  }

  function compare(a, b, type) {
    if (type === "number") {
      const na = parseFloat(a);
      const nb = parseFloat(b);
      const aEmpty = a === "" || a === "—" || Number.isNaN(na);
      const bEmpty = b === "" || b === "—" || Number.isNaN(nb);
      if (aEmpty && bEmpty) return 0;
      if (aEmpty) return 1;
      if (bEmpty) return -1;
      return na - nb;
    }
    if (type === "date") {
      return a.localeCompare(b);
    }
    return a.localeCompare(b, "ru", { sensitivity: "base" });
  }

  function sortTable(table, colIndex, type, th) {
    const tbody = table.tBodies[0];
    if (!tbody) return;

    const current = th.dataset.sortDir || "";
    const dir = current === "asc" ? "desc" : "asc";

    table.querySelectorAll("th[data-sort]").forEach((h) => {
      h.classList.remove("sort-asc", "sort-desc");
      delete h.dataset.sortDir;
    });
    th.classList.add(dir === "asc" ? "sort-asc" : "sort-desc");
    th.dataset.sortDir = dir;

    const rows = Array.from(tbody.querySelectorAll("tr"));
    rows.sort((r1, r2) => {
      const v1 = cellValue(r1, colIndex);
      const v2 = cellValue(r2, colIndex);
      const c = compare(v1, v2, type || "string");
      return dir === "asc" ? c : -c;
    });
    rows.forEach((r) => tbody.appendChild(r));
  }

  function applyDefaultSort(table) {
    const def = table.dataset.defaultSort;
    if (!def) return;
    const [colKey, dir] = def.split(":");
    const th = table.querySelector(`th[data-col="${colKey}"]`) || table.querySelector(`th[data-sort="${colKey}"]`);
    if (!th) return;
    th.dataset.sortDir = dir === "desc" ? "asc" : "desc";
    sortTable(table, th.cellIndex, th.dataset.sort, th);
  }

  function initTable(table) {
    table.querySelectorAll("th[data-sort]").forEach((th) => {
      th.addEventListener("click", () => {
        sortTable(table, th.cellIndex, th.dataset.sort, th);
      });
    });
    applyDefaultSort(table);
  }

  document.querySelectorAll("table.sortable").forEach(initTable);
})();
