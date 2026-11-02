const source = document.getElementById("source");
const out = document.getElementById("out");
const example = document.getElementById("example");
const tabs = document.getElementById("tabs");
const buttons = ["check", "emit", "compile"].map((id) => document.getElementById(id));
const tabButtons = ["c", "idl", "client"].map((id) => document.getElementById("tab-" + id));
const views = { c: "", idl: "", client: "" };
let cursor = "";

/* One consumer of the output surface: the state class adds a colored
   edge to the text, which always carries the meaning itself. */
function show(text, state) {
  out.textContent = text;
  out.className = state || "on-info";
}

/* Emit artifacts live in three panes; Check and other output hides the tabs. */
function openTabs(payload) {
  views.c = payload.c || "";
  views.idl = payload.idl || "";
  views.client = payload.client || "";
  cursor = views.c;
  if (!views.c) {
    tabs.hidden = true;
    return;
  }
  tabs.hidden = false;
  setTab("c");
}

function closeTabs() {
  views.c = views.idl = views.client = "";
  cursor = "";
  tabs.hidden = true;
}

function setTab(which, focus) {
  cursor = views[which] || "";
  out.textContent = cursor || "Nothing for this tab yet.";
  tabButtons.forEach((button) => {
    const on = button.id === "tab-" + which;
    button.classList.toggle("on", on);
    button.setAttribute("aria-selected", String(on));
    button.tabIndex = on ? 0 : -1;
    if (on && focus) {
      button.focus();
    }
  });
}

tabButtons.forEach((button) => {
  button.addEventListener("click", () => setTab(button.id.slice(4)));
  button.addEventListener("keydown", (event) => {
    const order = ["c", "idl", "client"];
    const at = order.indexOf(button.id.slice(4));
    let next = -1;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") {
      next = (at + 1) % order.length;
    } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
      next = (at + order.length - 1) % order.length;
    } else if (event.key === "Home") {
      next = 0;
    } else if (event.key === "End") {
      next = order.length - 1;
    }
    if (next >= 0) {
      event.preventDefault();
      setTab(order[next], true);
    }
  });
});

document.getElementById("copy").addEventListener("click", async () => {
  if (!cursor) {
    return;
  }
  const copy = document.getElementById("copy");
  const label = copy.querySelector(".lbl") || copy;
  try {
    await navigator.clipboard.writeText(cursor);
    label.textContent = "Copied";
    setTimeout(() => {
      label.textContent = "Copy";
    }, 1200);
  } catch (err) {
    label.textContent = "Copy failed";
    setTimeout(() => {
      label.textContent = "Copy";
    }, 1600);
    show(cursor + "\n\n(Copy failed — select the text above.)", "on-info");
  }
});

source.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
    event.preventDefault();
    document.getElementById("check").click();
  }
});

function formatDiagnostics(rows) {
  if (!rows || !rows.length) {
    return "No problems.";
  }
  return rows
    .map((row) => {
      const where = row.file ? row.file + ":" + row.line + ":" + row.col + " " : "";
      const fix = row.fix ? "\n  fix: " + row.fix : "";
      return where + row.code + " " + row.message + fix;
    })
    .join("\n\n");
}

/* Brief button feedback: the label says what happened, then restores. */
function flash(id, label) {
  const button = document.getElementById(id);
  if (!button) {
    return;
  }
  const span = button.querySelector(".lbl") || button;
  const original = span.textContent;
  span.textContent = label;
  setTimeout(() => {
    span.textContent = original;
  }, 1400);
}

async function post(path, body, label) {
  if (!source.value.trim()) {
    show("Choose an example or paste a program first.", "on-info");
    return;
  }
  buttons.forEach((button) => {
    if (button) {
      button.disabled = true;
    }
  });
  out.setAttribute("aria-busy", "true");
  show(label, "on-info");
  try {
    const response = await fetch(path, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    const payload = await response.json();
    const rendered = render(path, response.status, payload);
    show(rendered.text, rendered.state);
  } catch (err) {
    show("The playground did not answer.\n" + err, "on-err");
  } finally {
    out.removeAttribute("aria-busy");
    buttons.forEach((button) => {
      if (button) {
        button.disabled = false;
      }
    });
  }
}

function render(path, status, payload) {
  if (payload.diagnostics && payload.diagnostics.length) {
    closeTabs();
    return { text: formatDiagnostics(payload.diagnostics), state: "on-diag" };
  }
  if (payload.ok === false) {
    closeTabs();
    const code = payload.code ? payload.code + " " : "";
    return {
      text: code + (payload.error || "Request failed (" + status + ")."),
      state: "on-err",
    };
  }
  if (path === "/v1/check") {
    closeTabs();
    flash("check", "\u2713 Checked");
    return { text: "No problems.", state: "on-ok" };
  }
  if (path === "/v1/emit") {
    if (!payload.idl && !payload.client) {
      closeTabs();
      return { text: payload.c || "Emit succeeded, but no C was returned.", state: "on-ok" };
    }
    openTabs(payload);
    flash("emit", "C ready");
    return { text: views.c, state: "on-ok" };
  }
  if (path === "/v1/compile") {
    closeTabs();
    flash("compile", "\u2713 Built");
    return {
      text: "Built program.so\nsha256 " + payload.so_sha256 + "\ncache " + payload.cache,
      state: "on-ok",
    };
  }
  closeTabs();
  return { text: "Done.", state: "on-ok" };
}

async function loadExample(name) {
  const response = await fetch("/examples/" + name);
  if (!response.ok) {
    show("Could not load the " + name + " example.", "on-err");
    return false;
  }
  source.value = await response.text();
  closeTabs();
  show("Loaded " + name + ". Check it, show the C, or compile.", "on-info");
  return true;
}

document.getElementById("reset").addEventListener("click", () => {
  loadExample(example.value || "counter");
});

example.addEventListener("change", () => {
  loadExample(example.value);
});

document.getElementById("check").addEventListener("click", () => {
  post("/v1/check", { source: source.value, filename: "program.py" }, "Checking…");
});

document.getElementById("emit").addEventListener("click", () => {
  post("/v1/emit", { source: source.value, filename: "program.py" }, "Generating C…");
});

document.getElementById("compile").addEventListener("click", () => {
  post("/v1/compile", { source: source.value, filename: "program.py" }, "Compiling… this can take a moment.");
});

fetch("/healthz")
  .then((response) => response.json())
  .then((health) => {
    if (!health.compile) {
      const button = document.getElementById("compile");
      button.hidden = true;
    }
  })
  .catch(() => {});

fetch("/examples")
  .then((response) => response.json())
  .then((payload) => {
    const names = payload.examples || [];
    names.forEach((name) => {
      const option = document.createElement("option");
      option.value = name;
      option.textContent = name;
      example.appendChild(option);
    });
    if (names.length) {
      loadExample(names[0]);
    } else {
      show("No examples are installed.", "on-info");
    }
  })
  .catch((err) => {
    show("Could not load examples.\n" + err, "on-err");
  });
