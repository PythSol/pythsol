const source = document.getElementById("source");
const out = document.getElementById("out");
const example = document.getElementById("example");
const tabs = document.getElementById("tabs");
const buttons = ["check", "emit", "compile"].map((id) => document.getElementById(id));
const tabButtons = ["c", "idl", "client"].map((id) => document.getElementById("tab-" + id));
const views = { c: "", idl: "", client: "" };
let cursor = "";

function show(text) {
  out.textContent = text;
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

function setTab(which) {
  cursor = views[which] || "";
  out.textContent = cursor || "Nothing for this tab yet.";
  tabButtons.forEach((button) => {
    const on = button.id === "tab-" + which;
    button.classList.toggle("on", on);
    button.setAttribute("aria-pressed", String(on));
  });
}

tabButtons.forEach((button) => {
  button.addEventListener("click", () => setTab(button.id.slice(4)));
});

document.getElementById("copy").addEventListener("click", async () => {
  if (!cursor) {
    return;
  }
  try {
    await navigator.clipboard.writeText(cursor);
    const copy = document.getElementById("copy");
    copy.textContent = "Copied";
    setTimeout(() => {
      copy.textContent = "Copy";
    }, 1200);
  } catch (err) {
    show(cursor + "\n\n(Copy failed — select the text above.)");
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

async function post(path, body, label) {
  if (!source.value.trim()) {
    show("Choose an example or paste a program first.");
    return;
  }
  buttons.forEach((button) => {
    if (button) {
      button.disabled = true;
    }
  });
  show(label);
  try {
    const response = await fetch(path, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    const payload = await response.json();
    show(render(path, response.status, payload));
  } catch (err) {
    show("The playground did not answer.\n" + err);
  } finally {
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
    return formatDiagnostics(payload.diagnostics);
  }
  if (payload.ok === false) {
    closeTabs();
    const code = payload.code ? payload.code + " " : "";
    return code + (payload.error || "Request failed (" + status + ").");
  }
  if (path === "/v1/check") {
    closeTabs();
    return "No problems.";
  }
  if (path === "/v1/emit") {
    if (!payload.idl && !payload.client) {
      closeTabs();
      return payload.c || "Emit succeeded, but no C was returned.";
    }
    openTabs(payload);
    return views.c;
  }
  if (path === "/v1/compile") {
    closeTabs();
    return "Built program.so\nsha256 " + payload.so_sha256 + "\ncache " + payload.cache;
  }
  closeTabs();
  return "Done.";
}

async function loadExample(name) {
  show("Loading " + name + "…");
  const response = await fetch("/examples/" + name);
  if (!response.ok) {
    show("Could not load the " + name + " example.");
    return;
  }
  source.value = await response.text();
  show("Loaded " + name + ". Check it, show the C, or compile.");
}

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
      show("No examples are installed.");
    }
  })
  .catch((err) => {
    show("Could not load examples.\n" + err);
  });
