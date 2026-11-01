"use strict";

const { spawn } = require("child_process");
const vscode = require("vscode");

const collectionName = "pythsol";

function activate(context) {
  const collection = vscode.languages.createDiagnosticCollection(collectionName);
  let warned = false;

  async function lint(document) {
    if (!shouldCheck(document)) {
      collection.delete(document.uri);
      return;
    }
    const executable = vscode.workspace
      .getConfiguration("pythsol")
      .get("executable", "pythsol");
    let stdout;
    try {
      stdout = await runCheck(executable, document.uri.fsPath);
    } catch (err) {
      collection.delete(document.uri);
      if (!warned) {
        warned = true;
        vscode.window.showWarningMessage(
          "PythSol check failed to start. Set pythsol.executable. " + String(err)
        );
      }
      return;
    }
    let payload;
    try {
      payload = JSON.parse(stdout);
    } catch (err) {
      return;
    }
    const rows = Array.isArray(payload.diagnostics) ? payload.diagnostics : [];
    const diagnostics = rows.map((row) => toDiagnostic(document, row));
    collection.set(document.uri, diagnostics);
  }

  context.subscriptions.push(
    collection,
    vscode.workspace.onDidOpenTextDocument(lint),
    vscode.workspace.onDidSaveTextDocument(lint)
  );
  for (const document of vscode.workspace.textDocuments) {
    lint(document);
  }
}

function shouldCheck(document) {
  if (document.languageId !== "python") {
    return false;
  }
  const text = document.getText();
  return text.includes("pythsol");
}

function runCheck(executable, file) {
  return new Promise((resolve, reject) => {
    const child = spawn(executable, ["check", "--json", file], { windowsHide: true });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString();
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
    });
    child.on("error", reject);
    child.on("close", (code) => {
      if (code !== 0 && code !== 1) {
        reject(new Error(stderr || "pythsol check exited " + code));
        return;
      }
      resolve(stdout);
    });
  });
}

function toDiagnostic(document, row) {
  const line = Math.min(
    document.lineCount - 1,
    Math.max(0, Number(row.line || 1) - 1)
  );
  const text = document.lineAt(line).text;
  const col = Math.min(text.length, Math.max(0, Number(row.col || 1) - 1));
  const range = new vscode.Range(line, col, line, Math.min(text.length, col + 1));
  const message = row.fix ? row.message + "\nfix: " + row.fix : String(row.message || "");
  const diagnostic = new vscode.Diagnostic(range, message, vscode.DiagnosticSeverity.Error);
  diagnostic.source = "pythsol";
  diagnostic.code = row.code;
  return diagnostic;
}

function deactivate() {}

module.exports = { activate, deactivate };
