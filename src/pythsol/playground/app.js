const source = document.getElementById("source");
const out = document.getElementById("out");
const example = document.getElementById("example");
const buttons = ["check", "emit", "compile"].map((id) => document.getElementById(id));

function show(text) {
  out.textContent = text;
}

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
    return formatDiagnostics(payload.diagnostics);
  }
  if (payload.ok === false) {
    const code = payload.code ? payload.code + " " : "";
    return code + (payload.error || "Request failed (" + status + ").");
  }
  if (path === "/v1/check") {
    return "No problems.";
  }
  if (path === "/v1/emit") {
    return payload.c || "Emit succeeded, but no C was returned.";
  }
  if (path === "/v1/compile") {
    return "Built program.so\nsha256 " + payload.so_sha256 + "\ncache " + payload.cache;
  }
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
