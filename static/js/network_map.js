/* The network map page: draws the elements from /map/data/ with Cytoscape.js.
 *
 * The elements come from inventory/netmap.py. They are fetched on load and every
 * 30 seconds; when only health or "last seen" changed, the nodes are updated in
 * place, so nothing moves. Where the user dragged the nodes is kept in this
 * browser's localStorage until a device appears or goes (a convenience: the map
 * works the same without it).
 */
(function () {
  "use strict";

  const REFRESH_MS = 30000;
  const POSITIONS_KEY = "wall-hub.map.positions";
  const container = document.getElementById("map");
  const details = document.getElementById("map-details");
  const status = document.getElementById("map-status");
  const search = document.getElementById("map-search");
  const empty = document.getElementById("map-empty");
  const intro = details.innerHTML;

  /* Bootstrap's colours for the current theme, so the map matches the rest of the
   * hub. Read again when the header's button switches between light and dark. */
  function palette() {
    const css = getComputedStyle(document.documentElement);
    const colour = (name, fallback) => css.getPropertyValue(name).trim() || fallback;
    return {
      up: colour("--bs-success", "#198754"),
      down: colour("--bs-danger", "#dc3545"),
      grey: colour("--bs-secondary", "#6c757d"),
      text: colour("--bs-body-color", "#212529"),
      bg: colour("--bs-body-bg", "#ffffff"),
      box: colour("--bs-tertiary-bg", "#f8f9fa"),
      border: colour("--bs-border-color", "#dee2e6"),
      accent: colour("--bs-primary", "#0d6efd"),
    };
  }

  function buildStyle() {
    const c = palette();
    return [
      {
        selector: "node",
        style: {
          label: "data(label)",
          "text-wrap": "wrap",
          "text-valign": "bottom",
          "text-margin-y": 4,
          "font-size": 10,
          color: c.text,
          width: 24,
          height: 24,
          shape: "ellipse",
          "background-color": c.bg,
          "border-width": 2,
          "border-color": c.grey,
        },
      },
      {
        selector: ".network",
        style: {
          shape: "round-rectangle",
          "text-valign": "top",
          "text-margin-y": -4,
          "font-size": 12,
          "font-weight": "bold",
          "background-color": c.box,
          "border-width": 1,
          "border-color": c.border,
          padding: 18,
        },
      },
      { selector: ".other", style: { "border-style": "dashed" } },
      { selector: ".kind-computer", style: { shape: "round-rectangle" } },
      { selector: ".kind-server", style: { shape: "rectangle" } },
      { selector: ".kind-printer", style: { shape: "barrel" } },
      { selector: ".kind-phone", style: { width: 18, height: 18 } },
      { selector: ".kind-network, .gateway, .router", style: { shape: "diamond", width: 30, height: 30 } },
      { selector: ".health-up", style: { "background-color": c.up, "border-color": c.up } },
      { selector: ".health-down", style: { "background-color": c.down, "border-color": c.down } },
      { selector: ".health-unknown", style: { "background-color": c.grey, "border-color": c.grey } },
      { selector: ".stale", style: { opacity: 0.45, "border-style": "dashed" } },
      { selector: ".synthetic", style: { "border-style": "dotted" } },
      {
        selector: ".hub",
        style: {
          shape: "star",
          width: 46,
          height: 46,
          "background-color": c.accent,
          "border-color": c.accent,
          "font-size": 12,
          "font-weight": "bold",
        },
      },
      {
        selector: ".internet",
        style: {
          shape: "round-rectangle",
          width: 80,
          height: 34,
          "text-valign": "center",
          "text-margin-y": 0,
          "background-color": c.box,
          "border-style": "dashed",
        },
      },
      {
        selector: "edge",
        style: { width: 2, "line-color": c.border, "curve-style": "bezier" },
      },
      {
        selector: "edge[label]",
        style: {
          label: "data(label)",
          "font-size": 9,
          color: c.grey,
          "text-background-color": c.bg,
          "text-background-opacity": 1,
          "text-background-padding": 2,
        },
      },
      { selector: "node:selected", style: { "border-width": 4, "border-color": c.accent } },
      {
        selector: ".match",
        style: { "underlay-color": c.accent, "underlay-opacity": 0.3, "underlay-padding": 8 },
      },
    ];
  }

  const cy = cytoscape({ container, style: buildStyle(), minZoom: 0.2, maxZoom: 3 });
  document.addEventListener("hub:theme", () => cy.style(buildStyle()));

  // --- positions ---

  function loadPositions() {
    try {
      return JSON.parse(localStorage.getItem(POSITIONS_KEY)) || {};
    } catch (error) {
      return {};
    }
  }

  function savePositions() {
    const positions = {};
    cy.nodes().forEach((node) => {
      if (!node.isParent()) positions[node.id()] = node.position();
    });
    try {
      localStorage.setItem(POSITIONS_KEY, JSON.stringify(positions));
    } catch (error) {
      // Storage blocked (private window): positions are just not remembered.
    }
  }

  function forgetPositions() {
    try {
      localStorage.removeItem(POSITIONS_KEY);
    } catch (error) {
      // Nothing was stored.
    }
  }

  /* The layout is deterministic, not force-directed: every network box holds its
   * devices in a grid (the gateway first, then by IP address), the boxes stand in
   * rows of BOXES_PER_ROW, the hub below them and the Internet above. The same
   * data always gives the same picture, and a new device only shifts the ones
   * after it in its own box. */
  const CELL_W = 100; // room for a label like "Reception PC" under each device
  const CELL_H = 78;
  const BOX_PAD = 18; // the .network padding in the style above, plus its title
  const BOX_GAP = 80;
  const BOXES_PER_ROW = 3;
  const MAX_COLUMNS = 6;

  function ipKey(node) {
    const parts = String(node.data("ip") || "").split(".").map(Number);
    return parts.length === 4 ? parts.reduce((key, part) => key * 256 + part, 0) : Infinity;
  }

  function devicesFirst(a, b) {
    return (b.data("gateway") ? 1 : 0) - (a.data("gateway") ? 1 : 0) || ipKey(a) - ipKey(b);
  }

  /* Positions of a box's contents relative to its top-left corner, and its size.
   * Networks inside the box (a /25 in a /24) go in a row under its devices. */
  function measure(box) {
    const devices = box.children().filter((node) => !node.isParent()).sort(devicesFirst);
    const inner = box.children().filter((node) => node.isParent());
    const columns = Math.max(1, Math.min(MAX_COLUMNS, Math.ceil(Math.sqrt(devices.length * 1.5))));
    const rows = Math.ceil(devices.length / columns);
    const places = devices.map((node, i) => ({
      node,
      x: (i % columns) * CELL_W + CELL_W / 2,
      y: Math.floor(i / columns) * CELL_H + CELL_H / 2,
    }));
    let width = devices.length ? columns * CELL_W : CELL_W;
    let height = rows * CELL_H;
    let left = 0;
    let innerHeight = 0;
    inner.forEach((child) => {
      const size = measure(child);
      places.push({ size, x: left + BOX_PAD, y: height + BOX_PAD * 2 });
      left += size.width + BOX_PAD * 2 + BOX_GAP / 2;
      innerHeight = Math.max(innerHeight, size.height + BOX_PAD * 4);
    });
    if (inner.length) {
      width = Math.max(width, left - BOX_GAP / 2);
      height += innerHeight;
    }
    return { width, height, places };
  }

  function place(size, left, top, positions) {
    for (const item of size.places) {
      if (item.node) positions[item.node.id()] = { x: left + item.x, y: top + item.y };
      else place(item.size, left + item.x, top + item.y, positions);
    }
  }

  function gridPositions() {
    const positions = {};
    const boxes = cy.nodes(".network").filter((node) => node.parent().empty());
    let top = 0;
    for (let start = 0; start < boxes.length; start += BOXES_PER_ROW) {
      const row = boxes.slice(start, start + BOXES_PER_ROW).map(measure);
      const rowWidth =
        row.reduce((sum, size) => sum + size.width + BOX_PAD * 2, 0) + BOX_GAP * (row.length - 1);
      let left = -rowWidth / 2;
      for (const size of row) {
        place(size, left + BOX_PAD, top + BOX_PAD * 2, positions);
        left += size.width + BOX_PAD * 2 + BOX_GAP;
      }
      top += Math.max(...row.map((size) => size.height)) + BOX_PAD * 3 + BOX_GAP;
    }
    positions.hub = { x: 0, y: top + 20 };
    positions.internet = { x: 0, y: -110 };
    // Routers outside every box (for a network behind a router no scan covered).
    cy.nodes(".router")
      .filter((node) => node.parent().empty())
      .forEach((node, i) => {
        positions[node.id()] = { x: -160 - i * CELL_W, y: -110 };
      });
    return positions;
  }

  /* Remembered positions if every node has one (nothing new since the user
   * arranged the map), otherwise the grid. */
  function arrange(useSaved) {
    const saved = useSaved ? loadPositions() : {};
    const leaves = cy.nodes().filter((node) => !node.isParent());
    const positions = leaves.every((node) => saved[node.id()]) ? saved : gridPositions();
    // Only the leaves: a box's position follows from its contents, and moving a
    // box would drag its devices along.
    leaves
      .layout({
        name: "preset",
        positions: (node) => positions[node.id()] || { x: 0, y: 0 },
        fit: false,
      })
      .run();
    cy.fit(undefined, 30);
    if (positions !== saved) forgetPositions();
  }

  // --- details panel (built with textContent: names come from users) ---

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function link(href, text) {
    const anchor = element("a", "", text);
    anchor.href = href;
    return anchor;
  }

  function addRow(list, term, value) {
    if (value === undefined || value === null || value === "") return;
    list.append(element("dt", "col-5 fw-normal text-body-secondary", term));
    list.append(element("dd", "col-7 mb-1 text-break", value));
  }

  function showDetails(node) {
    const data = node.data();
    details.replaceChildren(element("h2", "h6", data.label.replace("\n", " · ")));
    const list = element("dl", "row mb-2");
    if (node.hasClass("hub")) {
      details.append(element("p", "mb-1", "The hub: it scans, monitors and wakes the devices on these networks."));
      for (const address of data.addresses || []) {
        const line = element("div");
        line.append(link(address.url, address.ip));
        details.append(line);
      }
      return;
    }
    if (data.network) {
      const devices = node.descendants().filter((child) => child.data("url")).length;
      details.append(element("p", "", `${devices} device${devices === 1 ? "" : "s"}.`));
      return;
    }
    if (node.hasClass("internet")) {
      details.append(element("p", "", "Where the networks' routers lead."));
      return;
    }
    if (!data.url) {
      details.append(
        element("p", "", `The gateway of a network, at ${data.ip}. No scan has found it as a device.`),
      );
      return;
    }
    addRow(list, "IP address", data.ip);
    addRow(list, "MAC address", data.mac);
    addRow(list, "Vendor", data.vendor);
    addRow(list, "Hostname", data.hostname);
    addRow(list, "Type", data.type);
    addRow(list, "Role", data.gateway ? "gateway of its network" : "");
    addRow(list, "Health", data.health);
    addRow(list, "Last seen", data.lastSeen + (data.seenInLastScan ? "" : " (not in the newest scan)"));
    addRow(list, "Open ports", data.ports || "none");
    addRow(list, "Owner", data.owner);
    addRow(list, "Location", data.location);
    details.append(list, link(data.url, "Open the device page"));
  }

  cy.on("tap", "node", (event) => showDetails(event.target));
  cy.on("tap", (event) => {
    if (event.target === cy) details.innerHTML = intro;
  });
  cy.on("dragfree", "node", savePositions);

  // --- search ---

  function highlight() {
    cy.nodes().removeClass("match");
    const query = search.value.trim().toLowerCase();
    if (!query) return cy.collection();
    const fields = ["label", "ip", "mac", "hostname", "vendor"];
    const hits = cy.nodes().filter(
      (node) =>
        !node.isParent() &&
        fields.some((field) => String(node.data(field) || "").toLowerCase().includes(query)),
    );
    hits.addClass("match");
    return hits;
  }

  search.addEventListener("input", () => {
    const hits = highlight();
    if (hits.nonempty()) cy.animate({ fit: { eles: hits, padding: 80 } }, { duration: 250 });
  });
  search.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    const first = highlight()[0];
    if (first) {
      cy.$(":selected").unselect();
      first.select();
      showDetails(first);
    }
  });

  document.getElementById("map-fit").addEventListener("click", () => cy.fit(undefined, 30));
  document.getElementById("map-arrange").addEventListener("click", () => arrange(false));

  // --- loading and refreshing ---

  let shape = "";

  async function refresh() {
    let elements;
    try {
      const response = await fetch(container.dataset.url, {
        headers: { Accept: "application/json" },
        credentials: "same-origin",
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      elements = (await response.json()).elements;
    } catch (error) {
      status.textContent = `Could not update the map (${error.message}). Logged out?`;
      return;
    }
    // Which elements exist and where they sit; anything else is updated in place.
    const newShape = elements
      .map((item) => `${item.data.id}>${item.data.parent || ""}`)
      .sort()
      .join("|");
    const selected = cy.$(":selected").map((node) => node.id());
    if (newShape !== shape) {
      shape = newShape;
      cy.elements().remove();
      cy.add(elements);
      arrange(true);
    } else {
      for (const item of elements) {
        // Structure (id, parent, edge ends) is unchanged here and cannot be set this way.
        const { id, parent, source, target, ...rest } = item.data;
        const existing = cy.getElementById(id);
        existing.data(rest);
        existing.classes(item.classes || "");
      }
    }
    highlight();
    for (const id of selected) {
      const node = cy.getElementById(id);
      if (node.nonempty()) {
        node.select();
        showDetails(node);
      }
    }
    empty.hidden = cy.nodes(".network").nonempty();
    status.textContent = `Updated ${new Date().toLocaleTimeString()}`;
  }

  refresh();
  setInterval(() => {
    if (!document.hidden) refresh();
  }, REFRESH_MS);
})();
